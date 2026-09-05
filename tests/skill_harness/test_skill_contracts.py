from __future__ import annotations

import importlib
from pathlib import Path
from typing import get_type_hints

from typer.testing import CliRunner

from skills.harness.harness import build_registry
from skills.skill_registry import SKILL_REGISTRY
from lib.insights import InsightFile
from tests.skill_harness.cases import (
    ADMIN_ONLY_HARNESS_COMMANDS,
    HARNESS_SMOKE_COMMANDS,
    SKILL_COVERAGE,
    SKILL_COVERAGE_REASONS,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


def _skill_dirs() -> list[Path]:
    return sorted(path.parent for path in SKILLS_ROOT.glob("*/SKILL.md"))


def test_every_skill_markdown_directory_is_importable_package():
    for skill_dir in _skill_dirs():
        package_name = f"skills.{skill_dir.name}"
        importlib.import_module(package_name)


def test_every_skill_main_renders_typer_help():
    for main_path in sorted(SKILLS_ROOT.glob("*/__main__.py")):
        module_name = f"skills.{main_path.parent.name}.__main__"
        module = importlib.import_module(module_name)

        result = CliRunner().invoke(module.app, ["--help"])

        assert result.exit_code == 0, module_name
        assert "Usage:" in result.output


def test_harness_registry_commands_are_smoked_or_marked_admin_only():
    registered = set(build_registry())
    covered = set(HARNESS_SMOKE_COMMANDS) | ADMIN_ONLY_HARNESS_COMMANDS

    assert registered <= covered


def test_skill_registry_dependencies_reference_existing_keys():
    registered = set(SKILL_REGISTRY)

    for name, spec in SKILL_REGISTRY.items():
        assert set(spec.depends_on) <= registered, name


def test_every_skill_has_explicit_harness_coverage_classification():
    skill_names = {path.name for path in _skill_dirs()}

    assert set(SKILL_COVERAGE) == skill_names
    assert set(SKILL_COVERAGE.values()) <= set(SKILL_COVERAGE_REASONS)


def test_insight_skill_apis_declare_uniform_result_contract():
    entrypoints = {
        "advocates": "skills.advocates.advocates",
        "dd_checks": "skills.dd_checks.dd_checks",
        "dd_priorities": "skills.dd_priorities.dd_priorities",
        "deep_dive_invitation": "skills.deep_dive_invitation.deep_dive_invitation",
        "expert_search": "skills.expert_search.expert_search",
        "investor_profile": "skills.investor_profile.investor_profile",
        "person_profile": "skills.person_profile.person_profile",
        "persons_in_dataset": "skills.persons_in_dataset.persons_in_dataset",
        "potential_investors": "skills.potential_investors.potential_investors",
        "sha_review": "skills.sha_review.sha_review",
        "startup_profile": "skills.startup_profile.startup_profile",
        "startup_traction": "skills.startup_traction.startup_traction",
        "submission_ready": "skills.submission_ready.submission_ready",
        "suggested_startups": "skills.suggested_startups.suggested_startups",
        "team_profile": "skills.team_profile.team_profile",
        "team_profile_revised": "skills.team_profile_revised.team_profile_revised",
    }

    for function_name, module_name in entrypoints.items():
        function = getattr(importlib.import_module(module_name), function_name)
        assert get_type_hints(function)["return"] == list[InsightFile], function_name
