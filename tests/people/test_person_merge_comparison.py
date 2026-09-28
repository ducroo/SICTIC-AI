"""Policy regressions and opt-in, local-only merger comparison.

SICTIC_PERSON_MERGE_DATASET selects a parsed local dataset; extraction runs once.
SICTIC_PERSON_MERGE_REPORT optionally saves timings and complete result signatures.
Without a dataset, the benchmark uses deterministic synthetic candidates.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import string
from time import perf_counter

import pytest
from rapidfuzz import fuzz

from lib.datasets.chunking import build_chunk
from lib.people.model import Person


def old_merge(people, candidate):
    # Frozen pre-refactor behavior, including the second consolidation pass.
    existing = candidate.find_best_match(people)
    if existing is None:
        people.append(candidate)
        return
    existing.merge(candidate)
    for other in list(people):
        if other is not existing and existing.matches(other):
            existing.merge(other)
            people.remove(other)


def signature(people):
    return sorted((p.full_name, p.linkedin_id, sorted(p.email_addresses),
                   sorted(c.chunk_id for c in p.mentions),
                   sorted(c.document_name for c in p.dossier)) for p in people)


def test_default_retains_second_pass_and_evidence():
    chunks = [build_chunk(str(i), f'{i}.md', 1, 0) for i in range(4)]
    inputs = [Person(full_name='Jane Doe', mentions=[chunks[0]]),
              Person(linkedin_id='jane-id', mentions=[chunks[1]]),
              Person(full_name='Jane Doe', linkedin_id='jane-id', mentions=[chunks[2]]),
              Person(full_name='Jane Doe', linkedin_id='different-id', mentions=[chunks[3]])]
    expected = []
    for candidate in deepcopy(inputs):
        old_merge(expected, candidate)
    actual = Person.merge_all(deepcopy(inputs))
    assert actual == expected
    assert len(actual) == 2
    assert len(actual[0].mentions) == 3


def test_alternative_groups_ids_first_and_preserves_identity_boundary():
    inputs = [Person(full_name='Jane Doe'), Person(linkedin_id='jane-doe-123'),
              Person(full_name='Jane Doe', linkedin_id='other-jane'),
              Person(linkedin_id='jane-doe-123', email_addresses=['jane@example.com'])]
    result = Person.merge_all_alternative(inputs)
    assert len(result) == 2
    assert result[0].linkedin_id == 'jane-doe-123'
    assert result[0].full_name == 'Jane Doe'
    assert result[0].email_addresses == ['jane@example.com']


def test_email_restricts_search_but_requires_fuzzy_confirmation():
    result = Person.merge_all_alternative([
        Person(full_name='Alice Green', linkedin_id='alice', email_addresses=['team@example.com']),
        Person(full_name='Bob Black', linkedin_id='bob'),
        Person(full_name='Bob Black', email_addresses=['team@example.com']),
    ])
    assert len(result) == 3  # Exact Bob outside the email subset cannot win.


def test_multiple_email_targets_choose_best_and_index_new_emails():
    first = Person(full_name='Alice Green', linkedin_id='alice', email_addresses=['team@example.com'])
    second = Person(full_name='Bob Black', linkedin_id='bob', email_addresses=['team@example.com'])
    result = Person.merge_all_alternative([first, second,
        Person(full_name='Bob Black', email_addresses=['team@example.com', 'new@example.com']),
        Person(full_name='Alice Green', email_addresses=['new@example.com'])])
    assert len(result) == 3  # Newly added email restricts Alice to Bob; no merge.
    assert result[1].email_addresses == ['team@example.com', 'new@example.com']


def test_named_email_group_precedes_email_only_and_retains_evidence():
    one = build_chunk('contact', 'contact.md', 1, 0)
    two = build_chunk('team', 'team.md', 1, 0)
    sparse = Person(email_addresses=['shared@example.com'], mentions=[one])
    named = Person(full_name='Jane Doe', email_addresses=['shared@example.com'], mentions=[two])
    result = Person.merge_all_alternative([sparse, named, Person(email_addresses=['shared@example.com'])])
    assert len(result) == 1
    assert result[0] is named
    assert result[0].mentions == [two, one]


def test_email_only_chooses_first_target_even_when_multiple_ids_match():
    first = Person(full_name='Alice Green', linkedin_id='alice', email_addresses=['team@example.com'])
    second = Person(full_name='Bob Black', linkedin_id='bob', email_addresses=['bob@example.com'])
    sparse = Person(email_addresses=['bob@example.com', 'team@example.com', 'new@example.com'])
    result = Person.merge_all_alternative([first, second, sparse, Person(email_addresses=['new@example.com'])])
    assert result == [first, second]
    assert first.email_addresses == ['team@example.com', 'bob@example.com', 'new@example.com']
    assert second.email_addresses == ['bob@example.com']


def test_repeated_email_only_objects_merge_without_any_name():
    result = Person.merge_all_alternative([Person(email_addresses=['support@example.com']) for _ in range(5)])
    assert len(result) == 1
    assert result[0].full_name == ''


def test_derived_names_are_symmetric_but_not_compared_to_each_other():
    full = Person(full_name='Jane Doe')
    email = Person(email_addresses=['jane.doe@example.com'])
    linkedin = Person(linkedin_id='jane-doe-123')
    assert full.name_match_score(email) == email.name_match_score(full) == 100
    assert full.name_match_score(linkedin) == linkedin.name_match_score(full) == 100
    assert email.name_match_score(linkedin) == 0
    assert len(Person.merge_all_alternative([email, linkedin])) == 2
    assert Person(full_name='lucas').name_match_score(Person(full_name='lucas du croo de jongh')) == pytest.approx(37.037037)


def test_strict_threshold_and_no_substring_shortcut():
    first, second = 'abcdefghijklmnopqrst', 'abcdefghijklmnopqxyz'
    assert fuzz.token_sort_ratio(first, second) == 85
    assert len(Person.merge_all_alternative([Person(full_name=first), Person(full_name=second)])) == 2
    assert len(Person.merge_all_alternative([Person(full_name='Lucas'), Person(full_name='Lucas du Croo de Jongh')])) == 2


@pytest.mark.parametrize('name, variant', [
    ('Иван Петров', 'ИВАН-ПЕТРОВ'),
    ('王小明', '王小明'),
    ('René Müller', 'Rene\u0301_Mu\u0308ller'),
])
def test_unicode_names_match_without_changing_identity_or_evidence(name, variant):
    one = build_chunk(name, 'one.md', 1, 0)
    two = build_chunk(variant, 'two.md', 1, 0)
    first = Person(full_name=name, mentions=[one])
    second = Person(full_name=variant, mentions=[two])
    identifier = first.identifier
    assert first.name_match_score(second) == 100
    assert first.identifier == identifier
    result = Person.merge_all_alternative([first, second])
    assert len(result) == 1
    assert result[0].mentions == [one, two]
    assert result[0].full_name in (name, variant)


def test_distinct_cyrillic_names_do_not_collapse_to_empty_matches():
    first = Person(full_name='Иван Петров')
    second = Person(full_name='Ольга Смирнова')
    assert first.name_match_score(second) < 85
    assert len(Person.merge_all_alternative([first, second])) == 2


def test_unicode_linkedin_hint_matches_without_rewriting_id():
    person = Person(linkedin_id='иван-петров-123')
    identifier = person.linkedin_id
    result = Person.merge_all_alternative([Person(full_name='Иван Петров'), person])
    assert len(result) == 1
    assert result[0].linkedin_id == identifier


def test_profile_name_replaces_stale_index_and_preserves_metadata():
    person = Person(full_name='Completely Wrong Name', linkedin_id='jane-id')
    profile = Person(linkedin_id='jane-id', linkedin_profile={'fullName': 'Jane Doe'})
    result = Person.merge_all_alternative([person, profile, Person(full_name='Completely Wrong Name'), Person(full_name='Jane Doe')])
    assert len(result) == 2
    assert result[0].full_name == 'Jane Doe'
    assert result[0].linkedin_profile == profile.linkedin_profile


def test_repeated_references_are_unique_even_without_a_full_name():
    person = Person(email_addresses=['team@example.com'])
    assert Person.merge_all_alternative([person, person]) == [person]


def test_native_matching_agrees_with_pairwise_policy_reference():
    rng = random.Random(7)
    inputs = [Person(full_name=name, linkedin_id=f'person-{i}',
                     email_addresses=['shared@example.com'])
              for i, name in enumerate(['Jane Doe', 'Janet Doe', 'Alice Green', 'Bob Black'])]
    for _ in range(60):
        inputs.append(Person(full_name=rng.choice(['Jane Doe', 'Jane Do', 'Alice Green', 'Bob Black', '']),
                             email_addresses=rng.choice([[], ['shared@example.com'], ['jane.doe@example.com']])))
    targets = []
    for candidate in sorted(deepcopy(inputs), key=lambda p: 0 if p.linkedin_id else
                            (1 if p.full_name.strip() else 2) if p.email_addresses else 3):
        exact = next((p for p in targets if candidate.linkedin_id and p.linkedin_id == candidate.linkedin_id), None)
        if exact is None:
            email_matches = [p for p in targets if set(p.email_addresses) & set(candidate.email_addresses)]
            if email_matches and not candidate.linkedin_id and not candidate.full_name.strip():
                email_matches[0].merge(candidate)
                continue
            scored = [(candidate.name_match_score(p), p) for p in email_matches or targets
                      if not (p.linkedin_id and candidate.linkedin_id and p.linkedin_id != candidate.linkedin_id)]
            best = max(scored, key=lambda item: item[0], default=(0, None))
            exact = best[1] if best[0] > 85 else None
        if exact is None:
            targets.append(candidate)
        else:
            exact.merge(candidate)
    assert Person.merge_all_alternative(deepcopy(inputs)) == targets


def test_extract_raw_once_retains_unmerged_evidence():
    from lib.people.extraction import PersonExtractor
    from tests.people.test_extraction import FakeNER
    chunks = [build_chunk('Jane Doe jane.doe@example.com', f'{i}.md', 1, 0) for i in range(2)]
    raw = PersonExtractor('fake', batch_size=8, nlp=FakeNER()).extract_candidates(chunks)
    assert len(raw) == 4
    original = deepcopy(raw)
    for merge in [Person.merge_all, Person.merge_all_alternative]:
        merged = merge(deepcopy(raw))
        assert {c.chunk_id for p in merged for c in p.mentions} == {c.chunk_id for c in chunks}
    assert raw == original


def test_merger_benchmark(monkeypatch):
    if not os.getenv('SICTIC_PERSON_MERGE_BENCHMARK'):
        pytest.skip('opt-in merger benchmark')
    dataset = os.getenv('SICTIC_PERSON_MERGE_DATASET')
    extraction_seconds = None
    if dataset:
        from lib.datasets.source import iter_parsed_chunks
        from lib.people.extraction import PersonExtractor
        from lib.infrastructure.configuration import load_repository_config
        from lib.storage import reset_storage_singleton
        from lib.people.linkedin.identity import is_linkedin_document
        from lib.people.linkedin import LinkedInResolver
        root = os.getenv('SICTIC_DISCOVERY_BENCHMARK_STORAGE')
        runtime = os.getenv('SICTIC_DISCOVERY_BENCHMARK_RUNTIME')
        if not root or not runtime:
            pytest.fail('Local comparison requires SICTIC_DISCOVERY_BENCHMARK_STORAGE and SICTIC_DISCOVERY_BENCHMARK_RUNTIME')
        monkeypatch.setenv('LOCAL_STORAGE_PATH', root)
        monkeypatch.setenv('LOCAL_DATA_PATH', runtime)
        reset_storage_singleton()
        config = load_repository_config('persons_in_dataset', 'discovery')
        try:
            print(f'{dataset}: extracting local candidates', flush=True)
            started = perf_counter()
            chunks = (chunk for chunk in iter_parsed_chunks(dataset)
                      if not is_linkedin_document(chunk.document_name))
            raw = PersonExtractor(**config['ner']).extract_candidates(chunks)
            raw.extend(LinkedInResolver(dataset).get_cached_persons())
            extraction_seconds = perf_counter() - started
            print(f'{dataset}: {len(raw)} raw candidates in {extraction_seconds:.2f}s', flush=True)
        finally:
            reset_storage_singleton()
        assert raw, 'No candidates extracted; check the dataset and storage roots'
    else:
        rng = random.Random(42)
        raw = [Person(full_name=''.join(rng.choices(string.ascii_lowercase, k=10)) + ' ' +
                      ''.join(rng.choices(string.ascii_lowercase, k=10))) for _ in range(2000)]
    report = {'dataset': dataset, 'input_count': len(raw), 'extraction_seconds': extraction_seconds}
    for name, merge in [('legacy', Person.merge_all), ('new', Person.merge_all_alternative)]:
        inputs = deepcopy(raw)
        print(f'{dataset}: starting {name} merger', flush=True)
        started = perf_counter()
        result = merge(inputs)
        report[name] = {'seconds': perf_counter() - started, 'count': len(result), 'people': signature(result)}
        print(f'{dataset}: {name} finished: {len(result)} people, {report[name]["seconds"]:.2f}s', flush=True)
    report['same_result'] = report['legacy']['people'] == report['new']['people']
    destination = os.getenv('SICTIC_PERSON_MERGE_REPORT')
    if destination:
        Path(destination).write_text(json.dumps(report, indent=2))
    print(json.dumps({key: ({k: v for k, v in value.items() if k != 'people'} if isinstance(value, dict) else value)
                      for key, value in report.items()}))
