"""Provider taxonomies, shared retrieval, validation and insight compatibility."""

import copy
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from lib.datasets.manifest import IngestionManifest
from lib.datasets.models import Chunk
from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.ai_text_generation.json import validate_json_schema, validate_schema
from lib.infrastructure.configuration import config_cache_key, load_repository_config
from lib.insights import InsightFile
from lib.storage import get_storage
from skills.startup_sector.taxonomy import derive, provider_record, response_schema, review_classification

module = importlib.import_module('skills.startup_sector.startup_sector')


def legacy(**changes):
    result = dict(sector='EnergyTech', sector_confidence='H', rationale='Energy software.',
                  evidence=['offering.md, page 3: heating optimisation.'])
    return result | changes


def classification(reference, **changes):
    choices = {name: dict(primary=None, secondary=[]) for name in reference['components']}
    choices['industries']['primary'] = reference['components']['industries']['categories'][0]['id']
    return dict(classifications=choices, confidence='H', rationale='Supported core offering.',
                evidence=['offering.md, page 3: heating optimisation.']) | changes


def install_dataset(name='example-co', domain='startups', revision='revision-1'):
    location = dataset_location_for_domain(name, domain)
    storage = get_storage()
    storage.mkdir(location.raw_rel)
    storage.write_text(f'{location.raw_rel}/offering.md', 'Heating optimisation software.')
    manifest = IngestionManifest.load(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = revision
    manifest.save()
    return location


@pytest.fixture
def workflow(mock_env, monkeypatch):
    monkeypatch.setenv('RANKED_LLMS', 'ollama/test_model:1b')
    install_dataset()
    config = load_repository_config('startup_sector')
    prepare = AsyncMock(return_value=SimpleNamespace(dataset_slug='example-co'))
    sync = AsyncMock()
    chunk = Chunk(chunk_id='offering-1', document_name='offering.md', page_number=3,
                  last_modified=1.0, text='Licenses heating-network optimisation software to energy operators.')
    retrieve = AsyncMock(return_value=[chunk])

    async def generate(prompt, schema, reviewer, **kwargs):
        reference = json.loads(prompt.split('Provider taxonomy:\n', 1)[1])
        result = classification(reference)
        validate_json_schema(result, schema)
        assert reviewer(result).accepted
        return result

    generation = AsyncMock(side_effect=generate)
    monkeypatch.setattr(module, 'ensure_startup_dataset', prepare)
    monkeypatch.setattr(module, 'sync_datasets', sync)
    monkeypatch.setattr(module, 'dataset_search', retrieve)
    monkeypatch.setattr(module, 'generate_json', generation)
    return SimpleNamespace(prepare=prepare, sync=sync, retrieve=retrieve, generate=generation,
                           config=config, chunk=chunk)


def test_references_are_complete_for_the_agreed_snapshots_and_internally_consistent(mock_env):
    config = load_repository_config('startup_sector')
    assert set(config['taxonomies']) == {'dealum', 'dealroom', 'pitchbook', 'startupticker'}
    assert len(config['queries']) == 3
    expected = {'dealum': {'industries': 53, 'technologies': 102},
                'dealroom': {'industries': 31, 'subindustries': 71, 'technologies': 19, 'tags': 50},
                'pitchbook': {'industries': 218, 'verticals': 59},
                'startupticker': {'industries': 8}}
    for key, ref in config['taxonomies'].items():
        assert {d: len(v['categories']) for d, v in ref['components'].items()} == expected[key]
        assert ref['sources'] and ref['status'] and ref['version']
        components = ref['components'] | ref['derived_components']
        for name, component in components.items():
            ids = [c['id'] for c in component['categories']]
            assert len(ids) == len(set(ids))
            for c in component['categories']:
                assert c['name'].strip() and c['description'].strip() and c['description_source']
                if component.get('parent_component'):
                    parent = component['parent_component']
                    assert parent != name
                    assert set(c['parents']) <= {v['id'] for v in components[parent]['categories']}
                    assert c['parents']
            # The configured hierarchy must be acyclic.
            seen = {name}
            while component.get('parent_component'):
                parent = component['parent_component']
                assert parent not in seen
                seen.add(parent)
                component = components[parent]
        for group in ref['reporting_groups']:
            if group['rule']:
                for term in group['rule']['any'] + group['rule']['exclude']:
                    assert term['id'] in {c['id'] for c in components[term['component']]['categories']}
            else:
                assert group['unavailable_reason']
        original = copy.deepcopy(ref)
        schema = response_schema(ref, config['response_schema'])
        validate_schema(schema)
        validate_json_schema(classification(ref), schema)
        assert ref == original
    assert 'unverified' in config['taxonomies']['pitchbook']['status']
    assert 'INCOMPLETE' in config['taxonomies']['dealum']['status']
    assert 'product_types' not in config
    assert 'company_category' not in config['taxonomies']['dealum']['components']


@pytest.mark.asyncio
async def test_four_calls_share_balanced_evidence_and_identical_prefix(workflow):
    [insight] = await module.startup_sector('Example Co')
    assert isinstance(insight, InsightFile)
    assert insight.filename == 'startup-sector-example-co-test-model-1b.json'
    assert insight.directory == 'storage/startups/example-co/insights'
    workflow.prepare.assert_awaited_once_with('Example Co', sync_after_import=False)
    workflow.sync.assert_awaited_once_with(['example-co'], raise_on_error=True)
    assert [c.args for c in workflow.retrieve.await_args_list] == [
        ('example-co', q) for q in workflow.config['queries']]
    assert [c.kwargs for c in workflow.retrieve.await_args_list] == [
        dict(max_chunks=n, raise_on_error=True) for n in (9, 8, 8)]
    assert workflow.generate.await_count == 4
    prefixes = {c.kwargs['cacheable_prompt_prefix'] for c in workflow.generate.await_args_list}
    assert len(prefixes) == 1
    prefix = prefixes.pop()
    assert workflow.chunk.to_md() in prefix
    assert 'startup_profile' not in prefix
    for call in workflow.generate.await_args_list:
        ref = json.loads(call.args[0].split('Provider taxonomy:\n', 1)[1])
        assert call.args[1] == response_schema(ref, workflow.config['response_schema'])
    result = json.loads(insight.content())
    assert set(result['providers']) == set(workflow.config['taxonomies'])
    for key, ref in workflow.config['taxonomies'].items():
        assert result['providers'][key] == provider_record(classification(ref), ref)
    assert await module.startup_sector_as_dict('example-co') == result
    assert workflow.generate.await_count == 4
    assert workflow.retrieve.await_count == 3


@pytest.mark.asyncio
async def test_product_and_customer_passages_survive_technical_results(workflow):
    product = workflow.chunk.model_copy(update={'text': 'Product: cognitive training reduces cravings.'})
    customer = workflow.chunk.model_copy(update={
        'chunk_id': 'customer-1', 'text': 'Customers: clinics buy a therapeutic intervention.'})
    technical = [
        workflow.chunk.model_copy(update={
            'chunk_id': f'technical-{i}', 'text': f'Technical detail {i}: predictive personalisation.'})
        for i in range(7)
    ]
    workflow.retrieve.side_effect = [[product], [customer, product], [product, *technical]]
    await module.startup_sector('example-co')
    for call in workflow.generate.await_args_list:
        prefix = call.kwargs['cacheable_prompt_prefix']
        assert prefix.count(product.to_md()) == 1
        assert prefix.count(customer.to_md()) == 1
        assert prefix.index(product.text) < prefix.index(customer.text) < prefix.index(technical[0].text)
        assert all(c.to_md() in prefix for c in technical)
        assert all(q in prefix for q in workflow.config['queries'])


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', [0, 1, 2])
async def test_missing_evidence_section_is_explicit_without_discarding_other_results(workflow, missing):
    results = [[workflow.chunk], [workflow.chunk], [workflow.chunk]]
    results[missing] = []
    workflow.retrieve.side_effect = results
    await module.startup_sector('example-co')
    assert workflow.generate.await_count == 4
    prefix = workflow.generate.await_args_list[0].kwargs['cacheable_prompt_prefix']
    assert f"{workflow.config['queries'][missing]}\n\nNo source passages retrieved" in prefix
    assert prefix.count(workflow.chunk.to_md()) == 1


@pytest.mark.asyncio
async def test_latest_application_proposition_is_included_even_without_search_hits(workflow):
    location = dataset_location_for_domain('example-co', 'startups')
    storage = get_storage()
    for day, identifier, product in [
        ('2024-01-01', 1, 'Superseded product'),
        ('2026-01-01', 2, 'Cognitive training reduces cravings'),
    ]:
        folder = f'{location.raw_rel}/dealum/{day}'
        storage.mkdir(folder)
        storage.write_text(f'{folder}/manifest.json', json.dumps({'dealum_id': identifier}))
        # Include a long customer statement: mandatory context must not silently
        # keep only the first search-sized chunk of an application answer.
        storage.write_text(
            f'{folder}/application.md.txt',
            f'### solution_summary\n\n{product}\n\n'
            '### customers_and_users\n\nClinics buy this intervention. ' + 'Detail. ' * 200
            + 'Final customer fact.\n\n'
            '### technologies\n\nUnverified supplied technology label\n',
        )
    workflow.retrieve.return_value = []
    await module.startup_sector('example-co')
    assert workflow.generate.await_count == 4
    for call in workflow.generate.await_args_list:
        prefix = call.kwargs['cacheable_prompt_prefix']
        assert 'dealum/2026-01-01/application.md.txt' in prefix
        assert 'Cognitive training reduces cravings' in prefix
        assert 'Clinics buy this intervention.' in prefix
        assert 'Final customer fact.' in prefix
        assert 'Superseded product' not in prefix
        assert 'Unverified supplied technology label' not in prefix


def test_application_proposition_skips_generated_datasets(workflow):
    install_dataset('temporary-co', 'generated')
    assert module._application_proposition('temporary-co', workflow.config['proposition_fields']) == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('retrieval', ['evidence', 'empty', 'failure'])
async def test_shared_search_integrates_three_queries_and_deduplicates(workflow, monkeypatch, mocker, retrieval):
    search = importlib.import_module('lib.datasets.search')
    monkeypatch.setattr(module, 'dataset_search', search.dataset_search)
    monkeypatch.setattr(search, 'sync_datasets', workflow.sync)
    monkeypatch.setenv('RERANK_MODEL', '')
    embeddings = mocker.patch.object(search, 'EmbeddingService').return_value
    embeddings.embed_many = AsyncMock(side_effect=lambda queries: [[0.1, 0.2] for _ in queries])
    adapter = mocker.patch.object(search, 'QdrantAdapter').return_value
    adapter.sparse_enabled.return_value = True
    point = SimpleNamespace(id='offering-1', score=.9, payload={
        'document_name': 'offering.md', 'page_number': 3,
        'last_modified': 1.0, 'text': workflow.chunk.text})
    adapter.query_hybrid.return_value = [point, point] if retrieval == 'evidence' else []
    if retrieval == 'failure':
        adapter.query_hybrid.side_effect = RuntimeError('index unavailable')
        with pytest.raises(RuntimeError, match='Semantic search failed'):
            await module.startup_sector('example-co')
        workflow.generate.assert_not_awaited()
        return
    await module.startup_sector('example-co')
    assert [c.args for c in embeddings.embed_many.await_args_list] == [
        ([q],) for q in workflow.config['queries']]
    assert adapter.query_hybrid.call_count == 3
    if retrieval == 'empty':
        workflow.generate.assert_not_awaited()
    else:
        assert workflow.generate.await_count == 4
        assert all(c.kwargs['cacheable_prompt_prefix'].count(workflow.chunk.text) == 1
                   for c in workflow.generate.await_args_list)


@pytest.mark.parametrize('problem', ['unknown', 'duplicate', 'too-many', 'null-secondary',
                                    'missing-evidence', 'bad-confidence', 'extra-field'])
def test_schema_enforces_ids_limits_and_evidence(mock_env, problem):
    config = load_repository_config('startup_sector')
    ref = config['taxonomies']['dealum']
    result = classification(ref)
    choice = result['classifications']['industries']
    if problem == 'unknown': choice['primary'] = 'invented'
    elif problem == 'duplicate': choice['secondary'] = ['energy', 'energy']
    elif problem == 'too-many': choice['secondary'] = ['energy', 'defence', 'gaming']
    elif problem == 'null-secondary': choice.update(primary=None, secondary=['energy'])
    elif problem == 'missing-evidence': result['evidence'] = []
    elif problem == 'bad-confidence': choice['primary'] = None
    else: result['product_type'] = 'Software'
    with pytest.raises(ValueError):
        validate_json_schema(result, response_schema(ref, config['response_schema']))


def test_reviewer_primary_secondary_and_multi_parent_rules(mock_env):
    ref = load_repository_config('startup_sector')['taxonomies']['dealroom']
    result = classification(ref)
    choices = result['classifications']
    choices['industries'] = dict(primary='health', secondary=['robotics'])
    choices['subindustries'] = dict(primary='medical-devices', secondary=[])
    assert review_classification(result, ref).accepted
    choices['industries']['primary'] = 'robotics'
    choices['industries']['secondary'] = ['health']
    assert review_classification(result, ref).accepted
    choices['industries']['primary'] = 'energy'
    assert not review_classification(result, ref).accepted  # Parent exists, but is not primary.
    choices['industries']['secondary'] = ['energy']
    problems = review_classification(result, ref).problems
    assert any('primary must not' in p for p in problems)
    assert any('needs a selected parent' in p for p in problems)


@pytest.mark.asyncio
async def test_shared_generation_corrects_reviewer_errors(mock_env, monkeypatch):
    generation = importlib.import_module('lib.infrastructure.ai_text_generation.generation')
    config = load_repository_config('startup_sector')
    ref = config['taxonomies']['dealroom']
    bad = classification(ref)
    bad['classifications']['industries'] = dict(primary='energy', secondary=[])
    bad['classifications']['subindustries'] = dict(primary='medical-devices', secondary=[])
    good = copy.deepcopy(bad)
    good['classifications']['industries']['primary'] = 'health'
    request = AsyncMock(side_effect=[json.dumps(bad), json.dumps({'reasoning': 'Correct parent.', **good})])
    monkeypatch.setattr(generation, '_request_text_waiting_out_rate_limits', request)
    result = await generation.generate_json('Classify', response_schema(ref, config['response_schema']),
                                           lambda x: review_classification(x, ref))
    assert result == good
    assert request.await_count == 2


def test_derived_parents_and_reporting_groups(mock_env):
    config = load_repository_config('startup_sector')
    ref = config['taxonomies']['pitchbook']
    result = classification(ref)
    result['classifications']['industries'] = dict(primary='1.1.1', secondary=['6.5.1'])
    derived = derive(result, ref)
    assert derived['parents']['industry_groups'] == ['1.1', '6.5']
    assert derived['parents']['broad_sectors'] == ['1', '6']
    ref = config['taxonomies']['dealroom']
    result = classification(ref)
    result['classifications']['industries'] = dict(primary='energy', secondary=[])
    result['classifications']['tags'] = dict(primary='defence', secondary=[])
    derived = derive(result, ref)
    assert {'energy', 'defence'} <= set(derived['reporting_groups'])
    assert 'ai' in derived['unevaluated_reporting_groups']
    result['classifications']['industries']['secondary'] = ['space']
    assert 'defence' not in derive(result, ref)['reporting_groups']
    result['classifications']['industries'] = dict(primary=None, secondary=[])
    assert 'defence' in derive(result, ref)['unevaluated_reporting_groups']


@pytest.mark.asyncio
async def test_new_manual_override_is_authoritative(workflow):
    [generated] = await module.startup_sector('example-co')
    payload = json.loads(generated.content())
    manual = InsightFile('example-co', 'startup_sector', 'manual', extension='json')
    payload['providers']['dealum']['result']['rationale'] = 'Manually checked.'
    manual.save(json.dumps(payload))
    original = manual.content()
    install_dataset(revision='revision-2')
    assert await module.startup_sector_as_dict('example-co') == payload
    assert manual.content() == original
    assert workflow.generate.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('computed_fields', ['stale', 'absent'])
async def test_manual_ids_drive_names_and_parents_without_rewriting(workflow, computed_fields):
    [generated] = await module.startup_sector('example-co')
    payload = json.loads(generated.content())
    payload['providers']['dealum']['result']['classifications']['industries']['primary'] = 'energy'
    payload['providers']['pitchbook']['result']['classifications']['industries']['primary'] = '1.1.1'
    if computed_fields == 'absent':
        for record in payload['providers'].values():
            del record['category_names']
            del record['derived']
    manual = InsightFile('example-co', 'startup_sector', 'manual', extension='json')
    manual.save(json.dumps(payload))
    original = manual.content()

    result = await module.startup_sector_as_dict('example-co')
    assert result['providers']['dealum']['category_names']['industries'] == {'energy': 'Energy'}
    assert result['providers']['pitchbook']['derived']['parents'] == {
        'industry_groups': ['1.1'], 'broad_sectors': ['1'],
    }
    assert result['providers']['dealum']['taxonomy'] == payload['providers']['dealum']['taxonomy']
    assert manual.content() == original
    assert workflow.generate.await_count == 4
    assert workflow.retrieve.await_count == 3


@pytest.mark.asyncio
async def test_manual_display_name_tracks_reference_without_rewriting(workflow, monkeypatch):
    [generated] = await module.startup_sector('example-co')
    payload = json.loads(generated.content())
    manual = InsightFile('example-co', 'startup_sector', 'manual', extension='json')
    manual.save(json.dumps(payload))
    original = manual.content()
    config = copy.deepcopy(workflow.config)
    category = config['taxonomies']['dealum']['components']['industries']['categories'][0]
    category['name'] = 'Updated display name'
    original_loader = module.load_repository_config
    monkeypatch.setattr(module, 'load_repository_config',
                        lambda name: config if name == 'startup_sector' else original_loader(name))
    result = await module.startup_sector_as_dict('example-co')
    assert result['providers']['dealum']['category_names']['industries'] == {
        category['id']: 'Updated display name',
    }
    assert manual.content() == original
    assert workflow.generate.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('problem', ['unknown-id', 'wrong-parent'])
async def test_manual_still_rejects_invalid_decisions(workflow, problem):
    [generated] = await module.startup_sector('example-co')
    payload = json.loads(generated.content())
    choices = payload['providers']['dealroom']['result']['classifications']
    choices['industries'] = dict(primary='energy', secondary=[])
    if problem == 'unknown-id':
        choices['industries']['primary'] = 'invented'
    else:
        choices['subindustries']['primary'] = 'medical-devices'
    manual = InsightFile('example-co', 'startup_sector', 'manual', extension='json')
    manual.save(json.dumps(payload))
    original = manual.content()
    with pytest.raises(ValueError):
        await module.startup_sector_as_dict('example-co')
    assert manual.content() == original
    assert workflow.generate.await_count == 4


@pytest.mark.asyncio
async def test_profile_uses_resolved_manual_ids_and_preserves_legacy_reuse(workflow, monkeypatch):
    profile = importlib.import_module('skills.startup_profile.startup_profile')
    install_dataset('temp-manual-profile', domain='generated')
    monkeypatch.setattr(profile, 'sync_datasets', workflow.sync)
    chat = AsyncMock(return_value='Profile body.')
    monkeypatch.setattr(profile, 'dataset_chat', chat)
    [generated] = await module.startup_sector('temp-manual-profile')
    payload = json.loads(generated.content())
    payload['providers']['dealum']['result']['classifications']['industries']['primary'] = 'energy'
    manual = InsightFile('temp-manual-profile', 'startup_sector', 'manual', extension='json')
    manual.save(json.dumps(payload))
    original = manual.content()
    [report] = await profile.startup_profile('temp-manual-profile')
    assert '  - **Primary-industry:** Energy.' in report.content()
    assert manual.content() == original
    assert workflow.generate.await_count == 4

    manual.save(json.dumps(legacy(product_type='Hardware', product_type_confidence='H')))
    [report] = await profile.startup_profile('temp-manual-profile')
    assert '  - **SICTIC sector:** EnergyTech' in report.content()
    calls = chat.await_count
    manual.save(json.dumps(legacy(product_type='Software', product_type_confidence='M')))
    original = manual.content()
    [reused] = await profile.startup_profile('temp-manual-profile')
    assert reused.content() == report.content()
    assert chat.await_count == calls
    assert manual.content() == original


@pytest.mark.asyncio
@pytest.mark.parametrize('retired', [False, True])
async def test_legacy_manual_preserved_without_fake_provider_translation(workflow, retired):
    manual = InsightFile('example-co', 'startup_sector', 'manual', extension='json')
    payload = legacy()
    if retired: payload.update(product_type='Hardware', product_type_confidence='M')
    manual.save(json.dumps(payload, indent=2))
    original = manual.content()
    [selected] = await module.startup_sector('example-co')
    assert selected.path == manual.path
    assert selected.content() == original
    assert await module.startup_sector_as_dict('example-co') == legacy()
    workflow.retrieve.assert_not_awaited()
    workflow.generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('content', ['{broken', json.dumps(legacy(sector='Unknown')),
                                    json.dumps(legacy(unrelated='invalid'))])
async def test_invalid_manual_raises_without_regeneration(workflow, content):
    manual = InsightFile('example-co', 'startup_sector', 'manual', extension='json')
    manual.save(content)
    with pytest.raises(ValueError): await module.startup_sector('example-co')
    assert manual.content() == content
    workflow.generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('corruption', ['identifier', 'relationship', 'display', 'derived'])
async def test_invalid_cached_json_raises_without_regeneration(workflow, corruption):
    [insight] = await module.startup_sector('example-co')
    payload = json.loads(insight.content())
    record = payload['providers']['dealroom']
    if corruption == 'identifier': record['result']['classifications']['industries']['primary'] = 'fake'
    elif corruption == 'relationship':
        record['result']['classifications']['industries'] = dict(primary='energy', secondary=['energy'])
    elif corruption == 'display': record['category_names'] = {}
    else: record['derived']['reporting_groups'] = ['invented']
    insight.save(json.dumps(payload))
    with pytest.raises(ValueError): await module.startup_sector('example-co')
    assert workflow.generate.await_count == 4


@pytest.mark.asyncio
async def test_dataset_revision_invalidates(workflow):
    await module.startup_sector('example-co')
    install_dataset(revision='revision-2')
    await module.startup_sector('example-co')
    assert workflow.generate.await_count == 8


@pytest.mark.asyncio
async def test_old_generated_artifact_rebuilds_at_same_path(workflow):
    old = InsightFile('example-co', 'startup_sector', module.llm_model(), extension='json',
                      config_key=config_cache_key({'old': 'SICTIC schema'}))
    old.save(json.dumps(legacy()))
    [new] = await module.startup_sector('example-co')
    assert new.path == old.path
    assert 'providers' in json.loads(new.content())
    assert workflow.generate.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('section', ['taxonomies', 'llm_instructions', 'queries', 'proposition_fields', 'response_schema', 'structured_output'])
async def test_configuration_changes_invalidate(workflow, monkeypatch, section):
    await module.startup_sector('example-co')
    original = module.load_repository_config
    config = copy.deepcopy(workflow.config)
    structured = copy.deepcopy(original('structured_output'))
    if section == 'taxonomies': config[section]['dealum']['components']['industries']['categories'][0]['description'] += ' Clarified.'
    elif section == 'queries': config[section][0] += ' Clarified.'
    elif section == 'proposition_fields': config[section].append('market_summary')
    elif section == 'llm_instructions': config[section] += ' Clarified.'
    elif section == 'response_schema': config[section]['properties']['rationale']['description'] = 'Explain choices.'
    else: structured['changed_setting'] = True
    monkeypatch.setattr(module, 'load_repository_config', lambda key: structured if key == 'structured_output' else config)
    await module.startup_sector('example-co')
    assert workflow.generate.await_count == 8


@pytest.mark.asyncio
async def test_generated_dataset_isolated_and_skips_external_import(workflow):
    location = install_dataset('temp-sector-review', domain='generated')
    workflow.prepare.side_effect = AssertionError('No Dealum import for generated datasets')
    [insight] = await module.startup_sector('temp-sector-review')
    assert insight.directory == location.insights_rel
    assert insight.dataset == 'temp-sector-review'
    workflow.prepare.assert_not_awaited()
    assert workflow.retrieve.await_args.args[0] == 'temp-sector-review'


@pytest.mark.asyncio
async def test_preparation_canonical_name_used(workflow):
    [insight] = await module.startup_sector('Historical Company Name')
    assert insight.dataset == 'example-co'
    assert workflow.retrieve.await_args.args[0] == 'example-co'


@pytest.mark.asyncio
async def test_community_dataset_rejected(workflow):
    with pytest.raises(ValueError, match='startup or generated'):
        await module.startup_sector('sictic-members')
    workflow.prepare.assert_not_awaited()
    workflow.sync.assert_not_awaited()
    workflow.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_retrieval_saves_unknowns_without_llm_calls(workflow):
    workflow.retrieve.return_value = []
    [insight] = await module.startup_sector('example-co')
    for record in json.loads(insight.content())['providers'].values():
        assert record['result']['confidence'] == 'L'
        assert record['result']['evidence'] == []
        assert all(v == dict(primary=None, secondary=[]) for v in record['result']['classifications'].values())
    await module.startup_sector('example-co')
    assert workflow.retrieve.await_count == 3
    workflow.generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['sync', 'retrieve', 'third-provider'])
