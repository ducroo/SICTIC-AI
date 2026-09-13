"""Source-line evidence for cap-table, share-register and pool extraction.

A quote is a list of source fragments separated by line breaks or ellipses.
Every fragment must resolve to one source line: a table fragment by the
subsequence of its quoted cells within one source row (dropped or trailing
cells are tolerated, cell boundaries are never crossed), a prose fragment
by substring within a few adjacent lines. Numbers are read from the resolved
source cells, never from the quote, so digits are never joined across
cells, only an explicit marker evidences a zero, and a blank cell or an
absent column evidences nothing. A holder's numbers come only from resolved
rows that name the holder: in a cell, through the row that owns a run of
nameless rows above, through a column header, through a section row of the
same table, or in the text directly above the table. Additive fields sum
every such row in one column, never a subset. The whole document is never
searched for a holder's name. Share classes and pools are described across
the rows of one sheet, so once a quoted row of a table names them the other
quoted rows of that table count; a class may also be quoted by the header
that names it. Converter quirks are read locally: page markers inside a
table, a first data row declared as a header, a numeral split at its
apostrophe into the next cell, an escaped pipe inside a cell, a quoted list
spanning a few adjacent lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import difflib
import re

from lib.captable.aggregation import normalize_lender_name
from lib.captable.documents import normalize_for_matching
from lib.markdown_tables import is_separator_row, is_table_line, parse_table, split_cells

# Column meanings used to exclude columns that cannot evidence a field.
# Vocabulary, not thresholds: a header naming certificates, dates, money
# or percentages never evidences a share count, and vice versa.
_CERT_LIKE = re.compile(r"certificat|zertifikat|urkunde|\bid\b|\bdate\b|datum|\bfrom\b|\bto\b|\bvon\b|\bbis\b")
_NUMBERING = re.compile(r"\bno\.?\b|\bnr\.?\b|\bnumber\b|nummer|\bnum\b|#")
_COUNTING = re.compile(r"anzahl|count|number of|no\.? of|nombre de|total|stück")
_PCT_LIKE = re.compile(r"%|percent|prozent|(?<![a-zß])anteil(?![a-zß])|beteiligung|participation|ownership|\bpct\b|\bquota\b|\bquote\b")
_MONEY_LIKE = re.compile(r"invest|amount|betrag|price|preis|prix|valuation|bewertung|montant")
_NOMINAL_LIKE = re.compile(r"nominal|nennwert|par value|\bchf\b|\beur\b|\busd\b|€|\$")
_VOTES_LIKE = re.compile(r"\bvotes?\b|voting rights|stimmen\b|stimmrechte\b")
_COMMON_LIKE = re.compile(r"common|ordinary|stamm|ordinaire")
_PREFERRED_LIKE = re.compile(r"prefer|vorzug|privil|\bseries\b|\bserie\b|\bseed\b|\bpref\b")
_NAME_COLUMN = re.compile(r"holder|\bname\b|aktion[äa]r|shareholder|actionnaire|inhaber|group|label|pool|bezeichnung|titulaire|\bnom\b")

COUNT_FIELDS = frozenset({
    "current_common", "current_preferred", "count", "issued_total",
    "diluted_count", "diluted_total", "total", "granted", "unallocated",
})
# Fields that may be the sum of several quoted rows (certificate lines).
ADDITIVE_FIELDS = frozenset({"current_common", "current_preferred", "count", "issued_total", "diluted_count"})
# In prose, these values must follow their label; a share count in the same
# sentence is not a nominal value.
_PROSE_LABELS = {
    "nominal_value": re.compile(r"nominal|nennwert|par value|valeur nominale", re.I),
    "votes_per_share": re.compile(r"\bvotes?\b|\bvoting\b|stimm", re.I),
}
_ZERO_MARKERS = frozenset({"-", "–", "—", "0", "none", "nil", "keine", "aucun", "aucune"})
_PAGE_MARKER = re.compile(r"^\s*<!--\s*[\w-]*page[\w-]*\s*:\s*\d+\s*-->\s*$")
_FRAGMENT_SPLIT = re.compile(r"\r?\n|\.{3,}|…")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_HEADING = re.compile(r"^\s*#{1,6}\s+\S")
PROSE_WINDOW = 8         # adjacent prose lines one fragment may span (a quoted list)
CONTEXT_LINES = 3        # prose lines directly above a table that may name a row
TITLE_LINES = 5          # opening prose lines that may name a pool
NEARBY_LINES = 10        # prose fragments this close may share one identity

# How far a name may sit from the quoted row, per extracted collection.
ROW_SCOPE = "row"            # holders: the row, its owner row, header, section, text above
TABLE_SCOPE = "table"        # share classes: any line of the same table
DOCUMENT_HEADINGS = "headings"  # pools: additionally headings and the title block


_ENTITY = re.compile(r"&#\d+;|&#x[0-9a-fA-F]+;|&[a-zA-Z]+;")


def _clean_cell(cell: str) -> str:
    """Drop HTML entities converters leave in cells ("&#124;" for a pipe)."""
    return _ENTITY.sub(" ", cell)


def numbers(text: str) -> list[Decimal]:
    """Numerals of one cell or passage, repaired only within that text.

    Swiss apostrophes padded by PDF conversion ("145 ' 832") and stray
    spaces inside a grouped numeral ("21'66 6") are joined; nothing is
    joined across the boundary of the text passed in. Occurrences are
    preserved so repeated amounts still count separately.
    """
    text = re.sub(
        r"(?<=\d)[   ]*['’][   ]*(\d[   ]*\d[   ]*\d)(?!\d)",
        lambda m: re.sub(r"\s", "", m[1]), text,
    )
    text = re.sub(r"(?<=\d)[   ](?=\d{3}(?:\D|$))", "", text)
    result = []
    for token in re.findall(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*", text):
        if "," in token and "." in token:
            decimal, grouping = (".", ",") if token.rfind(".") > token.rfind(",") else (",", ".")
            token = token.replace(grouping, "").replace(decimal, ".")
        elif "," in token:
            token = token.replace(",", "") if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+", token) else token.replace(",", ".")
        elif token.count(".") > 1:
            if not re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+", token):
                continue
            token = token.replace(".", "")
        try:
            result.append(Decimal(token))
        except InvalidOperation:
            continue
    return result


def cell_values(cell: str) -> list[Decimal]:
    """Numbers stated by one source cell; an explicit marker states zero."""
    cell = _clean_cell(cell)
    if cell.strip().casefold() in _ZERO_MARKERS:
        return [Decimal(0)]
    return numbers(cell)


_PERCENTAGE = re.compile(r"[+-]?[\d.,'\u2019\u00a0\u202f ]*\d\s*%")


def row_values(cells: tuple[str, ...], percentages: bool = True) -> list[list[Decimal]]:
    """Numbers per cell of a row.

    OCR sometimes breaks a grouped numeral at its apostrophe into the next
    cell ("28 5 '" | "135"): a cell ending in a dangling apostrophe joins
    the three digits that open the next cell. Nothing else crosses a cell.
    Without ``percentages``, figures written as percentages are dropped:
    they state a share of ownership, never a count or an amount.
    """
    values: list[list[Decimal]] = []
    carry = ""
    for index, cell in enumerate(cells):
        text = cell[len(carry):] if carry else cell
        carry = ""
        following = cells[index + 1] if index + 1 < len(cells) else ""
        if re.search(r"\d\s*['\u2019]\s*$", text) and re.match(r"\s*\d{3}(?!\d)", following):
            carry = re.match(r"\s*\d{3}", following)[0]
            text = text + carry
        if not percentages:
            text = _PERCENTAGE.sub(" ", text)
        values.append(cell_values(text))
    return values


@dataclass(frozen=True)
class SourceLine:
    index: int
    text: str
    kind: str                      # "row", "header", "separator", "prose", "blank"
    cells: tuple[str, ...] = ()
    table: int = -1                # table id, -1 outside tables
    headers: tuple[str, ...] = ()  # column names of the table, () when unknown
    run: int = -1                  # prose run id, -1 outside prose


@dataclass
class Resolved:
    fragment: str
    line: SourceLine
    passage: str = ""                                    # prose window the fragment sits in
    binding: tuple[str, tuple[int, ...]] | None = None   # how the identity was found

    @property
    def is_row(self) -> bool:
        return self.line.kind == "row"


def _is_numeric_cell(cell: str) -> bool:
    key = cell.strip().casefold()
    return key in _ZERO_MARKERS or (bool(numbers(cell)) and not re.search(r"[a-zA-ZÀ-ɏ]{2,}", cell))


def _is_text_cell(cell: str) -> bool:
    return bool(cell.strip()) and not _is_numeric_cell(cell)


def _drop_page_breaks(raw_lines: list[str]) -> list[str]:
    """Remove page markers (and the blanks around them) that split a table."""
    kept: list[str] = []
    index = 0
    while index < len(raw_lines):
        line = raw_lines[index]
        if _PAGE_MARKER.match(line):
            before = len(kept) - 1
            while before >= 0 and not kept[before].strip():
                before -= 1
            after = index + 1
            while after < len(raw_lines) and not raw_lines[after].strip():
                after += 1
            if before >= 0 and is_table_line(kept[before]) and after < len(raw_lines) and is_table_line(raw_lines[after]):
                del kept[before + 1:]
                index = after
                continue
            index += 1
            continue
        kept.append(line)
        index += 1
    return kept


def source_lines(document: str) -> list[SourceLine]:
    """Every source line, with table structure where present.

    Page markers between table lines are transparent so a table continued
    on the next page is one table. A header declared by a separator row is
    context only, unless its cells are mostly numbers: converters make the
    first row of every table a header, and that row is often a data row.
    """
    lines: list[SourceLine] = []
    pending: list[str] = []
    table_id = 0
    run = 0
    in_run = False

    def flush_table() -> None:
        nonlocal table_id
        if not pending:
            return
        block = parse_table(pending)
        headers = tuple(split_cells(block.header)) if block.header else ()
        declared = bool(block.separator)
        numeric = sum(1 for cell in headers if _is_numeric_cell(cell))
        if numeric and numeric >= sum(1 for cell in headers if _is_text_cell(cell)):
            headers, declared = (), False
        header_key = tuple(normalize_for_matching(cell) for cell in headers)
        for raw in pending:
            cells = tuple(split_cells(raw))
            if is_separator_row(raw):
                kind = "separator"
            elif declared and headers and tuple(normalize_for_matching(c) for c in cells) == header_key:
                kind = "header"
            else:
                kind = "row"
            lines.append(SourceLine(len(lines), raw, kind, cells, table_id, headers))
        table_id += 1
        pending.clear()

    for raw in _drop_page_breaks(document.splitlines()):
        if is_table_line(raw):
            pending.append(raw.strip())
            in_run = False
            continue
        flush_table()
        if raw.strip():
            if not in_run:
                run += 1
                in_run = True
            lines.append(SourceLine(len(lines), raw.strip(), "prose", run=run))
        else:
            lines.append(SourceLine(len(lines), "", "blank"))
    flush_table()
    return lines


class Source:
    """A parsed document with the lookups the evidence rules need."""

    def __init__(self, document: str):
        self.lines = source_lines(document)
        self._runs: dict[int, list[SourceLine]] = {}
        for line in self.lines:
            if line.kind == "prose":
                self._runs.setdefault(line.run, []).append(line)
        self._keys = {line.index: normalize_for_matching(line.text) for line in self.lines}

    def find_prose(self, key: str) -> list[tuple[SourceLine, str]]:
        """Prose windows of up to PROSE_WINDOW adjacent lines containing key."""
        found: list[tuple[SourceLine, str]] = []
        for run_lines in self._runs.values():
            for start in range(len(run_lines)):
                for width in range(1, PROSE_WINDOW + 1):
                    window = run_lines[start:start + width]
                    if len(window) < width:
                        break
                    if key in "".join(self._keys[line.index] for line in window):
                        found.append((window[0], " ".join(line.text for line in window)))
                        break
        return found

    def table_lines(self, table: int) -> list[SourceLine]:
        return [line for line in self.lines if line.table == table]

    def name_column(self, table: int) -> int | None:
        """The column that names holders, when the header says so."""
        first = next((line for line in self.lines if line.table == table), None)
        if first is None:
            return None
        for index, header in enumerate(first.headers):
            key = header.casefold()
            if _NAME_COLUMN.search(key) and not re.fullmatch(r"\s*(?:no|nr)\.?\s*", key):
                return index
        return None

    def owner_row(self, line: SourceLine, name_column: int | None) -> SourceLine | None:
        """The named row that owns a run of nameless rows ending at ``line``.

        A row is nameless when its name cell is empty or numeric. The walk
        up the table stops at the first row carrying text in that cell, so
        a continuation never borrows a name across another named holder.
        """
        if name_column is not None:
            if name_column >= len(line.cells) or _is_text_cell(line.cells[name_column]):
                return None
            positions = [name_column]
        else:
            positions = [i for i, cell in enumerate(line.cells) if not cell.strip()]
            if not positions:
                return None
        for previous in reversed(self.lines[: line.index]):
            if previous.table != line.table:
                break
            if previous.kind != "row" or len(previous.cells) != len(line.cells):
                continue
            if any(i < len(previous.cells) and _is_text_cell(previous.cells[i]) for i in positions):
                return previous
        return None

    def section_rows(self, line: SourceLine) -> list[SourceLine]:
        """Rows above with a single text cell: section labels of a sheet."""
        found: list[SourceLine] = []
        for previous in reversed(self.lines[: line.index]):
            if previous.table != line.table:
                break
            filled = [cell for cell in previous.cells if cell.strip()]
            if previous.kind == "row" and len(filled) == 1 and _is_text_cell(filled[0]):
                found.append(previous)
        return found

    def context_above(self, table: int) -> list[SourceLine]:
        """Prose lines directly above a table (a heading, a pool letter)."""
        first = next((line for line in self.lines if line.table == table), None)
        if first is None:
            return []
        found: list[SourceLine] = []
        for previous in reversed(self.lines[: first.index]):
            if previous.kind == "blank":
                continue
            if previous.kind != "prose" or len(found) >= CONTEXT_LINES:
                break
            found.append(previous)
        return found

    def headings(self) -> list[SourceLine]:
        """Markdown headings and the title block of the document."""
        prose = [line for line in self.lines if line.kind == "prose" and not line.text.startswith("<!--")]
        return [line for line in prose if _HEADING.match(line.text)] + prose[:TITLE_LINES]

    def closest_line(self, fragment: str) -> str | None:
        """The source line most similar to an unresolved fragment."""
        key = normalize_for_matching(fragment)
        if not key:
            return None
        candidates = {self._keys[line.index]: line.text for line in self.lines if line.text}
        matches = difflib.get_close_matches(key, list(candidates), n=1, cutoff=0.6)
        return candidates[matches[0]] if matches else None


def _cell_key(cell: str) -> str:
    """Comparable form of a cell: alphanumerics, or the marker itself."""
    stripped = _clean_cell(cell).strip()
    if stripped.casefold() in _ZERO_MARKERS:
        return stripped
    return normalize_for_matching(stripped)


def quote_cells(fragment: str) -> list[str]:
    """Cells of a quoted table fragment, tolerating a missing outer pipe."""
    stripped = fragment.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in _CELL_SPLIT.split(stripped)]


def _cells_match_row(quoted: list[str], row: SourceLine) -> bool:
    """Quoted cells appear in order within the row, each inside one cell."""
    # Cells without letters or digits ("#", "*") carry nothing to match.
    keys = [key for key in (_cell_key(cell) for cell in quoted) if key]
    if not keys:
        return False
    sources = [_cell_key(cell) for cell in row.cells]
    position = 0      # next source cell to try
    current = ""      # source cell matched last; a split cell may match several quoted cells
    for key in keys:
        if current and key not in _ZERO_MARKERS and key in current:
            continue
        while position < len(sources):
            source = sources[position]
            position += 1
            if source and (key == source or (key not in _ZERO_MARKERS and key in source)):
                current = source
                break
        else:
            return False
    return True


def _substantial(fragment: str) -> bool:
    """A fragment must carry enough to identify a source line."""
    return bool(re.search(r"[a-zA-ZÀ-ɏ]", fragment)) or len(numbers(fragment)) >= 2


def identity_in_text(identity: str, text: str) -> bool:
    """The identity appears in the text, contiguously or token by token.

    Tokens must all sit in this text (a row, a header cell, a passage),
    never spread across the document.
    """
    key = normalize_for_matching(identity)
    text_key = normalize_for_matching(text)
    if not key or not text_key:
        return False
    if key == text_key or (len(key) >= 4 and key in text_key):
        return True
    tokens = normalize_lender_name(identity).split()
    if not tokens:
        return False
    available = set(normalize_lender_name(text).split())
    return all(token in available for token in tokens)


def _names(identity: str, cell: str) -> bool:
    """The cell carries (part of) the holder's name."""
    if not _is_text_cell(cell):
        return False
    if identity_in_text(identity, cell):
        return True
    tokens = [token for token in normalize_lender_name(identity).split() if len(token) >= 3]
    available = set(normalize_lender_name(cell).split())
    return any(token in available for token in tokens)


