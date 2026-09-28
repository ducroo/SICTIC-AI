"""Dependency-aware bulk insight refresh orchestration."""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import dataset_location, find_dataset_location, list_all_dataset_names
from lib.datasets.state import is_active_dataset
from lib.infrastructure.logging import get_logger
from lib.slugify import slugify
from skills.skill_registry import SKILL_REGISTRY, expand_skill_dependencies
from skills.bulk_refresh.datasets import update_dataset_states
from lib.startups.dealum.session import dealum_session
from lib.startups.identity import canonical_startup_slug

logger = get_logger(__name__)

SOURCE_DOMAINS = ("startups", "community")
ALL_DATASETS = "all"

Node = tuple[str, str]
Outcome = Literal["succeeded", "failed", "skipped"]


class BulkRefreshError(RuntimeError):
    """Raised after a bulk refresh completes with failed or skipped work."""


@dataclass(frozen=True)
class _DatasetScope:
    names: tuple[str, ...]
    domains: dict[str, str]
    stages: dict[str, str | None] = field(default_factory=dict)


def _parse_selector(value: str | None, *, label: str) -> list[str]:
    if value is None:
        return []
    values = [slugify(item) for item in value.split(",") if slugify(item)]
    if not values:
        raise ValueError(f"{label} must contain at least one value.")
    return list(dict.fromkeys(values))


def _select_datasets(
    datasets: str | None, exclude: str | None = None, *, candidates: bool = False,
) -> _DatasetScope:
    requested = _parse_selector(datasets, label="datasets")
    excluded = set(_parse_selector(exclude, label="exclude"))
    if excluded:
        available = list_all_dataset_names(domains=SOURCE_DOMAINS)
        unknown = excluded.difference(available)
        if unknown:
            raise ValueError(f"Unknown excluded source datasets: {', '.join(sorted(unknown))}")
    if ALL_DATASETS in requested and requested != [ALL_DATASETS]:
        raise ValueError("'all' cannot be combined with named datasets.")

    if not requested and excluded:
        names = available
    elif requested == [ALL_DATASETS] or (not requested and candidates):
        names = list_all_dataset_names(domains=SOURCE_DOMAINS)
    elif requested:
        names = list(dict.fromkeys(
            canonical_startup_slug(name)
            if candidates and find_dataset_location(name) is None else name
            for name in requested
        ))
    else:
        names = [
            name
            for name in list_all_dataset_names(domains=SOURCE_DOMAINS)
            if is_active_dataset(name)
        ]

    domains: dict[str, str] = {}
    for name in names:
        if candidates and requested and find_dataset_location(name) is None:
            # Resolve the named startup's stage before deciding whether to create it.
            domains[name] = "startups"
            continue
        location = dataset_location(name)
        if location.domain not in SOURCE_DOMAINS:
            raise ValueError(
                f"Dataset '{name}' belongs to unsupported bulk-refresh "
                f"domain '{location.domain}'."
            )
        domains[name] = location.domain
    return _DatasetScope(
        tuple(name for name in names if name not in excluded),
        {name: domain for name, domain in domains.items() if name not in excluded},
    )


def _resolve_targets(
    datasets: str | None, exclude: str | None,
) -> tuple[_DatasetScope, dict[str, str]]:
    candidates = _select_datasets(datasets, exclude, candidates=True)
    requested = _parse_selector(datasets, label="datasets")
    excluded = set(_parse_selector(exclude, label="exclude"))
    # Preserve the established exclude-only selector: all source datasets minus exclusions.
    discover = not requested or requested == [ALL_DATASETS]
    if not candidates.names and excluded:
        return candidates, {}
    names, stages, errors = update_dataset_states(
        candidates.names, discover=discover, excluded=excluded,
    )
    domains = {}
    for name in names:
        location = find_dataset_location(name)
        if location is None:
            continue
        if not requested and not excluded and name not in errors and not is_active_dataset(name):
            continue
        domains[name] = location.domain
    return _DatasetScope(tuple(domains), domains, stages), errors


def _select_skills(skills: str | None) -> tuple[str, ...]:
    requested = _parse_selector(skills, label="skills")
    if not requested:
        return ()
    if ALL_DATASETS in requested:
        if requested != [ALL_DATASETS]:
            raise ValueError("'all' cannot be combined with named skills.")
        return tuple(SKILL_REGISTRY)
    return tuple(expand_skill_dependencies(requested))


def _planned_nodes(
    scope: _DatasetScope, skills: str | None, graph: dict[Node, set[Node]],
) -> set[Node]:
    if skills is not None:
        selected = _nodes(scope, set(_select_skills(skills)))
    else:
        selected = {
            (dataset, key)
            for dataset in scope.names
            for key, spec in SKILL_REGISTRY.items()
            if scope.domains[dataset] in spec.domains
            and ("*" in spec.mandatory_stages or (
                scope.domains[dataset] == "startups"
                and dataset in scope.stages
                and scope.stages[dataset] in spec.mandatory_stages
            ))
        }
    pending = list(selected)
    while pending:
        for dependency in graph[pending.pop()]:
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    return selected


