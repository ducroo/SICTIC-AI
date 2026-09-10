"""Check maintained documentation against real paths and command parsers."""

from __future__ import annotations

import argparse
import asyncio
import importlib
from pathlib import Path
import re
import shlex
from urllib.parse import unquote, urlsplit

import click
import pytest
from typer.main import get_command
import yaml

from skills.harness.harness import build_registry, dispatch_command


ROOT = Path(__file__).resolve().parents[2]
SKILL_DOCS = sorted((ROOT / "skills").glob("*/SKILL.md"))
MAINTAINED_DOCS = SKILL_DOCS + [
    ROOT / "AGENTS.md",
    ROOT / "README.md",
    ROOT / "docs/installation-and-operations.md",
    ROOT / "docs/reviews/documentation-closeout-2026-09-06.md",
    ROOT / "skills/standards_and_architecture/references/architecture.md",
]


def _without_fences(text):
    return re.sub(r"```.*?```", "", text, flags=re.S)


def _heading_anchors(text):
    anchors = set()
    counts = {}
    for heading in re.findall(r"^#{1,6}\s+(.+)$", _without_fences(text), re.M):
        base = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(base, 0)
        anchors.add(f"{base}-{count}" if count else base)
        counts[base] = count + 1
    return anchors


@pytest.mark.parametrize("document", SKILL_DOCS, ids=lambda p: p.parent.name)
def test_skill_discovery_metadata_matches_package(document):
    parts = document.read_text().split("---", 2)
    assert len(parts) == 3 and not parts[0].strip(), document
    metadata = yaml.safe_load(parts[1])
    assert metadata["name"] == document.parent.name
    assert isinstance(metadata["description"], str) and metadata["description"].strip()


@pytest.mark.parametrize("document", MAINTAINED_DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_maintained_document_links_resolve(document):
    text = _without_fences(document.read_text())
    for target in re.findall(r"\]\(([^)]+)\)", text):
        target = target.strip().removeprefix("<").removesuffix(">")
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            continue
        assert not parsed.path.startswith("/"), (document, target)
        path = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
        assert path.exists(), (document, target)
        if parsed.fragment and path.suffix == ".md":
            assert unquote(parsed.fragment) in _heading_anchors(path.read_text()), (document, target)


def _skill_examples():
    for document in MAINTAINED_DOCS:
        for block in re.findall(r"```(?:bash|sh|shell)\n(.*?)```", document.read_text(), re.S):
            for line in block.replace("\\\n", " ").splitlines():
                if " -m skills." not in line:
                    continue
                tokens = shlex.split(line, comments=True)
                module_index = tokens.index("-m") + 1
                if tokens[module_index].startswith("skills."):
                    yield document, tokens[module_index], tokens[module_index + 1:]


class _ParsedHarnessArguments(BaseException):
    """Stop before the dispatcher can reach any business action."""


@pytest.mark.parametrize(
    "document,module_name,arguments", list(_skill_examples()),
    ids=lambda value: str(value.relative_to(ROOT)) if isinstance(value, Path) else str(value),
)
def test_documented_skill_commands_parse_without_running_workflows(
    mock_env, monkeypatch, document, module_name, arguments,
):
    module = importlib.import_module(f"{module_name}.__main__")
    command = get_command(module.app)
    args = list(arguments)
    if isinstance(command, click.Group):
        assert args and args[0] in command.commands, (document, arguments)
        command = command.commands[args.pop(0)]
    with command.make_context(command.name or module_name, args) as context:
        parsed = context.params

    if module_name != "skills.harness" or not parsed.get("command"):
        return
    # Click returns a tuple here; Typer converts the callback's List[str].
    tokens = list(parsed["command"])
    line = tokens[0] if len(tokens) == 1 else tokens
    name = shlex.split(line)[0] if isinstance(line, str) else line[0]
    if name in {"/help", "/exit"}:
        return
    assert name in build_registry(), (document, name)
    original_parse = argparse.ArgumentParser.parse_args

    def parse_and_stop(parser, *args, **kwargs):
        original_parse(parser, *args, **kwargs)
        raise _ParsedHarnessArguments()

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", parse_and_stop)
    with pytest.raises(_ParsedHarnessArguments):
        asyncio.run(dispatch_command(line))
