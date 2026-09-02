"""Dependency-aware bulk insight refresh orchestration."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import dataset_location, list_all_dataset_names
from lib.datasets.state import is_active_dataset
from lib.infrastructure.logging import get_logger
from lib.slugify import slugify
from skills.skill_registry import SKILL_REGISTRY, expand_skill_dependencies

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


def _parse_selector(value: str | None, *, label: str) -> list[str]:
    if value is None:
        return []
    values = [slugify(item) for item in value.split(",") if slugify(item)]
    if not values:
        raise ValueError(f"{label} must contain at least one value.")
    return list(dict.fromkeys(values))


def _select_datasets(datasets: str | None) -> _DatasetScope:
    requested = _parse_selector(datasets, label="datasets")
    if ALL_DATASETS in requested and requested != [ALL_DATASETS]:
        raise ValueError("'all' cannot be combined with named datasets.")

    if requested == [ALL_DATASETS]:
        names = list_all_dataset_names(domains=SOURCE_DOMAINS)
    elif requested:
        names = requested
    else:
        names = [
            name
            for name in list_all_dataset_names(domains=SOURCE_DOMAINS)
            if is_active_dataset(name)
        ]

    domains: dict[str, str] = {}
    for name in names:
        location = dataset_location(name)
        if location.domain not in SOURCE_DOMAINS:
            raise ValueError(
                f"Dataset '{name}' belongs to unsupported bulk-refresh "
                f"domain '{location.domain}'."
            )
        domains[name] = location.domain
    return _DatasetScope(tuple(names), domains)


def _select_skills(skills: str | None) -> tuple[str, ...]:
    requested = _parse_selector(skills, label="skills")
    if not requested:
        return tuple(SKILL_REGISTRY)
    if ALL_DATASETS in requested:
        if requested != [ALL_DATASETS]:
            raise ValueError("'all' cannot be combined with named skills.")
        return tuple(SKILL_REGISTRY)
    return tuple(expand_skill_dependencies(requested))


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
) -> tuple[_DatasetScope, dict[str, str]]:
    """Resolve and ingest every dataset before any skill execution."""
    from lib.startups.sources import ensure_startup_dataset

    resolved_names: list[str] = []
    resolved_domains: dict[str, str] = {}
    ingestion_errors: dict[str, str] = {}

    for requested_name in scope.names:
        domain = scope.domains[requested_name]
        effective_name = requested_name
        try:
            if domain == "startups":
                status = await ensure_startup_dataset(
                    requested_name,
                    sync_after_import=False,
                )
                effective_name = status.dataset_slug
            await sync_datasets([effective_name], raise_on_error=True)
        except Exception as error:
            logger.exception(
                "[%s] Pre-ingestion failed; its skills will be skipped",
                requested_name,
            )
            ingestion_errors[requested_name] = _exception_text(error)
            resolved_names.append(requested_name)
            resolved_domains[requested_name] = domain
            continue

        if effective_name not in resolved_domains:
            resolved_names.append(effective_name)
        resolved_domains[effective_name] = domain

    return _DatasetScope(tuple(resolved_names), resolved_domains), ingestion_errors


async def bulk_refresh(
    datasets: str | None = None,
    skills: str | None = None,
) -> None:
    """Refresh selected insight skills without aborting on individual failures."""
    selected_datasets = _select_datasets(datasets)
    selected_skills = _select_skills(skills)
    logger.info(
        "Starting bulk refresh routine (skills=%s, datasets=%s)...",
        list(selected_skills),
        list(selected_datasets.names),
    )
    if not selected_datasets.names:
        logger.warning("No valid datasets found to process.")
        return

    logger.info(
        "Selected %d datasets. Starting pre-ingestion barrier...",
        len(selected_datasets.names),
    )
    scope, ingestion_errors = await _prepare_datasets(selected_datasets)
    logger.info("Pre-ingestion complete. Building skill execution graph.")

    all_nodes = _nodes(scope, set(SKILL_REGISTRY))
    planned_nodes = _nodes(scope, set(selected_skills))
    graph = _dependency_graph(scope, all_nodes)
    planned_graph = {
        node: graph[node].intersection(planned_nodes)
        for node in planned_nodes
    }

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
                SKILL_REGISTRY[skill].func(dataset)
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