def _nodes(datasets: _DatasetScope, skills: set[str]) -> set[Node]:
    return {
        (dataset, skill)
        for dataset in datasets.names
        for skill in skills
        if datasets.domains[dataset] in SKILL_REGISTRY[skill].domains
    }


def _dependency_graph(
    datasets: _DatasetScope,
    nodes: set[Node],
) -> dict[Node, set[Node]]:
    """Map nodes to local or cross-domain prerequisite nodes."""
    graph: dict[Node, set[Node]] = {}
    for dataset, skill in nodes:
        domain = datasets.domains[dataset]
        dependencies: set[Node] = set()
        for dependency in SKILL_REGISTRY[skill].depends_on:
            dependency_spec = SKILL_REGISTRY[dependency]
            if domain in dependency_spec.domains:
                candidate = (dataset, dependency)
                if candidate in nodes:
                    dependencies.add(candidate)
                continue

            dependencies.update(
                candidate
                for candidate in nodes
                if candidate[1] == dependency
            )
        graph[(dataset, skill)] = dependencies
    return graph


def _propagate_skips(
    nodes: set[Node],
    graph: dict[Node, set[Node]],
    outcomes: dict[Node, Outcome],
    failure_sources: dict[Node, set[Node]],
) -> None:
    """Propagate root failure sources through the complete skill graph."""
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if outcomes.get(node) in {"succeeded", "failed"}:
                continue
            inherited = {
                source
                for dependency in graph[node]
                if outcomes.get(dependency) in {"failed", "skipped"}
                for source in failure_sources[dependency]
            }
            if not inherited:
                continue
            previous = failure_sources[node]
            if outcomes.get(node) != "skipped" or not inherited.issubset(previous):
                outcomes[node] = "skipped"
                previous.update(inherited)
                changed = True


def _exception_text(error: BaseException) -> str:
    text = " ".join(str(error).split())
    return text or error.__class__.__name__


def _source_text(source: Node) -> str:
    dataset, skill = source
    if skill == "pre-ingestion":
        return f"pre-ingestion failed for {dataset}"
    return f"{skill} failed for {dataset}"


def _log_problem_table(
    ingestion_errors: dict[str, str],
    outcomes: dict[Node, Outcome],
    failure_errors: dict[Node, str],
    failure_sources: dict[Node, set[Node]],
) -> int:
    rows: list[tuple[str, str, str]] = [
        (dataset, "pre-ingestion", f"failed: {error}")
        for dataset, error in ingestion_errors.items()
    ]
    for node, outcome in outcomes.items():
        dataset, skill = node
        if outcome == "failed":
            rows.append((dataset, skill, f"failed: {failure_errors[node]}"))
        elif outcome == "skipped":
            reasons = ", ".join(
                _source_text(source)
                for source in sorted(failure_sources[node])
            )
            rows.append((dataset, skill, f"skipped: {reasons}"))

    if not rows:
        return 0

    logger.error("Bulk refresh completed with errors:")
    logger.error("| dataset | skill | exception |")
    logger.error("|---|---|---|")
    for dataset, skill, error in sorted(rows):
        safe_error = error.replace("|", "\\|")
        logger.error("| %s | %s | %s |", dataset, skill, safe_error)
    return len(rows)


async def _prepare_datasets(
    scope: _DatasetScope,
) -> dict[str, str]:
    """Parse/index the already resolved targets, without acquiring other datasets."""
    ingestion_errors: dict[str, str] = {}
    for dataset in scope.names:
        try:
            await sync_datasets([dataset], raise_on_error=True)
        except Exception as error:
            logger.exception(
                "[%s] Pre-ingestion failed; its skills will be skipped",
                dataset,
            )
            ingestion_errors[dataset] = _exception_text(error)
    return ingestion_errors


def _plan_jobs(
    scope: _DatasetScope, skills: str | None,
) -> tuple[set[Node], set[Node], dict[Node, set[Node]]]:
    all_nodes = _nodes(scope, set(SKILL_REGISTRY))
    graph = _dependency_graph(scope, all_nodes)
    planned_nodes = _planned_nodes(scope, skills, graph)
    return all_nodes, planned_nodes, graph


async def _invoke_skill(dataset: str, skill: str) -> object:
    spec = SKILL_REGISTRY[skill]
    if inspect.iscoroutinefunction(spec.func):
        result = await spec.func(dataset)
    else:
        result = await asyncio.to_thread(spec.func, dataset)
        if inspect.isawaitable(result):
            result = await result
    if spec.prepares_sources:
        await sync_datasets([dataset], raise_on_error=True)
    return result


