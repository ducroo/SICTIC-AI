from importlib import import_module
from inspect import signature

import pytest
from typer.testing import CliRunner

ROUTES = [
    ("expert_search", "expert_search", ["--startup", "example"], "top_k", "--top-k",
     "/expert_search example"),
    ("potential_investors", "potential_investors", ["--startup", "example"], "top_k", "--top-k",
     "/potential_investors example"),
    ("advocates", "advocates", ["--event", "event", "--description", "Panel"], "top_k", "--top-k",
     '/advocates event --description "Panel on new technology"'),
    ("suggested_startups", "suggested_startups", [], "max_startups", "--max-startups",
     "/suggested_startups"),
    ("ranking", "ranking_persons", ["--objective", "Find experts"], "top_k", "--top-k", None),
]


@pytest.mark.parametrize("skill,api,args,limit,option,command", ROUTES)
@pytest.mark.parametrize("explicit_limit", [None, 3])
def test_direct_cli_default_and_explicit_limit(
    mock_env, monkeypatch, skill, api, args, limit, option, command, explicit_limit,
):
    cli = import_module(f"skills.{skill}.__main__")
    api_signature = signature(getattr(cli, api))
    received = []

    async def fake_api(*args, **kwargs):
        bound = api_signature.bind(*args, **kwargs)
        bound.apply_defaults()
        received.append(bound.arguments[limit])
        return "" if skill == "ranking" else []

    monkeypatch.setattr(cli, api, fake_api)
    arguments = args + ([option, str(explicit_limit)] if explicit_limit is not None else [])
    result = CliRunner().invoke(cli.app, arguments)

    assert result.exit_code == 0, result.output
    assert received == [16 if explicit_limit is None else explicit_limit]


@pytest.mark.parametrize("skill,api,args,limit,option,command", ROUTES[:4])
def test_harness_uses_same_default_as_public_api(
    mock_env, monkeypatch, skill, api, args, limit, option, command,
):
    module = import_module(f"skills.{skill}.{api}")
    api_signature = signature(getattr(module, api))
    received = []

    async def fake_api(*args, **kwargs):
        bound = api_signature.bind(*args, **kwargs)
        bound.apply_defaults()
        received.append(bound.arguments[limit])
        return []

    monkeypatch.setattr(module, api, fake_api)
    cli = import_module("skills.harness.__main__")
    result = CliRunner().invoke(cli.app, [command])
    assert result.exit_code == 0, result.output
    assert received == [16]
