"""DD checks and priorities written by an agent with tools scoped to one startup's data room.

The agent decides the product type, assesses every check of the DD checklists
and writes the priorities. The OpenAI Agents SDK runs the agent loop; its
wiring in agent_runner.py is imported only for a run. This module provides the
tools, checks that every check was assessed and saves the chapter audits, the
report and the priorities in the formats of the pipeline.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from lib.batch_audit.checklist import Checklist, ChecklistCheck, parse_checklist
from lib.batch_audit.rendering import json_to_markdown_table
from lib.batch_audit.schema import AUDIT_SCHEMA_VERSION, validate_audit_document
from lib.datasets.page_markers import split_text_by_pages
from lib.datasets.paths import dataset_location
from lib.datasets.source import list_source_files, parsed_filepath
from lib.infrastructure.ai_text_generation.json import validate_json_schema
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile
from lib.model_config import llm_model
from lib.startups.dealum.manifest import read_manifest
from lib.storage import get_storage
from skills.dd_checks.dd_checks import (
    agent_config_key,
    checklist_chapters_and_types,
    select_checklists,
    top_findings_section,
)

logger = get_logger(__name__)

# Skill name in the chapter audits, the same as in the pipeline's audits.
AUDIT_SKILL = "dd_checks"


@dataclass
class DataRoom:
    """Read-only access to the current parsed documents of one startup."""

    startup_slug: str
    # Storage path of the parsed Markdown per source document path.
    parsed_paths: dict[str, str]
    # Most characters one read_document call returns.
    max_read_characters: int
    # Most matches one search_text call returns.
    max_search_results: int
    # Length of the text shown around a search match, in characters.
    excerpt_characters: int
    # Length of each document's first words in list_documents, in characters.
    preview_characters: int
    documents_read: set[str] = field(default_factory=set)

    @classmethod
    def for_startup(cls, startup_slug: str, settings: dict[str, Any]) -> DataRoom:
        """Collect the current sources of the startup that have parsed text."""
        storage = get_storage()
        location = dataset_location(startup_slug)
        parsed_paths = {}
        for filename, _mtime in sorted(list_source_files(storage, location.raw_rel)):
            path = parsed_filepath(location.parsed_rel, filename)
            if storage.exists(path):
                parsed_paths[filename] = path
        return cls(
            startup_slug=startup_slug,
            parsed_paths=parsed_paths,
            max_read_characters=settings["max_read_characters"],
            max_search_results=settings["max_search_results"],
            excerpt_characters=settings["search_excerpt_characters"],
            preview_characters=settings["document_preview_characters"],
        )

    def _pages(self, document: str) -> list[tuple[int | str, str]]:
        return split_text_by_pages(get_storage().read_text(self.parsed_paths[document]))

    def list_documents(self) -> str:
        lines = []
        for document in self.parsed_paths:
            pages = self._pages(document)
            numbered = [page for page, _text in pages if isinstance(page, int)]
            characters = sum(len(text) for _page, text in pages)
            page_info = f"pages {min(numbered)}-{max(numbered)}" if numbered else "no page numbers"
            first_words = self._first_words(pages)
            lines.append(
                f"- {document} ({page_info}, {characters} characters)"
                + (f": {first_words}" if first_words else "")
            )
        return "\n".join(lines) or "The data room contains no parsed documents."

    def _first_words(self, pages: list[tuple[int | str, str]]) -> str:
        """Return the start of a document's text without markup, so the agent sees its language."""
        text = " ".join(page_text for _page, page_text in pages)
        # Conversion comments such as <!-- image -->, headings and table lines.
        text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
        text = re.sub(r"[#|*]+|-{3,}", " ", text)
        text = " ".join(text.split())
        if len(text) <= self.preview_characters:
            return text
        return text[: self.preview_characters] + "…"

    def read_document(
        self,
        document: str,
        first_page: int | None = None,
        last_page: int | None = None,
    ) -> str:
        if document not in self.parsed_paths:
            return f"Unknown document: {document!r}. Use a path from list_documents."
        self.documents_read.add(document)
        sections = []
        for page, text in self._pages(document):
            if isinstance(page, int):
                if first_page is not None and page < first_page:
                    continue
                if last_page is not None and page > last_page:
                    continue
            sections.append((page, text))
        if not sections:
            return f"{document} has no text on the requested pages."
        output, length = [], 0
        for page, text in sections:
            block = f"## {document}, page {page}\n\n{text}"
            if output and length + len(block) > self.max_read_characters:
                output.append(
                    f"[Stopped before page {page} to stay within the reading limit. "
                    f"Call read_document with first_page={page} to continue.]"
                )
                break
            output.append(block[: self.max_read_characters])
            length += len(block)
        return "\n\n".join(output)

    def search_text(self, pattern: str) -> str:
        try:
            expression = re.compile(pattern, re.IGNORECASE)
        except re.error:
            expression = re.compile(re.escape(pattern), re.IGNORECASE)
        half = self.excerpt_characters // 2
        matches = []
        for document in self.parsed_paths:
            for page, text in self._pages(document):
                for match in expression.finditer(text):
                    excerpt = " ".join(text[max(0, match.start() - half): match.end() + half].split())
                    matches.append(f"- {document}, page {page}: …{excerpt}…")
                    if len(matches) > self.max_search_results:
                        return "\n".join(matches[: self.max_search_results]) + (
                            "\n[More matches exist; use a more specific pattern.]"
                        )
        return "\n".join(matches) or f"No matches for {pattern!r}."