async def bulk_refresh(
    datasets: str | None = None,
    skills: str | None = None,
    exclude: str | None = None,
) -> None:
    """Refresh selected insight skills without aborting on individual failures."""
    with dealum_session():
        await _bulk_refresh(datasets, skills, exclude)


async def _bulk_refresh(datasets: str | None, skills: str | None, exclude: str | None) -> None:
    # Reject invalid skills before any imports or marker changes.
    selected_skills = _select_skills(skills)
    selected_datasets, state_errors = _resolve_targets(datasets, exclude)
    logger.info(
        "Starting bulk refresh routine (skills=%s, datasets=%s)...",
        list(selected_skills) if skills is not None else "mandatory per stage",
        list(selected_datasets.names),
    )
    if not selected_datasets.names:
        if state_errors:
            _log_problem_table(state_errors, {}, {}, {})
            raise BulkRefreshError("Bulk refresh dataset-state update failed.")
        logger.warning("No valid datasets found to process.")
        return

    all_nodes, planned_nodes, graph = _plan_jobs(selected_datasets, skills)
    logger.info(
        "Planned %d dataset-skill jobs across %d datasets. Starting ingestion...",
        len(planned_nodes), len(selected_datasets.names),
    )
    healthy = _DatasetScope(
        tuple(name for name in selected_datasets.names if name not in state_errors),
        {name: domain for name, domain in selected_datasets.domains.items() if name not in state_errors},
        selected_datasets.stages,
    )
    ingestion_errors = await _prepare_datasets(healthy)
    ingestion_errors.update(state_errors)
    await _schedule_jobs(all_nodes, planned_nodes, graph, ingestion_errors)


async def _schedule_jobs(
    all_nodes: set[Node], planned_nodes: set[Node], graph: dict[Node, set[Node]],
    ingestion_errors: dict[str, str],
) -> None:
    planned_graph = {
        node: graph[node].intersection(planned_nodes)
        for node in planned_nodes
    }
    # Acquisition must finish before insights start, but optional evidence is
    # not a required dependency and must not propagate failure skips.
    acquisition_jobs: dict[str, set[Node]] = defaultdict(set)
    for node in planned_nodes:
        if SKILL_REGISTRY[node[1]].prepares_sources:
            acquisition_jobs[node[0]].add(node)

    outcomes: dict[Node, Outcome] = {}
    failure_errors: dict[Node, str] = {}
    failure_sources: dict[Node, set[Node]] = defaultdict(set)

    for dataset in ingestion_errors:
        source = (dataset, "pre-ingestion")
        for node in all_nodes:
            if node[0] == dataset:
                outcomes[node] = "skipped"
                failure_sources[node].add(source)

    _propagate_skips(all_nodes, graph, outcomes, failure_sources)
    pending = {node for node in planned_nodes if outcomes.get(node) is None}
    batch_index = 1

    while pending:
        _propagate_skips(all_nodes, graph, outcomes, failure_sources)
        pending = {node for node in pending if outcomes.get(node) is None}
        if not pending:
            break

        ready = sorted(
            node
            for node in pending
            if all(
                outcomes.get(dependency) == "succeeded"
                for dependency in planned_graph[node]
            )
            and (
                SKILL_REGISTRY[node[1]].prepares_sources
                or all(source in outcomes for source in acquisition_jobs[node[0]])
            )
        )
        if not ready:
            unresolved = ", ".join(
                f"{dataset}/{skill}" for dataset, skill in sorted(pending)
            )
            raise RuntimeError(
                "Circular or unresolvable bulk-refresh dependency graph: "
                + unresolved
            )

        logger.info(
            "--- Starting Job Batch %d (%d dataset-skill pairs) ---",
            batch_index,
            len(ready),
        )
        for dataset, skill in ready:
            logger.info("[%s] Queueing %s...", dataset, skill)

        results = await asyncio.gather(
            *(
                _invoke_skill(dataset, skill)
                for dataset, skill in ready
            ),
            return_exceptions=True,
        )
        for node, result in zip(ready, results):
            dataset, skill = node
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                outcomes[node] = "failed"
                failure_sources[node].add(node)
                failure_errors[node] = _exception_text(result)
                logger.error(
                    "[%s] Skill %s failed; bulk refresh will continue",
                    dataset,
                    skill,
                    exc_info=(type(result), result, result.__traceback__),
                )
            else:
                outcomes[node] = "succeeded"
                logger.info("[%s] Skill %s completed.", dataset, skill)
            pending.remove(node)

        _propagate_skips(all_nodes, graph, outcomes, failure_sources)
        batch_index += 1

    problem_count = _log_problem_table(
        ingestion_errors,
        outcomes,
        failure_errors,
        failure_sources,
    )
    if problem_count:
        raise BulkRefreshError(
            "Bulk refresh completed with "
            f"{problem_count} failed or skipped rows."
        )
    logger.info("Bulk refresh routine complete.")


__all__ = ["BulkRefreshError", "bulk_refresh"]