def _class_kind(field: str, class_id: str | None) -> str | None:
    if field == "current_common":
        return "common"
    if field == "current_preferred":
        return "preferred"
    if field in {"count", "issued_total"} and class_id:
        key = class_id.replace("_", " ").casefold()
        if _PREFERRED_LIKE.search(key):
            return "preferred"
        if _COMMON_LIKE.search(key):
            return "common"
    return None


def column_excluded(header: str, field: str, class_id: str | None) -> bool:
    """Whether a column named ``header`` cannot evidence ``field``."""
    key = " ".join(header.casefold().split())
    if not key:
        return False
    if _CERT_LIKE.search(key) or (_NUMBERING.search(key) and not _COUNTING.search(key)):
        return True
    if field in COUNT_FIELDS:
        if _PCT_LIKE.search(key) or _MONEY_LIKE.search(key) or _NOMINAL_LIKE.search(key) or _VOTES_LIKE.search(key):
            return True
        kind = _class_kind(field, class_id)
        if kind == "common" and _PREFERRED_LIKE.search(key):
            return True
        if kind == "preferred" and _COMMON_LIKE.search(key) and not _PREFERRED_LIKE.search(key):
            return True
        return False
    if field == "current_participation_pct":
        return bool(_MONEY_LIKE.search(key) or _NOMINAL_LIKE.search(key) or _VOTES_LIKE.search(key))
    if field == "invested_amount":
        return bool(_PCT_LIKE.search(key) or _VOTES_LIKE.search(key))
    if field == "nominal_value":
        return bool(_PCT_LIKE.search(key) or _MONEY_LIKE.search(key) or _VOTES_LIKE.search(key))
    if field == "votes_per_share":
        return bool(_PCT_LIKE.search(key) or _MONEY_LIKE.search(key) or _NOMINAL_LIKE.search(key))
    return False


