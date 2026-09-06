import argparse
import asyncio
import shlex
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List

from lib.cli import format_insights
from lib.insights import InsightFile
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)


Handler = Callable[[List[str]], Awaitable[str]]


@dataclass(frozen=True)
class HarnessCommand:
    name: str
    usage: str
    description: str
    handler: Handler


def _format_result(result) -> str:
    if result is None:
        return ""
    if isinstance(result, tuple):
        parts = [str(item) for item in result if item is not None]
        return "\n\n".join(parts)
    if isinstance(result, dict):
        lines = []
        for key, value in result.items():
            lines.append(f"## {key}\n\n{value}")
        return "\n\n".join(lines)
    if isinstance(result, list):
        if all(isinstance(item, InsightFile) for item in result):
            return format_insights(result)
        rendered = []
        for item in result:
            if hasattr(item, "person_profile_markdown"):
                rendered.append(item.person_profile_markdown)
            else:
                rendered.append(str(item))
        return "\n\n".join(rendered)
    return str(result)


def _parser(prog: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=prog, add_help=False)


def _parse_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


async def _config(_: List[str]) -> str:
    from lib.infrastructure.configuration import (
        _local_cache_paths,
        load_repository_config,
    )

    config = load_repository_config()
    _, cache_file = _local_cache_paths()
    return f"Loaded {len(config)} config sections.\nRESULT_PATH: {cache_file}"


async def _sync(args: List[str]) -> str:
    parser = _parser("/sync")
    parser.add_argument("dataset")
    ns = parser.parse_args(args)
    from lib.datasets.ingestion import sync_datasets

    await sync_datasets([ns.dataset], raise_on_error=True)
    return f"Synced dataset: {ns.dataset}"


async def _dataset_chat(args: List[str]) -> str:
    parser = _parser("/dataset_chat")
    parser.add_argument("dataset")
    parser.add_argument("question", nargs=argparse.REMAINDER)
    ns = parser.parse_args(args)
    if not ns.question:
        raise ValueError("Missing question.")
    from skills.dataset_chat.dataset_chat import dataset_chat

    question = " ".join(ns.question)
    return _format_result(
        await dataset_chat(ns.dataset, question, f"Query: {question}")
    )


async def _startup_profile(args: List[str]) -> str:
    parser = _parser("/startup_profile")
    parser.add_argument("startup")
    ns = parser.parse_args(args)
    from skills.startup_profile.startup_profile import startup_profile

    return _format_result(await startup_profile(ns.startup))


async def _startup_traction(args: List[str]) -> str:
    parser = _parser("/startup_traction")
    parser.add_argument("startup")
    ns = parser.parse_args(args)
    from skills.startup_traction.startup_traction import startup_traction

    return _format_result(await startup_traction(ns.startup))


async def _persons_in_dataset(args: List[str]) -> str:
    parser = _parser("/persons_in_dataset")
    parser.add_argument("dataset")
    ns = parser.parse_args(args)
    from skills.persons_in_dataset.persons_in_dataset import persons_in_dataset
    return _format_result(await persons_in_dataset(ns.dataset))


async def _person_profile(args: List[str]) -> str:
    parser = _parser("/person_profile")
    parser.add_argument("dataset")
    parser.add_argument("person", nargs=argparse.REMAINDER)
    ns = parser.parse_args(args)
    if not ns.person:
        raise ValueError("Missing person.")
    from skills.person_profile.person_profile import person_profile

    return _format_result(await person_profile(ns.dataset, " ".join(ns.person)))


async def _team_profile(args: List[str]) -> str:
    parser = _parser("/team_profile")
    parser.add_argument("startup")
    ns = parser.parse_args(args)
    from skills.team_profile.team_profile import team_profile

    return _format_result(await team_profile(ns.startup))


async def _team_profile_revised(args: List[str]) -> str:
    parser = _parser("/team_profile_revised")
    parser.add_argument("startup")
    ns = parser.parse_args(args)
    from skills.team_profile_revised.team_profile_revised import team_profile_revised

    return _format_result(await team_profile_revised(ns.startup))


async def _investor_profile(args: List[str]) -> str:
    parser = _parser("/investor_profile")
    parser.add_argument("--source-dataset", default="sictic-members")
    ns = parser.parse_args(args)
    from skills.investor_profile.investor_profile import investor_profile

    return _format_result(await investor_profile(source_dataset=ns.source_dataset))


