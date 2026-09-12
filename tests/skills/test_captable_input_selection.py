"""Report input selection must agree with build freshness across models."""
import asyncio
from importlib import import_module
from unittest.mock import AsyncMock

import pytest

from lib.captable.insights import select_consolidated, read_build_insight
from tests.skills.test_captable_build import _install_dataset, _patched_build, _captable_extraction, _consolidated_artifact


def test_report_selects_fresh_lower_ranked_build(mock_env, monkeypatch):
    helpers = import_module('lib.captable.insights')
    extraction = import_module('lib.captable.table_extraction')
    build, _ = _patched_build(monkeypatch)
    monkeypatch.setenv('RANKED_LLMS', 'ollama/high,ollama/low')
    monkeypatch.setattr(helpers, 'llm_model', lambda: 'ollama/high')
    _install_dataset('review-co', 'old indexed source')
    [old] = asyncio.run(build.captable_build('review-co'))
    _install_dataset('review-co', 'new indexed source')
    monkeypatch.setattr(helpers, 'llm_model', lambda: 'ollama/low')
    async def corrected(*args):
        result = _captable_extraction('captable.md')
        result['dataset'] = 'review-co'
        result['stakeholders'][0]['name'] = 'Corrected Founder'
        return result
    monkeypatch.setattr(extraction, 'extract_captable', corrected)
    [fresh] = asyncio.run(build.captable_build('review-co'))
    monkeypatch.setattr(build, 'classify_documents', AsyncMock(side_effect=AssertionError('read only')))
    selected = select_consolidated('review-co')
    assert selected.path == fresh.path
    assert selected.path != old.path
    assert read_build_insight(selected)['stakeholders'][0]['name'] == 'Corrected Founder'


@pytest.mark.parametrize('change', ['revision', 'prompt', 'manual-input'])
def test_stale_input_requires_build_without_generation(mock_env, monkeypatch, change):
    from lib.insights import InsightFile
    from lib.captable.insights import build_insight
    helpers = import_module('lib.captable.insights')
    build, calls = _patched_build(monkeypatch)
    monkeypatch.setenv('RANKED_LLMS', 'ollama/test_model:1b')
    _install_dataset('stale-input', 'old indexed source')
    asyncio.run(build.captable_build('stale-input'))
    if change == 'revision':
        _install_dataset('stale-input', 'new indexed source')
    elif change == 'prompt':
        real_config = helpers.load_repository_config
        def edited(*args):
            config = dict(real_config(*args))
            config['cla_extraction_prompt'] += ' Changed'
            return config
        monkeypatch.setattr(helpers, 'load_repository_config', edited)
    else:
        import json
        data = read_build_insight(build_insight('stale-input', 'table-extraction'))
        data['captable']['stakeholders'][0]['name'] = 'Manual correction'
        InsightFile('stale-input', 'captable_build', 'manual', identifier='table-extraction', subdir=True, extension='json').save(json.dumps(data))
    with pytest.raises(ValueError, match='run captable_build first'):
        select_consolidated('stale-input')
    assert calls == {'classify': 1, 'captable': 1}


def test_manual_consolidated_wins_without_dependencies(mock_env, monkeypatch):
    from lib.insights import InsightFile
    _install_dataset('manual-input', 'source')
    manual = InsightFile('manual-input', 'captable_build', 'manual', identifier='consolidated', subdir=True, extension='json')
    import json
    manual.save(json.dumps(_consolidated_artifact('manual-input')))
    helpers = import_module('lib.captable.insights')
    monkeypatch.setattr(helpers, 'configured_build_insight', lambda *args: pytest.fail('manual must win first'))
    assert select_consolidated('manual-input').path == manual.path