class QuoteError(ValueError):
    """The quote does not resolve to source lines."""


@dataclass
class Evidence:
    """Resolved quote of one extracted row."""

    source: Source
    identity: str | None
    scope: str = ROW_SCOPE
    resolved: list[Resolved] = field(default_factory=list)

    @property
    def rows(self) -> list[Resolved]:
        """Table rows that may evidence this row's numbers.

        A holder's rows must each name the holder. A share class or pool is
        described across the rows of one sheet, so once a quoted row of a
        table names it, the other quoted rows of that table count as well.
        """
        if self.identity is None:
            return [item for item in self.resolved if item.is_row]
        named_tables = {item.line.table for item in self.resolved if item.is_row and item.binding}
        return [
            item for item in self.resolved
            if item.is_row and (item.binding or (self.scope != ROW_SCOPE and item.line.table in named_tables))
        ]

    def ignored_rows(self) -> list[SourceLine]:
        """Quoted rows that do not name the holder and were left out."""
        used = {item.line.index for item in self.rows}
        return [item.line for item in self.resolved if item.is_row and item.line.index not in used]

    @property
    def prose(self) -> list[Resolved]:
        return [item for item in self.resolved if item.line.kind == "prose"]

    def identity_found(self) -> bool:
        if self.identity is None:
            return True
        if self.rows or any(self._prose_identified(item) for item in self.prose):
            return True
        # A share class is a column concept: quoting only the header that
        # names it identifies the class (and evidences no number).
        return self.scope == TABLE_SCOPE and not any(item.is_row for item in self.resolved) and any(
            identity_in_text(self.identity, line.text) for line in self.source.lines if line.kind == "header"
        )

    def _prose_identified(self, item: Resolved) -> bool:
        if self.identity is None:
            return True
        if identity_in_text(self.identity, item.passage):
            return True
        return any(
            identity_in_text(self.identity, other.fragment)
            and abs(other.line.index - item.line.index) <= NEARBY_LINES
            for other in self.prose
        )

    def eligible_columns(self, item: Resolved, field: str, class_id: str | None) -> list[int]:
        line = item.line
        columns = list(range(len(line.cells)))
        if item.binding and item.binding[0] == "header" and field in COUNT_FIELDS:
            columns = list(item.binding[1])
        elif line.headers and len(line.headers) == len(line.cells):
            columns = [i for i in columns if not column_excluded(line.headers[i], field, class_id)]
        return columns

    def candidates(self, field: str, class_id: str | None) -> tuple[list[Decimal], list[Decimal], bool]:
        """Numbers stated for this row: single cells, full-column sums, strict flag.

        Strict applies when several quoted rows name the holder and the
        field is additive: a value must then be the sum of one column over
        all of them, or a single cell in a column no other quoted row fills.
        Subsets are never summed.
        """
        rows = self.rows
        per_row = [
            (item, row_values(item.line.cells, field == "current_participation_pct"),
             self.eligible_columns(item, field, class_id))
            for item in rows
        ]
        stating: dict[tuple[int, int], int] = {}
        sums: dict[tuple[int, int], Decimal | None] = {}
        singles: list[Decimal] = []
        for item, per_cell, columns in per_row:
            for column in columns:
                values = per_cell[column]
                if not values:
                    continue
                # OCR merges a figure into the name cell; it is stated there
                # but does not make the name column one to be summed.
                if self.identity and _names(self.identity, item.line.cells[column]):
                    singles.extend(values)
                    continue
                key = (item.line.table, column)
                stating[key] = stating.get(key, 0) + 1
                previous = sums.get(key, Decimal(0))
                sums[key] = None if previous is None or len(values) != 1 else previous + values[0]
        strict = self.identity is not None and field in ADDITIVE_FIELDS and len(rows) >= 2
        for item, per_cell, columns in per_row:
            for column in columns:
                if self.identity and _names(self.identity, item.line.cells[column]):
                    continue
                if not strict or stating.get((item.line.table, column), 0) == 1:
                    singles.extend(per_cell[column])
        totals = [
            total for key, total in sums.items()
            if total is not None and len(rows) >= 2 and stating[key] == len(rows)
        ]
        for item in self.prose:
            if self.identity is None or self._prose_identified(item):
                singles.extend(_prose_numbers(item, field))
        return singles, totals, strict

    def evidenced(self, value: float, field: str, class_id: str | None) -> bool:
        target = Decimal(str(value))
        singles, totals, strict = self.candidates(field, class_id)
        if field in ADDITIVE_FIELDS and any(total == target for total in totals):
            return True
        return any(number == target for number in singles)

    def describe_numbers(self, field: str, class_id: str | None) -> str:
        singles, totals, strict = self.candidates(field, class_id)
        found = _format_numbers(singles)
        if strict:
            return (
                f"the quoted rows for this holder sum to {_format_numbers(totals) or 'no single column'} "
                f"(cells: {found or 'none'}); with several quoted rows a value must be the sum of "
                "one column over all of them, or quote only the row you report"
            )
        if totals:
            return f"the quoted cells state {found or 'no numbers'}; column sums {_format_numbers(totals)}"
        return f"the quoted cells state {found or 'no numbers'}"


