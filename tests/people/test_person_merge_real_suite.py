"""Opt-in local comparison on a saved dossier selection; no online services.

SICTIC_PERSON_MERGE_SUITE points to a directory containing selection.json.
Uses SICTIC_DISCOVERY_BENCHMARK_STORAGE and SICTIC_DISCOVERY_BENCHMARK_RUNTIME.
Raw snapshots are immutable experiment inputs; delete explicitly to re-extract.
Timings include identical provenance bookkeeping for both merger policies.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import fields
import gzip
import json
import os
from pathlib import Path
from time import perf_counter

import pytest

from lib.datasets.models import Chunk
from lib.people.model import Person

TRACE = '_merge_benchmark'
ROOT = os.getenv('SICTIC_PERSON_MERGE_SUITE')
DATASETS = ([r['dataset'] for r in json.loads((Path(ROOT) / 'selection.json').read_text())['datasets']]
            if ROOT else [None])


def save_snapshot(path, people):
    chunks = {}
    rows = []
    for person in people:
        row = {f.name: getattr(person, f.name) for f in fields(Person)}
        for name in ('mentions', 'dossier'):
            row[name] = [c.chunk_id for c in getattr(person, name)]
            chunks.update({c.chunk_id: c.model_dump(mode='json') for c in getattr(person, name)})
        rows.append(row)
    with gzip.open(path, 'wt', encoding='utf-8') as handle:
        json.dump({'people': rows, 'chunks': chunks}, handle, ensure_ascii=False)


def load_snapshot(path):
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        saved = json.load(handle)
    chunks = {key: Chunk.model_validate(value) for key, value in saved['chunks'].items()}
    for row in saved['people']:
        for name in ('mentions', 'dossier'):
            row[name] = [chunks[key] for key in row[name]]
    return [Person(**row) for row in saved['people']]


def information(people):
    return {
        'linkedin_ids': {p.linkedin_id for p in people if p.linkedin_id},
        'emails': {email for p in people for email in p.email_addresses},
        'mentions': {c.chunk_id for p in people for c in p.mentions},
        'dossier_documents': {c.document_name for p in people for c in p.dossier},
    }


def describe(person):
    sources = []
    for chunk in person.mentions:
        if len(sources) == 3:
            break
        sources.append({'document': chunk.document_name, 'text': chunk.text[:700]})
    return {'full_name': person.full_name, 'linkedin_id': person.linkedin_id,
            'emails': person.email_addresses,
            'members': sorted(map(int, person.adhoc_data.get(TRACE, {}))),
            'sources': sources}


def metrics(people, original):
    current = information(people)
    identities = Counter((p.full_name, p.linkedin_id, tuple(sorted(p.email_addresses))) for p in people)
    ids = Counter(p.linkedin_id for p in people if p.linkedin_id)
    sparse = Counter(tuple(sorted(p.email_addresses)) for p in people
                     if p.email_addresses and not p.linkedin_id and not p.full_name.strip())
    names = Counter(p.full_name.strip().casefold() for p in people if p.full_name.strip())
    return {
        'count': len(people),
        'groups': {
            'linkedin': sum(bool(p.linkedin_id) for p in people),
            'name_email': sum(not p.linkedin_id and bool(p.full_name.strip()) and bool(p.email_addresses) for p in people),
            'email_only': sum(not p.linkedin_id and not p.full_name.strip() and bool(p.email_addresses) for p in people),
            'other': sum(not p.linkedin_id and not p.email_addresses for p in people),
        },
        'duplicate_identity_rows': sum(n - 1 for n in identities.values()),
        'duplicate_linkedin_ids': sum(n - 1 for n in ids.values()),
        'duplicate_email_only_rows': sum(n - 1 for n in sparse.values()),
        'repeated_full_names': sum(n - 1 for n in names.values()),
        'lost': {key: sorted(original[key] - current[key]) for key in original},
        'retained_counts': {key: len(value) for key, value in current.items()},
    }


def compare_groups(old, new, raw):
    """Connected components of the two partitions of original candidate IDs."""
    rows = {'legacy': [describe(p) for p in old], 'new': [describe(p) for p in new]}
    owners = {side: {member: i for i, row in enumerate(data) for member in row['members']}
              for side, data in rows.items()}
    edges = {}
    for member in range(len(raw)):
        left, right = ('legacy', owners['legacy'][member]), ('new', owners['new'][member])
        edges.setdefault(left, set()).add(right)
        edges.setdefault(right, set()).add(left)
    visited, changed, unchanged = set(), [], []
    for start in edges:
        if start in visited:
            continue
        pending, component = [start], []
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            pending.extend(edges[node] - visited)
        sides = {side: [rows[side][i] for s, i in sorted(component) if s == side]
                 for side in rows}
        same = (len(sides['legacy']) == len(sides['new']) == 1
                and {k:v for k,v in sides['legacy'][0].items() if k != 'sources'}
                == {k:v for k,v in sides['new'][0].items() if k != 'sources'})
        members = {m for data in sides.values() for row in data for m in row['members']}
        sides['input_names'] = sorted({raw[i].full_name for i in members if raw[i].full_name})
        sides['input_linkedin_ids'] = sorted({raw[i].linkedin_id for i in members if raw[i].linkedin_id})
        sides['input_emails'] = sorted({e for i in members for e in raw[i].email_addresses})
        (unchanged if same else changed).append(sides)
    return {'changed': changed, 'unchanged': unchanged}


@pytest.mark.parametrize('dataset', DATASETS)
def test_real_dossier_comparison(dataset, monkeypatch):
    if not ROOT:
        pytest.skip('opt-in 36-dossier comparison')
    from lib.infrastructure.configuration import load_repository_config
    from lib.storage import reset_storage_singleton
    from lib.datasets.source import iter_parsed_chunks
    from lib.people.extraction import PersonExtractor
    from lib.people.linkedin import LinkedInResolver
    from lib.people.linkedin.identity import is_linkedin_document
    for target, source in [('LOCAL_STORAGE_PATH', 'SICTIC_DISCOVERY_BENCHMARK_STORAGE'),
                           ('LOCAL_DATA_PATH', 'SICTIC_DISCOVERY_BENCHMARK_RUNTIME')]:
        monkeypatch.setenv(target, os.environ[source])
    reset_storage_singleton()
    directory = Path(ROOT) / dataset
    directory.mkdir(exist_ok=True)
    snapshot = directory / 'raw.json.gz'
    try:
        if snapshot.exists():
            raw = load_snapshot(snapshot)
        else:
            print(f'\n{dataset}: extracting raw candidates', flush=True)
            count = 0
            def chunks():
                nonlocal count
                for chunk in iter_parsed_chunks(dataset):
                    if not is_linkedin_document(chunk.document_name):
                        count += 1
                        if count % 2000 == 0:
                            print(f'{dataset}: extraction {count} chunks', flush=True)
                        yield chunk
            raw = PersonExtractor(**load_repository_config('persons_in_dataset', 'discovery')['ner']).extract_candidates(chunks())
            raw.extend(LinkedInResolver(dataset).get_cached_persons())
            save_snapshot(snapshot, raw)
        assert raw, f'{dataset}: no candidates'
        print(f'{dataset}: {len(raw)} candidates saved', flush=True)
        original = information(raw)
        for i, person in enumerate(raw):
            person.adhoc_data[TRACE] = {str(i): True}
        results = {}
        report = {'dataset': dataset, 'input_count': len(raw), 'timing': 'Single run per algorithm; includes candidate provenance metadata; excludes extraction, deepcopy and report generation'}
        order = [('legacy', Person.merge_all), ('new', Person.merge_all_alternative)]
        if DATASETS.index(dataset) % 2:
            order.reverse()
        for label, merge in order:
            inputs = deepcopy(raw)
            print(f'{dataset}: {label} merge starting', flush=True)
            started = perf_counter()
            result = merge(inputs)
            elapsed = perf_counter() - started
            results[label] = result
            report[label] = {'seconds': elapsed, **metrics(result, original)}
            print(f'{dataset}: {label} {elapsed:.3f}s, {len(result)} records', flush=True)
        groups = compare_groups(results['legacy'], results['new'], raw)
        report['changed_groups'] = len(groups['changed'])
        report['unchanged_groups'] = len(groups['unchanged'])
        (directory / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))
        with gzip.open(directory / 'groups.json.gz', 'wt', encoding='utf-8') as handle:
            json.dump(groups, handle, ensure_ascii=False)
        save_snapshot(directory / 'legacy.json.gz', results['legacy'])
        save_snapshot(directory / 'new.json.gz', results['new'])
        for label in results:
            assert not any(report[label]['lost'].values()), (label, report[label]['lost'])
    finally:
        reset_storage_singleton()


def test_snapshot_roundtrip(tmp_path):
    from lib.datasets.chunking import build_chunk
    person = Person(full_name='Иван Петров', email_addresses=['ivan@example.com'],
                    mentions=[build_chunk('Иван Петров', 'team.md', 1, 0)])
    path = tmp_path / 'raw.json.gz'
    save_snapshot(path, [person])
    assert load_snapshot(path) == [person]