async def _expert_search(args: List[str]) -> str:
    parser = _parser("/expert_search")
    parser.add_argument("startup")
    ns = parser.parse_args(args)
    from skills.expert_search.expert_search import expert_search

    return _format_result(await expert_search(ns.startup))


async def _potential_investors(args: List[str]) -> str:
    parser = _parser("/potential_investors")
    parser.add_argument("startup")
    ns = parser.parse_args(args)
    from skills.potential_investors.potential_investors import potential_investors

    return _format_result(await potential_investors(ns.startup))


async def _member_preferences(args: List[str]) -> str:
    parser = _parser("/member_preferences")
    parser.add_argument("--dataset", "-d", default="sictic-members")
    ns = parser.parse_args(args)
    from skills.member_preferences.member_preferences import (
        member_preferences,
        render_member_preferences,
    )

    return render_member_preferences(member_preferences(ns.dataset))


async def _deep_dive_invitation(args: List[str]) -> str:
    parser = _parser("/deep_dive_invitation")
    parser.add_argument("--startup", "-s", nargs="+", required=True)
    parser.add_argument("--founders", nargs="*", default=[])
    parser.add_argument("--investors", nargs="*", default=[])
    ns = parser.parse_args(args)
    from skills.deep_dive_invitation.deep_dive_invitation import (
        deep_dive_invitation,
        parse_people_csv,
    )

    return _format_result(await deep_dive_invitation(
        " ".join(ns.startup),
        founders=parse_people_csv(" ".join(ns.founders)),
        investors=parse_people_csv(" ".join(ns.investors)),
    ))


async def _advocates(args: List[str]) -> str:
    parser = _parser("/advocates")
    parser.add_argument("event")
    parser.add_argument("--description", "-d", required=True)
    ns = parser.parse_args(args)
    from skills.advocates.advocates import advocates

    return _format_result(await advocates(ns.event, ns.description))


async def _suggested_startups(args: List[str]) -> str:
    parser = _parser("/suggested_startups")
    parser.add_argument("--startups", "-s")
    parser.add_argument("--investor", "-i")
    parser.add_argument("--max-startups", "-m", type=int, default=5)
    ns = parser.parse_args(args)
    from skills.suggested_startups.suggested_startups import suggested_startups

    return _format_result(await suggested_startups(
        startups=_parse_csv(ns.startups),
        investors=_parse_csv(ns.investor),
        max_startups=ns.max_startups,
    ))


async def _dd_checks(args: List[str]) -> str:
    parser = _parser("/dd_checks")
    parser.add_argument("startup")
    ns = parser.parse_args(args)
    from skills.dd_checks.dd_checks import dd_checks

    return _format_result(await dd_checks(ns.startup))


async def _dd_priorities(args: List[str]) -> str:
    parser = _parser("/dd_priorities")
    parser.add_argument("startup")
    ns = parser.parse_args(args)
    from skills.dd_priorities.dd_priorities import dd_priorities

    return _format_result(await dd_priorities(ns.startup))


async def _sha_review(args: List[str]) -> str:
    parser = _parser("/sha_review")
    parser.add_argument("dataset")
    ns = parser.parse_args(args)
    from skills.sha_review.sha_review import sha_review

    return _format_result(await sha_review(ns.dataset))


async def _submission_ready(args: List[str]) -> str:
    parser = _parser("/submission_ready")
    parser.add_argument("startups", nargs="*")
    ns = parser.parse_args(args)
    from skills.submission_ready.submission_ready import submission_ready

    result = await submission_ready(ns.startups or None)
    return _format_result(result)


async def _dealum_import(args: List[str]) -> str:
    parser = _parser("/dealum_import")
    parser.add_argument("startup")
    ns = parser.parse_args(args)
    from skills.dealum_import.dealum_import import dealum_import

    result = await dealum_import(ns.startup)
    if not result.application_found:
        return f"No Dealum application found for {ns.startup}."
    return (
        f"Imported {result.dataset_slug}: changed={result.changed}, "
        f"downloaded={result.downloaded_files}, skipped={result.skipped_files}, "
        f"step={result.step}\n"
        f"APPLICATION_PATH: {result.application_path}\n"
        f"MANIFEST_PATH: {result.manifest_path}"
    )