def _prose_numbers(item: Resolved, field: str) -> list[Decimal]:
    """Numbers a prose fragment states, restricted to its labelled amount."""
    fragment = item.fragment
    label = _PROSE_LABELS.get(field)
    stated = numbers(fragment)
    if label:
        match = label.search(fragment)
        if match:
            after = numbers(fragment[match.start(): match.start() + 80])
            before = numbers(fragment[max(0, match.start() - 30): match.start()])
            stated = after or before
    in_passage = numbers(item.passage)
    return [number for number in stated if number in in_passage]


def _format_numbers(values: list[Decimal]) -> str:
    seen: list[str] = []
    for value in values:
        text = str(int(value)) if value == value.to_integral_value() else str(value.normalize())
        if text not in seen:
            seen.append(text)
    if len(seen) > 12:
        return ", ".join(seen[:12]) + ", ..."
    return ", ".join(seen)


def resolve_quote(quote: str, source: Source, identity: str | None, scope: str = ROW_SCOPE) -> Evidence:
    """Resolve every fragment of a quote to one source line and bind the identity.

    Raises ``QuoteError`` with a message the model can act on.
    """
    evidence = Evidence(source, identity, scope)
    used: set[int] = set()
    for fragment in _FRAGMENT_SPLIT.split(quote or ""):
        if not fragment.strip() or is_separator_row(fragment):
            continue
        item = _resolve_fragment(fragment, source, identity, used)
        if item.line.kind == "row":
            used.add(item.line.index)
        evidence.resolved.append(item)
    if not evidence.resolved:
        raise QuoteError("quote is missing; quote the source row(s) verbatim")
    if identity is not None:
        name_columns = _name_columns(identity, evidence.resolved, source)
        for item in evidence.resolved:
            if item.is_row:
                item.binding = _bind_identity(identity, item.line, source, name_columns.get(item.line.table), scope)
    return evidence