@dataclass
class DdReview:
    """State of one agent run: the selected checklists and the recorded results."""

    # Startup name used in the instructions.
    startup: str
    data_room: DataRoom
    dd_config: dict[str, Any]
    response_schema: dict[str, Any]
    product_type: str | None = None
    # Selected checklists as (chapter key, parsed checklist).
    checklists: list[tuple[str, Checklist]] = field(default_factory=list)
    # Recorded result per check number.
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    priorities: str | None = None
    tool_calls: Counter = field(default_factory=Counter)

    def product_types(self) -> set[str]:
        return checklist_chapters_and_types(self.dd_config)[1]

    def get_checklists(self, product_type: str) -> str:
        normalized = product_type.strip().casefold()
        allowed = sorted(self.product_types())
        if normalized not in allowed:
            return f"Unknown product type {product_type!r}. Use one of: {', '.join(allowed)}."
        if self.product_type and normalized != self.product_type and self.results:
            return (
                f"Checks were already recorded for product type {self.product_type!r}; "
                "the product type cannot change now."
            )
        chapters = checklist_chapters_and_types(self.dd_config)[0]
        self.product_type = normalized
        self.checklists = [
            (chapter, parse_checklist(markdown))
            for chapter, markdown in select_checklists(self.dd_config, chapters, normalized)
        ]
        lines = [f"Product type: {normalized}. Assess these checklists:"]
        lines += [
            f"- {checklist.title} ({sum(len(c.checks) for c in checklist.chapters)} checks)"
            for _chapter, checklist in self.checklists
        ]
        return "\n".join(lines)

    def _checklist(self, title: str) -> Checklist | None:
        wanted = title.strip().casefold()
        for chapter, checklist in self.checklists:
            if wanted in {checklist.title.casefold(), chapter.casefold()}:
                return checklist
        return None

    def get_checklist(self, title: str) -> str:
        if not self.checklists:
            return "No checklists selected yet; the product type must be decided first."
        checklist = self._checklist(title)
        if checklist is None:
            titles = ", ".join(checklist.title for _chapter, checklist in self.checklists)
            return f"Unknown checklist {title!r}. Use one of: {titles}."
        lines = [f"# {checklist.title}"]
        for chapter in checklist.chapters:
            lines.append(f"\n## {chapter.number} {chapter.title}")
            for check in chapter.checks:
                recorded = " (recorded)" if check.number in self.results else ""
                lines.append(f"\n### {check.number} {check.name}{recorded}\n\n{check.description}")
        return "\n".join(lines)

    def expected_checks(self) -> dict[str, ChecklistCheck]:
        return {
            check.number: check
            for _chapter, checklist in self.checklists
            for chapter in checklist.chapters
            for check in chapter.checks
        }

    def missing_checks(self) -> list[str]:
        return [number for number in self.expected_checks() if number not in self.results]

    def record_check(self, number: str, result_json: str) -> str:
        expected = self.expected_checks()
        if not expected:
            return "No checklists selected yet; the product type must be decided first."
        number = number.strip()
        if number not in expected:
            return f"Unknown check number {number!r}. Use the numbers from get_checklist."
        try:
            result = json.loads(result_json)
        except json.JSONDecodeError as error:
            return f"The result is not valid JSON: {error}. Record check {number} again."
        try:
            validate_json_schema(result, self.response_schema, label=f"Result of check {number}")
        except ValueError as error:
            return f"{error}. Record check {number} again."
        self.results[number] = result
        return f"Recorded check {number}. {len(self.missing_checks())} checks are still open."

    def recorded_checks(self) -> str:
        expected = self.expected_checks()
        if not self.results:
            return "No checks recorded yet."
        lines = ["| No | Check | Status | Importance | Rationale |", "|---|---|---|---|---|"]
        for number, check in expected.items():
            result = self.results.get(number)
            if result is None:
                lines.append(f"| {number} | {check.name} | not recorded | | |")
                continue
            rationale = " ".join(str(result.get("rationale", "")).split())
            lines.append(
                f"| {number} | {check.name} | {result.get('status')} | "
                f"{result.get('importance')} | {rationale} |"
            )
        return "\n".join(lines)

    def submit_priorities(self, markdown: str) -> str:
        if not markdown.strip():
            return "The priorities are empty; submit the complete Markdown."
        missing = self.missing_checks()
        if not self.checklists or missing:
            return f"Record all checks first; {len(missing)} checks are still open."
        self.priorities = markdown.strip()
        return "Priorities saved."

    def audit_documents(self, model: str) -> list[tuple[Checklist, dict[str, Any]]]:
        """Return each checklist with its results in the batch-audit envelope."""
        generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        documents = []
        for _chapter_key, checklist in self.checklists:
            document = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "skill": AUDIT_SKILL,
                "checklist_title": checklist.title,
                "dataset": self.data_room.startup_slug,
                "model": model,
                "generated_at": generated_at,
                "response_schema": self.response_schema,
                "chapters": [
                    {
                        "number": chapter.number,
                        "title": chapter.title,
                        "checks": [
                            {
                                "number": check.number,
                                "check": check.name,
                                "result": self.results[check.number],
                                "error": None,
                            }
                            for check in chapter.checks
                        ],
                    }
                    for chapter in checklist.chapters
                ],
            }
            documents.append((checklist, validate_audit_document(document, require_complete=True)))
        return documents


