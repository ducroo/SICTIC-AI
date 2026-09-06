"""Stage 7: assemble and render the versioned cap-table snapshot.

Versioning semantics per design §2.3: one snapshot per evidenced as-of
date under ``insights/captable/snapshots/``, all kept forever, plus
``latest.json`` and a table-only ``captable.md`` (narrative belongs to
``captable_analysis``, not here).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

TOOL_VERSION = "captable_build/0.3"


def snapshot_fingerprint(snapshot: dict[str, Any]) -> str:
    """Content hash of a snapshot, ignoring only the generation timestamp.

    Two snapshots with the same as-of date can describe different states
    (a corrected rebuild); derived artifacts such as the computed scenarios
    must be matched on this fingerprint, never on the date alone. A
    bit-identical rebuild keeps the fingerprint (and its scenarios) valid.
    """
    content = {
        key: value for key, value in snapshot.items() if key != "generated_at"
    }
    canonical = json.dumps(
        content, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

_MONTHS = {
    month.lower(): index
    for index, month in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"],
        start=1,
    )
}


def normalize_iso_date(value: str | None) -> str | None:
    """Normalize model-extracted date strings to ISO (YYYY[-MM[-DD]]).

    Handles "2026-06-30", "30 June 2026", "June 30, 2026", "30.06.2026",
    "2026-06", "2026". Returns the input unchanged when unparseable —
    callers treat that as evidence to keep, not to discard.
    """
    if not value:
        return value
    text = value.strip()
    if re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", text):
        return text
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if match:
        day, month, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    match = re.fullmatch(r"(\d{1,2})\.?\s+([A-Za-zä]+)\s+(\d{4})", text)
    if match and match.group(2).lower() in _MONTHS:
        day, month_name, year = match.groups()
        return f"{year}-{_MONTHS[month_name.lower()]:02d}-{int(day):02d}"
    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", text)
    if match and match.group(1).lower() in _MONTHS:
        month_name, day, year = match.groups()
        return f"{year}-{_MONTHS[month_name.lower()]:02d}-{int(day):02d}"
    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", text)
    if match and match.group(1).lower() in _MONTHS:
        month_name, year = match.groups()
        return f"{year}-{_MONTHS[month_name.lower()]:02d}"
    return value


def resolve_as_of(
    captable: dict | None,
    classification: dict,
    source_documents: list[str],
) -> tuple[str, list[str]]:
    """Best-evidence as-of date plus the assumptions that derivation makes."""
    assumptions = []
    stated = normalize_iso_date(
        ((captable or {}).get("as_of_date") or {}).get("value")
    )
    if stated:
        return stated, assumptions
    dates = [
        normalized
        for entry in classification.get("documents", [])
        if entry.get("filename") in source_documents and entry.get("as_of_date")
        for normalized in [normalize_iso_date(entry.get("as_of_date"))]
        # only ISO-shaped dates may compete: an unparseable string starting
        # with a letter would lexicographically beat every real date
        if normalized and re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", normalized)
    ]
    if dates:
        best = max(dates)
        assumptions.append(
            "as_of_date derived from document/filename dates during "
            f"classification (best evidence: {best}); no source document "
            "states its own as-of date."
        )
        return best, assumptions
    today = datetime.now(timezone.utc).date().isoformat()
    assumptions.append(
        f"No as-of evidence found in any source; using run date {today}."
    )
    return today, assumptions


def assemble_snapshot(
    dataset: str,
    *,
    classification: dict,
    captable: dict | None,
    register: dict | None,
    pool_docs: list[dict],
    cla_extraction: dict,
    assessment: dict,
    aggregation: dict,
    validation: list[dict],
) -> dict[str, Any]:
    source_documents = [d for d in [
        (captable or {}).get("document"),
        (register or {}).get("document"),
        *[p.get("document") for p in pool_docs],
        *[c.get("document") for c in cla_extraction.get("clas", [])],
    ] if d]
    as_of, as_of_assumptions = resolve_as_of(
        captable, classification, source_documents
    )
    assumptions = list(as_of_assumptions)
    for source in (captable, register, *pool_docs):
        for note in (source or {}).get("assumptions", []):
            assumptions.append(f"{(source or {}).get('document')}: {note}")

    return {
        "dataset": dataset,
        "as_of_date": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool_version": TOOL_VERSION,
        "sources": [
            {
                "doc": entry.get("filename"),
                "class": entry.get("document_class"),
                "date": entry.get("as_of_date"),
            }
            for entry in classification.get("documents", [])
        ],
        "share_classes": (captable or {}).get("share_classes", []),
        "stakeholders": (captable or {}).get("stakeholders", []),
        "pools": (captable or {}).get("pools", []),
        "totals": (captable or {}).get("totals", {}),
        "fully_diluted_definition": (captable or {}).get(
            "fully_diluted_definition", {}
        ),
        "register": register,
        "pool_documents": pool_docs,
        "convertibles": cla_extraction.get("clas", []),
        "convertible_failures": cla_extraction.get("failures", []),
        "aggregation": aggregation,
        "assessment": assessment.get("assessments", []),
        "validation": validation,
        "assumptions": assumptions,
        "diligence_questions": aggregation.get("diligence_questions", []),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return f"{int(value):,}"
    if isinstance(value, (int, float)):
        return f"{value:,}"
    return str(value)


def render_markdown(snapshot: dict[str, Any]) -> str:
    """Table-only human summary; narrative belongs to captable_analysis."""
    lines = [
        f"# Cap table snapshot — {snapshot['dataset']}",
        "",
        f"*As of {snapshot['as_of_date']} · generated "
        f"{snapshot['generated_at'][:10]} · {snapshot['tool_version']}*",
        "",
        "## Ownership (extracted holders)",
        "",
        "| Holder | Group | Role | Issued | Diluted |",
        "|---|---|---|---:|---:|",
    ]
    for s in snapshot.get("stakeholders", []):
        issued = sum(h.get("count") or 0 for h in s.get("holdings", []))
        lines.append(
            f"| {s.get('name')} | {s.get('group') or ''} | "
            f"{s.get('role')} | {_fmt(issued)} | "
            f"{_fmt(s.get('diluted_count'))} |"
        )
    totals = snapshot.get("totals") or {}
    lines += ["", "## Totals", "", "| Class | Issued |", "|---|---:|"]
    for t in totals.get("by_class", []):
        lines.append(
            f"| {t.get('class_id')} | {_fmt(t.get('issued_total'))} |"
        )
    lines.append(f"| fully diluted | {_fmt(totals.get('diluted_total'))} |")

    lines += [
        "",
        "## Convertible loans",
        "",
        "| Document | Status | Lenders | Principal | Maturity | Discount |"
        " Cap |",
        "|---|---|---|---:|---|---:|---:|",
    ]
    for cla in snapshot.get("convertibles", []):
        def val(field):
            entry = cla.get(field)
            return entry.get("value") if isinstance(entry, dict) else entry
        lines.append(
            f"| {cla.get('document')} | {cla.get('status')} | "
            f"{len(cla.get('lenders', []))} | "
            f"{_fmt(val('principal_total'))} | "
            f"{val('maturity_date') or ''} | "
            f"{_fmt(val('discount_pct'))} | {_fmt(val('valuation_cap'))} |"
        )

    aggregation = snapshot.get("aggregation") or {}
    ten_twenty = aggregation.get("ten_twenty_rule") or {}
    lines += [
        "",
        "## Aggregation",
        "",
        "- Outstanding principal (executed only): "
        + (
            f"{_fmt(aggregation.get('outstanding_principal_total'))}"
            + (
                f" {aggregation['outstanding_principal_currency']}"
                if aggregation.get("outstanding_principal_currency")
                else ""
            )
            if aggregation.get("outstanding_principal_total") is not None
            else "no consolidated total — mixed currencies: "
            + ", ".join(
                f"{code} {_fmt(total)}"
                for code, total in sorted(
                    (aggregation.get("outstanding_principal_by_currency")
                     or {}).items()
                )
            )
        ),
        f"- Lenders on identical terms (max group): "
        f"{ten_twenty.get('max_lenders_on_identical_terms')} "
        f"({ten_twenty.get('ten_rule')} 10-rule); total lenders "
        f"{ten_twenty.get('total_lenders_all_terms')} "
        f"({ten_twenty.get('twenty_rule')} 20-rule)",
    ]

    lines += ["", "## Assessment", "",
              "| Document | Worst severity |", "|---|---|"]
    for a in snapshot.get("assessment", []):
        lines.append(
            f"| {a.get('document')} | {a.get('worst_severity')} |"
        )

    lines += ["", "## Validation", "",
              "| Check | Status | Severity | Detail |", "|---|---|---|---|"]
    for v in snapshot.get("validation", []):
        lines.append(
            f"| {v.get('check')} | {v.get('status')} | {v.get('severity')} "
            f"| {v.get('detail')} |"
        )

    lines += ["", "## Diligence questions", ""]
    for q in snapshot.get("diligence_questions", []):
        lines.append(f"- {q}")
    lines += ["", "## Assumptions", ""]
    for a in snapshot.get("assumptions", []):
        lines.append(f"- {a}")
    lines.append("")
    return "\n".join(lines)