def _resolve_fragment(fragment: str, source: Source, identity: str | None, used: set[int]) -> Resolved:
    key = normalize_for_matching(fragment)
    if not key:
        raise QuoteError(f"quote fragment {fragment!r} carries no text")
    # Context lines (headers, separators) may be quoted freely and repeatedly.
    for line in source.lines:
        if line.kind == "header" and (source._keys[line.index] == key or _cells_match_row(quote_cells(fragment), line)):
            return Resolved(fragment, line)
    if not _substantial(fragment):
        raise QuoteError(
            f"quote fragment {fragment!r} is too short to identify a source row; "
            "quote the complete row including its name/label"
        )
    table_fragment = is_table_line(fragment) or "|" in fragment
    candidates: list[Resolved] = []
    for line in source.lines:
        if line.kind != "row":
            continue
        if table_fragment and _cells_match_row(quote_cells(fragment), line):
            candidates.append(Resolved(fragment, line))
        elif not table_fragment and key in source._keys[line.index]:
            candidates.append(Resolved(fragment, line))
    prose = [Resolved(fragment, line, passage) for line, passage in source.find_prose(key)]
    if not candidates and not prose:
        closest = source.closest_line(fragment)
        hint = f" The closest source line is {closest!r}." if closest else ""
        raise QuoteError(f"quote fragment {fragment!r} is not found verbatim in the source.{hint}")
    named = [item for item in candidates if identity and identity_in_text(identity, item.line.text)]
    for item in named + [item for item in candidates if item not in named]:
        if item.line.index not in used:
            return item
    if candidates:
        raise QuoteError(
            f"quote repeats the source row {candidates[0].line.text!r}; quote each source row once"
        )
    return prose[0]


