"""Configurable report thresholds, defaults and dependency reuse."""
from copy import deepcopy
from datetime import date
from importlib import import_module
from unittest.mock import AsyncMock

import pytest

from lib.captable.rubric import apply_rubric
from lib.infrastructure.configuration import load_repository_config
from skills.captable.captable import build_scenarios
from tests.skills.test_captable_analysis import _snapshot
from tests.skills.test_captable_build import _install_dataset, _patched_build


def settings():
    return deepcopy(load_repository_config("captable")["settings"])


def test_configured_rubric_thresholds_and_explanations():
    config = settings()
    config.update(founder_majority_min_pct=60, investor_dominance_ratio=0.4, departed_ownership_max_pct=20)
    findings = {f["item"]: f for f in apply_rubric(_snapshot(), settings=config)}
    assert findings["founder_majority"]["status"] == "flag"
    assert "<60%" in findings["founder_majority"]["detail"]
    assert "0.4 times" in findings["investor_dominance"]["detail"]
    assert findings["dead_equity"]["status"] == "ok"
    config["departed_ownership_max_pct"] = 12
    findings = {f["item"]: f for f in apply_rubric(_snapshot(), settings=config)}
    assert ">12%" in findings["dead_equity"]["detail"]


def test_fallback_multiplier_minimum_and_round_percentage():
    data = _snapshot()
    data["convertibles"] = []
    config = settings()
    config.update(fallback_pre_money_invested_multiplier=3, fallback_pre_money_minimum=100, fallback_investment_pct=25)
    computed = build_scenarios(data, settings=config)
    assert computed["hypothetical_round"]["pre_money"] == 1_350_000
    assert computed["hypothetical_round"]["investment"] == 337_500
    config["fallback_pre_money_minimum"] = 2_000_000
    computed = build_scenarios(data, settings=config)
    assert computed["hypothetical_round"]["pre_money"] == 2_000_000
    assert computed["hypothetical_round"]["investment"] == 500_000
    assert any("minimum of 2,000,000" in a for a in computed["assumptions"])


def test_explicit_inputs_and_extracted_terms_keep_precedence():
    config = settings()
    config.update(fallback_pre_money_minimum=99_000_000, fallback_investment_pct=99)
    extracted = build_scenarios(_snapshot(), settings=config)
    assert extracted["hypothetical_round"]["pre_money"] == 4_000_000
    assert extracted["hypothetical_round"]["investment"] == 2_000_000
    explicit = build_scenarios(_snapshot(), settings=config, pre_money=8_000_000, investment=1_000_000)
    assert explicit["hypothetical_round"]["pre_money"] == 8_000_000
    assert explicit["hypothetical_round"]["investment"] == 1_000_000


def test_post_round_uses_configured_founder_threshold():
    config = settings()
    config["founder_majority_min_pct"] = 99
    computed = build_scenarios(_snapshot(), settings=config, valuation_date=date(2026, 1, 1))
    finding = next(f for f in computed["scenario_flags"] if f["item"] == "founder_majority_post_round")
    assert "below 99%" in finding["detail"]
    config["founder_majority_min_pct"] = 0
    computed = build_scenarios(_snapshot(), settings=config, valuation_date=date(2026, 1, 1))
    assert not any(f["item"] == "founder_majority_post_round" for f in computed["scenario_flags"])


def test_missing_required_settings_do_not_use_hidden_defaults():
    with pytest.raises(KeyError, match="founder_majority_min_pct"):
        apply_rubric(_snapshot(), settings={})
    with pytest.raises(KeyError, match="founder_majority_min_pct"):
        build_scenarios(_snapshot(), settings={})


@pytest.mark.asyncio
async def test_settings_change_regenerates_only_report(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    build, calls = _patched_build(monkeypatch)
    report = import_module("skills.captable.captable")
    config = deepcopy(load_repository_config("captable"))
    monkeypatch.setattr(report, "load_repository_config", lambda *_: config)
    generate = AsyncMock(return_value="Commentary")
    monkeypatch.setattr(report, "generate_markdown", generate)
    _install_dataset("settings-co", "Founder 900,000")
    [consolidated] = await build.captable_build("settings-co")
    original = consolidated.content()
    await report.captable("settings-co")
    await report.captable("settings-co")
    assert generate.await_count == 1
    config["settings"]["founder_majority_min_pct"] = 95
    [reused] = await build.captable_build("settings-co")
    [changed] = await report.captable("settings-co")
    assert "&lt;95%" in changed.content()
    assert generate.await_count == 2
    assert calls == {"classify": 1, "captable": 1}
    assert reused.content() == original