def build_registry() -> Dict[str, HarnessCommand]:
    commands = [
        HarnessCommand("/config", "/config", "Load config cache.", _config),
        HarnessCommand("/sync", "/sync <dataset>", "Sync one dataset into the RAG index.", _sync),
        HarnessCommand("/dataset_chat", "/dataset_chat <dataset> <question>", "Ask a dataset question.", _dataset_chat),
        HarnessCommand("/startup_profile", "/startup_profile <startup>", "Generate a startup profile.", _startup_profile),
        HarnessCommand("/startup_traction", "/startup_traction <startup>", "Summarize commercial traction.", _startup_traction),
        HarnessCommand("/persons_in_dataset", "/persons_in_dataset <dataset>", "Discover the editable person roster.", _persons_in_dataset),
        HarnessCommand("/person_profile", "/person_profile <dataset> <person>", "Generate a person profile.", _person_profile),
        HarnessCommand("/team_profile", "/team_profile <startup>", "Generate a team profile.", _team_profile),
        HarnessCommand("/team_profile_revised", "/team_profile_revised <startup>", "Assess team checklists and synthesize each category.", _team_profile_revised),
        HarnessCommand("/investor_profile", "/investor_profile [--source-dataset dataset]", "Build investor profiles.", _investor_profile),
        HarnessCommand("/expert_search", "/expert_search <startup>", "Rank relevant experts.", _expert_search),
        HarnessCommand("/potential_investors", "/potential_investors <startup>", "Rank potential investors.", _potential_investors),
        HarnessCommand(
            "/member_preferences",
            "/member_preferences [--dataset sictic-members]",
            "Return member communication preferences.",
            _member_preferences,
        ),
        HarnessCommand(
            "/deep_dive_invitation",
            "/deep_dive_invitation --startup name [--founders contacts] [--investors contacts]",
            "Create a review-only deep-dive invitation draft.",
            _deep_dive_invitation,
        ),
        HarnessCommand("/advocates", '/advocates <event> --description "..."', "Rank event advocates.", _advocates),
        HarnessCommand("/suggested_startups", "/suggested_startups --startups a,b --investor x,y", "Suggest startups for investors.", _suggested_startups),
        HarnessCommand(
            "/submission_ready",
            "/submission_ready [startup ...]",
            "Check in-scope application completeness and eligibility.",
            _submission_ready,
        ),
        HarnessCommand("/dd_checks", "/dd_checks <startup>", "Run due-diligence checks.", _dd_checks),
        HarnessCommand("/dd_priorities", "/dd_priorities <startup>", "Prioritize an existing DD checks report.", _dd_priorities),
        HarnessCommand("/sha_review", "/sha_review <dataset>", "Review a startup Shareholders' Agreement.", _sha_review),
        HarnessCommand("/dealum_import", "/dealum_import <startup>", "Import startup data from Dealum.", _dealum_import),
    ]
    return {cmd.name: cmd for cmd in commands}


def help_text(registry: Dict[str, HarnessCommand] | None = None) -> str:
    registry = registry or build_registry()
    lines = ["Available commands:", ""]
    lines.append("/help")
    lines.append("/exit")
    for command in registry.values():
        lines.append(f"{command.usage} - {command.description}")
    return "\n".join(lines)


async def dispatch_command(line: str, registry: Dict[str, HarnessCommand] | None = None) -> str:
    registry = registry or build_registry()
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped in {"/help", "help"}:
        return help_text(registry)
    if stripped in {"/exit", "exit", "quit"}:
        return "__EXIT__"
    if not stripped.startswith("/"):
        return "Use slash commands. Type /help for available commands."

    try:
        # Only double quotes group tokens; apostrophes in natural-language
        # queries (e.g. "What's ...") must not open a quote.
        lexer = shlex.shlex(stripped, posix=True)
        lexer.quotes = '"'
        lexer.whitespace_split = True
        lexer.commenters = ""
        parts = list(lexer)
    except ValueError as e:
        return f"Parse error: {e}"

    if not parts:
        return ""
    command_name, args = parts[0], parts[1:]
    command = registry.get(command_name)
    if not command:
        return f"Unknown command: {command_name}\nType /help for available commands."

    try:
        return await command.handler(args)
    except SystemExit as e:
        return f"Invalid arguments for {command_name}. Exit code: {e.code}\nUsage: {command.usage}"
    except Exception as e:
        logger.error(f"Harness command failed ({command_name}): {e}")
        return f"Error: {e}"


async def run_repl() -> None:
    try:
        registry = build_registry()
        print("SICTIC-AI harness. Type /help for commands, /exit to quit.")
        while True:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                print()
                return
            output = await dispatch_command(line, registry)
            if output == "__EXIT__":
                return
            if output:
                print(output)
    finally:
        from lib.litellm_cleanup import close_litellm_sessions

        await close_litellm_sessions()


def run() -> None:
    asyncio.run(run_repl())