async def test_technical_failure_preserves_previous_artifact(workflow, failure):
    [insight] = await module.startup_sector('example-co')
    original = insight.content()
    install_dataset(revision='revision-2')
    if failure == 'third-provider':
        responses = [classification(ref) for ref in workflow.config['taxonomies'].values()]
        workflow.generate.side_effect = responses[:2] + [RuntimeError('Provider unavailable')]
    else: getattr(workflow, failure).side_effect = RuntimeError('Provider unavailable')
    with pytest.raises(RuntimeError, match='Provider unavailable'):
        await module.startup_sector('example-co')
    assert insight.content() == original


def test_direct_cli_preserves_contract(workflow, monkeypatch):
    cli = importlib.import_module('skills.startup_sector.__main__')
    fake = SimpleNamespace(content=lambda: '{"providers": {}}', path='classification.json')
    run = AsyncMock(return_value=[fake])
    monkeypatch.setattr(cli, 'startup_sector', run)
    result = CliRunner().invoke(cli.app, ['--startup', 'Example Co'])
    assert result.exit_code == 0, result.output
    assert '"providers"' in result.output
    assert 'RESULT_PATH: classification.json' in result.output
    run.assert_awaited_once_with('Example Co')


@pytest.mark.asyncio
async def test_harness_calls_public_skill(workflow, monkeypatch):
    from skills.harness.harness import dispatch_command
    package = importlib.import_module('skills.startup_sector')
    run = AsyncMock(return_value=[])
    monkeypatch.setattr(package, 'startup_sector', run)
    assert await dispatch_command('/startup_sector "Example Co"') == ''
    run.assert_awaited_once_with('Example Co')


def test_registry_contract_unchanged():
    from skills.skill_registry import SKILL_REGISTRY, expand_skill_dependencies
    spec = SKILL_REGISTRY['startup-sector']
    assert spec.domains == frozenset({'startups', 'generated'})
    assert not spec.mandatory_stages
    assert expand_skill_dependencies(['startup-sector']) == ['startup-sector']
    assert 'startup-sector' in expand_skill_dependencies(['startup-profile'])
    assert 'startup-sector' not in SKILL_REGISTRY['dd-checks'].depends_on
