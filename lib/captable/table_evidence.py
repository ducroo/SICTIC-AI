"""Conservative source-row and column evidence for table extraction.

Formatting tolerance must not turn unrelated source cells into evidence.
Ambiguous tables require a better quote or an unstated value, not guessing.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import re

from lib.captable.documents import normalize_for_matching
from lib.markdown_tables import is_table_line, parse_table, split_cells


# These are column meanings, not thresholds or configurable review bands.
_HEADERS = {
    "current_common": r"common(?: shares| issued)?|shares|stammaktien|aktien",
    "current_preferred": r"preferred(?: [a-z])?(?: shares| issued)?|vorzugsaktien",
    "current_participation_pct": r"participation|ownership(?: %)?|anteil(?: %)?",
    "diluted_count": r"(?:fully )?diluted(?: shares| count)?",
    "diluted_total": r"(?:fully )?diluted(?: shares| total)?",
    "nominal_value": r"nominal(?: value)?(?: \([a-z]+\))?|nennwert",
    "votes_per_share": r"votes per share|votes|stimmen pro aktie",
    "invested_amount": r"investment(?: \([a-z]+\))?|invested amount|amount \([a-z]+\)",
    "total": r"total(?: pool| shares)?|pool size",
    "granted": r"granted(?: shares)?|allocated",
    "unallocated": r"unallocated(?: shares)?|available|remaining",
}
_ZERO = {"-", "–", "—", "none", "nil", "keine"}


def numbers(text: str) -> list[Decimal]:
    """Preserve occurrences; repair grouped numerals within a single cell only."""
    text = re.sub(r"(?<=\d)[ \u00a0\u202f]*['’][ \u00a0\u202f]*(\d[ \u00a0\u202f]*\d[ \u00a0\u202f]*\d)(?!\d)",
                  lambda m: re.sub(r"\s", "", m[1]), text)
    text = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?:\D|$))", "", text)
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


def _identity_matches(identity: str, cell: str) -> bool:
    # Retain source wording, allowing a location following a comma. Do not
    # assemble names from tokens elsewhere in a row/table/document.
    return normalize_for_matching(identity) in {
        normalize_for_matching(cell), normalize_for_matching(cell.split(",", 1)[0])
    }


@dataclass
class SourceRow:
    text: str
    cells: list[str]
    headers: list[str]
    owner: str | None
    index: int


def source_rows(document: str) -> list[SourceRow]:
    result: list[SourceRow] = []
    pending: list[str] = []

    def flush():
        if not pending:
            return
        table = parse_table(pending)
        # Header inference is for layout, not proof: an inferred line with
        # amounts may be an ordinary data row (especially a one-row table).
        if table.header and any(numbers(c) for c in split_cells(table.header)):
            table = replace(table, rows=list(pending), header="")
        headers = split_cells(table.header) if table.header else []
        owner_index = next((i for i, h in enumerate(headers) if re.fullmatch(
            r"no\.?", h.strip(), re.I) is None and re.search(
            r"holder|name|group|label|pool|aktionär", h, re.I)), None)
        owner = None
        for line in table.rows:
            cells = split_cells(line)
            if len(cells) != len(headers) and headers:
                owner = None
            elif owner_index is not None and cells[owner_index].strip():
                owner = cells[owner_index]
            result.append(SourceRow(line, cells, headers, owner, len(result)))
        # Headers may be quoted separately, but never supply numeric evidence.
        for context in (table.header, table.separator):
            if context:
                result.append(SourceRow(context, [], headers, None, len(result)))
        pending.clear()

    for line in document.splitlines():
        if is_table_line(line):
            pending.append(line)
        elif re.fullmatch(r"\s*<!--\s*page\s*:\s*\d+\s*-->\s*", line):
            continue
        else:
            flush()
            if line.strip():
                result.append(SourceRow(line, [line], [], None, len(result)))
    flush()
    return result


def quoted_rows(quote: str, rows: list[SourceRow], identity: str | None,
                share_class: str | None = None) -> list[SourceRow]:
    """Resolve whole source lines; ellipses may only separate complete lines.

    Repeated quotes cannot duplicate a certificate. Identical source lines
    remain distinct occurrences when they are quoted that many times.
    """
    selected = []
    used: set[int] = set()
    for fragment in re.split(r"\r?\n|\.\.\.|…", quote):
        if not fragment.strip():
            continue
        # Preserve cell boundaries while tolerating whitespace and punctuation
        # inside cells using the shared source-matching normalization.
        fragment_cells = split_cells(fragment) if is_table_line(fragment) else [fragment]
        candidates = [row for row in rows if len(fragment_cells) == len(row.cells)
                      and all(normalize_for_matching(a) == normalize_for_matching(b)
                              for a, b in zip(fragment_cells, row.cells))]
        # A separately quoted header has no numeric cells.
        if any(normalize_for_matching(fragment) == normalize_for_matching(row.text)
               and not row.cells for row in rows):
            continue
        if not candidates:
            raise ValueError("quote must contain complete source rows with their original columns")
        if identity and share_class is not None:
            # Class definitions may be supplied by a labelled class column
            # and the nominal value on a holder row, rather than their own row.
            candidates = [row for row in candidates if any(_identity_matches(identity, c) for c in row.cells) or any(
                _column(h, "count", share_class) and i < len(row.cells)
                and any(n > 0 for n in numbers(row.cells[i]))
                for i, h in enumerate(row.headers)
            ) or (not row.headers and re.search(
                rf"\b{re.escape(identity)}\b", row.text, re.I))]
        elif identity:
            candidates = [row for row in candidates if (
                _identity_matches(identity, row.owner) if row.owner is not None
                else any(_identity_matches(identity, c) for c in row.cells)
                or (len(row.cells) == 1 and re.match(
                    rf"^{re.escape(identity)}\b", row.text.strip(), re.I))) ]
        if not candidates:
            # Verified rows for another holder/category may explain context,
            # but cannot supply numbers for this holder. At least one matching
            # source row is still required below.
            continue
        candidate = next((row for row in candidates if row.index not in used), None)
        if candidate is None:
            raise ValueError("quote must contain complete source rows for this holder/label; include its header and merged-cell context")
        used.add(candidate.index)
        selected.append(candidate)
    if not selected:
        raise ValueError("quote has no source rows for this holder/label")
    return selected


def _column(header: str, field: str, class_id: str | None) -> bool:
    header = re.sub(r"\s+", " ", header.strip().casefold())
    if field in {"count", "issued_total"}:
        if not class_id:
            return False
        kind = class_id.replace("_", " ").replace("-", " ").casefold()
        return header in {kind, f"{kind} shares", f"{kind} issued"} or (
            kind == "common" and header == "shares")
    return bool(re.fullmatch(_HEADERS.get(field, r"(?!)"), header))


def field_evidenced(value: float, field: str, class_id: str | None,
                    rows: list[SourceRow], identity: str | None, pool_kind: str | None = None) -> bool:
    target = Decimal(str(value))
    operands: list[Decimal] = []
    can_sum = field in {"current_common", "current_preferred", "count", "issued_total"}
    for row in rows:
        if not row.cells:
            continue
        if row.headers:
            if len(row.headers) != len(row.cells):
                return False
            columns = [i for i, h in enumerate(row.headers) if _column(h, field, class_id)]
            if not columns and field == "unallocated" and pool_kind == "grantable":
                columns = [i for i, h in enumerate(row.headers) if _column(h, "diluted_count", None)]
            if not columns and field == "total":
                if pool_kind in {"grantable", "authorized_capital", "esop", "psop"}:
                    columns = [i for i, h in enumerate(row.headers) if _column(h, "diluted_count", None)]
                elif pool_kind == "treasury":
                    columns = [i for i, h in enumerate(row.headers) if re.fullmatch(
                        r"(?:common|preferred(?: [a-z]+)?) issued", h.strip(), re.I)
                        and row.cells[i].strip()]
            if len(columns) != 1:
                continue
            cell = row.cells[columns[0]].strip()
            # A blank is unknown. Only an explicit zero marker in the selected
            # column supports zero; n/a is not zero either.
            if cell.casefold() in _ZERO:
                parsed = [Decimal(0)]
            else:
                parsed = numbers(cell)
            if len(parsed) != 1:
                return False
            operands.append(parsed[0])
        else:
            # Without a column header do not derive totals or implicit zeros.
            # Retain literal evidence in an unambiguous single-value passage.
            cells = [c for c in row.cells if not identity or not _identity_matches(identity, c)]
            parsed = [number for c in cells for number in numbers(c)]
            if len(rows) == 1 and len(parsed) == 1 and parsed[0] == target:
                return True
            # Prose can state several quantities. Accept an explicitly
            # labelled single amount, never their sum or concatenation.
            pattern = _HEADERS.get(field)
            if pattern:
                for cell in cells:
                    match = re.search(
                        rf"(?:{pattern})\s*(?:of\s+|is\s+|:\s*)?"
                        r"(?:CHF\s*|EUR\s*|USD\s*)?([+-]?\d+(?:[.,]\d+)*)",
                        cell, re.I,
                    )
                    if match and numbers(match[1]) == [target]:
                        return True
    if not operands:
        return False
    # Sum every selected holding line, preserving repeated values. Never try
    # arbitrary subsets, column combinations, or sums for non-additive fields.
    if can_sum and len(operands) > 1:
        return sum(operands) == target
    return any(number == target for number in operands)
