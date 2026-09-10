from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ChecklistCheck:
    number: str
    name: str
    description: str
    keywords: list[str]


@dataclass(frozen=True)
class ChecklistChapter:
    number: str
    title: str
    checks: list[ChecklistCheck]


@dataclass(frozen=True)
class Checklist:
    title: str
    chapters: list[ChecklistChapter]


_KEYWORDS = re.compile(r"^\s*\*\*Keywords:\*\*\s*(.*)$", re.IGNORECASE)
_TITLE_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+.+$")


def _block(lines: list[str]) -> str:
    """Normalize a Markdown text block while retaining paragraph breaks."""
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def _keywords(lines: list[str]) -> list[str]:
    values: list[str] = []
    for value in re.split(r"[,;\n]", "\n".join(lines)):
        clean = re.sub(r"^\s*[-*+]\s+", "", value).strip()
        if clean and clean not in values:
            values.append(clean)
    return values


def parse_checklist(markdown: str) -> Checklist:
    """Parse the expert-facing Markdown checklist format."""
    title: str | None = None
    chapters: list[ChecklistChapter] = []
    chapter_title: str | None = None
    checks: list[ChecklistCheck] = []
    check_name: str | None = None
    description_lines: list[str] = []
    keyword_lines: list[str] = []
    reading_keywords = False

    def chapter_number() -> str:
        chapter_index = str(len(chapters) + 1)
        if title is None:
            return chapter_index
        match = _TITLE_NUMBER.match(title)
        return f"{match.group(1)}.{chapter_index}" if match else chapter_index

    def finish_check() -> None:
        nonlocal check_name, description_lines, keyword_lines, reading_keywords
        if check_name is None:
            return
        description = _block(description_lines)
        if not description:
            raise ValueError(f"Checklist check {check_name!r} has no description.")
        checks.append(
            ChecklistCheck(
                number=f"{chapter_number()}.{len(checks) + 1}",
                name=check_name,
                description=description,
                keywords=_keywords(keyword_lines),
            )
        )
        check_name = None
        description_lines = []
        keyword_lines = []
        reading_keywords = False

    def finish_chapter() -> None:
        nonlocal chapter_title, checks
        finish_check()
        if chapter_title is None:
            return
        if not checks:
            raise ValueError(f"Checklist chapter {chapter_title!r} has no checks.")
        chapters.append(
            ChecklistChapter(
                number=chapter_number(),
                title=chapter_title,
                checks=checks,
            )
        )
        chapter_title = None
        checks = []

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        heading = re.match(r"^(#{1,})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            heading_text = heading.group(2).strip()
            if level == 1:
                if title is not None:
                    raise ValueError("A checklist must contain exactly one level-one title.")
                if chapter_title is not None or check_name is not None:
                    raise ValueError("The checklist title must appear before its chapters.")
                title = heading_text
            elif level == 2:
                if title is None:
                    raise ValueError("A checklist chapter requires a level-one title.")
                finish_chapter()
                chapter_title = heading_text
            elif level == 3:
                if chapter_title is None:
                    raise ValueError("A checklist check requires a level-two chapter.")
                finish_check()
                check_name = heading_text
            else:
                raise ValueError(f"Unsupported checklist heading level: {level}.")
            continue

        keyword_match = _KEYWORDS.match(line)
        if keyword_match:
            if check_name is None:
                raise ValueError("Keywords must belong to a checklist check.")
            reading_keywords = True
            keyword_lines.append(keyword_match.group(1))
            continue

        if check_name is None:
            if line.strip():
                raise ValueError(
                    "Checklist content must be inside a level-three check."
                )
            continue
        if reading_keywords:
            keyword_lines.append(line)
        else:
            description_lines.append(line)

    finish_chapter()
    if title is None:
        raise ValueError("A checklist requires a level-one title.")
    if not chapters:
        raise ValueError("A checklist requires at least one chapter.")
    return Checklist(title=title, chapters=chapters)