def _other_class_filled(identity: str, line: SourceLine) -> bool:
    """The row states a positive figure under a column of the other share class."""
    kind = "preferred" if _PREFERRED_LIKE.search(identity.casefold()) else (
        "common" if _COMMON_LIKE.search(identity.casefold()) else None)
    if kind is None:
        return False
    for header, cell in zip(line.headers, line.cells):
        key = header.casefold()
        other = "preferred" if _PREFERRED_LIKE.search(key) else ("common" if _COMMON_LIKE.search(key) else None)
        if other and other != kind and any(value > 0 for value in cell_values(cell)):
            return True
    return False


def _name_columns(identity: str, resolved: list[Resolved], source: Source) -> dict[int, int | None]:
    """Per table, the column holding names: from a quoted named row, else the header."""
    columns: dict[int, int | None] = {}
    for item in resolved:
        if not item.is_row or item.line.table in columns:
            continue
        for index, cell in enumerate(item.line.cells):
            if _names(identity, cell):
                columns[item.line.table] = index
                break
    for item in resolved:
        if item.is_row and item.line.table not in columns:
            columns[item.line.table] = source.name_column(item.line.table)
    return columns


def _bind_identity(
    identity: str, line: SourceLine, source: Source, name_column: int | None, scope: str
) -> tuple[str, tuple[int, ...]] | None:
    if identity_in_text(identity, line.text):
        return ("row", ())
    owner = source.owner_row(line, name_column)
    if owner is not None and identity_in_text(identity, owner.text):
        return ("owner", ())
    if line.headers and len(line.headers) == len(line.cells):
        named = [i for i, header in enumerate(line.headers) if identity_in_text(identity, header)]
        positive = tuple(
            i for i in named
            if line.cells[i].strip() and any(value > 0 for value in cell_values(line.cells[i]))
        )
        if positive:
            return ("header", positive)
        if named and scope == TABLE_SCOPE and _other_class_filled(identity, line):
            return None   # the row holds the other class; this class is blank on it
    if any(identity_in_text(identity, section.text) for section in source.section_rows(line)):
        return ("section", ())
    if any(identity_in_text(identity, above.text) for above in source.context_above(line.table)):
        return ("context", ())
    if scope == TABLE_SCOPE and any(
        identity_in_text(identity, other.text) for other in source.table_lines(line.table)
    ):
        return ("table", ())
    if scope == DOCUMENT_HEADINGS and any(identity_in_text(identity, heading.text) for heading in source.headings()):
        return ("heading", ())
    return None