def fill_placeholders(template: str, **values: str) -> str:
    """Replace each {{name}} in the template with its value."""
    for name, value in values.items():
        template = template.replace("{{" + name + "}}", value)
    return template


def follow_up_message(review: DdReview) -> str | None:
    """Return the message that asks the agent to finish, or None when it is complete."""
    if not review.checklists:
        return "Decide the product type with get_checklists, then continue the review."
    missing = review.missing_checks()
    if missing:
        return (
            f"These checks are not recorded yet: {', '.join(missing)}. Assess them "
            "with assess_checklist, then submit the priorities."
        )
    if review.priorities is None:
        return "All checks are recorded. Submit the priorities with submit_priorities."
    return None


def _startup_name(startup_slug: str, fallback: str) -> str:
    name = read_manifest(startup_slug).get("startup")
    return " ".join(str(name).split()) if name else fallback


async def agent_dd_checks(
    startup_slug: str,
    startup: str,
    config: dict[str, Any],
) -> list[InsightFile]:
    """Return the agent's DD report; run the agent unless the report and priorities are reusable.

    A run saves the report `dd-checks-<startup>-<model>.md`, the priorities
    `dd-priorities-<startup>-<model>.md` and the chapter audits. A manual report
    is returned without a run. The dataset must be prepared and synchronized.

    Args:
        startup_slug: Canonical slug of the startup's dataset.
        startup: Startup name as given by the caller, used when the Dealum
            manifest has no name.
        config: The complete repository configuration.
    """
    dd_config = config["dd_checks"]
    model = llm_model()
    config_key = agent_config_key(config)
    report = InsightFile(startup_slug, "dd_checks", model, config_key=config_key)
    priorities = InsightFile(startup_slug, "dd_priorities", model, config_key=config_key)
    reusable = report.find(selection="reusable")
    if reusable is not None and (
        reusable.model == "manual" or priorities.find(selection="reusable") is not None
    ):
        return [reusable]

    settings = dd_config["settings"]["agent"]
    data_room = DataRoom.for_startup(startup_slug, settings)
    if not data_room.parsed_paths:
        raise ValueError(f"{startup_slug} has no parsed documents to review.")
    startup_name = _startup_name(startup_slug, startup)
    review = DdReview(
        startup=startup_name,
        data_room=data_room,
        dd_config=dd_config,
        response_schema=dd_config["audit_response_schema"],
    )
    # Imported only for a run, so tests can replace the SDK wiring.
    from skills.dd_checks.agent_runner import run_review

    started = time.monotonic()
    usage, follow_up = await run_review(review, config)
    runtime_seconds = round(time.monotonic() - started, 1)
    missing = review.missing_checks()
    if not review.checklists or missing or review.priorities is None:
        raise RuntimeError(
            f"[{startup_slug}] The DD agent did not finish: product type "
            f"{review.product_type!r}, {len(missing)} checks not recorded "
            f"({', '.join(missing[:20])}), priorities "
            f"{'submitted' if review.priorities else 'missing'}; it used "
            f"{usage.total_tokens} tokens in {runtime_seconds} s."
        )

    audits = []
    for checklist, document in review.audit_documents(model):
        audit = InsightFile(
            dataset=startup_slug,
            skill="batch_audit",
            model=model,
            identifier=f"{AUDIT_SKILL}-{checklist.title}",
            subdir=True,
            extension="json",
            config_key=config_key,
        )
        audit.save(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        audits.append(audit)
    sections = [
        f"## Chapter: {chapter}\n\n{json_to_markdown_table(audit)}\n"
        for (chapter, _checklist), audit in zip(review.checklists, audits)
    ]
    report.save(
        f"# M&A Due Diligence Checks for {startup_name}\n\n"
        f"**Product type:** {review.product_type}\n\n"
        + "\n\n".join([top_findings_section(audits, dd_config), *sections])
        + "\n"
    )
    priorities.save(review.priorities + "\n")
    logger.info(
        "[%s] DD agent finished in %s s with %s tokens; read %d of %d documents; "
        "follow-up needed: %s; tool calls: %s",
        startup_slug, runtime_seconds, usage.total_tokens, len(data_room.documents_read),
        len(data_room.parsed_paths), follow_up, dict(review.tool_calls),
    )
    return [report]
