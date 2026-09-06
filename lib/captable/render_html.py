"""Deterministic HTML one-pager over a stored cap-table snapshot.

Pure Python over the snapshot JSON (plus, optionally, the computed
analysis scenarios): no LLM call, no clock, no external resources. The
point is that the visual a reviewer actually looks at carries exactly the
snapshot's numbers — the division-of-labor rule extended to the last
mile. Percentages use the same denominator as ``rubric.ownership_by_role``
(fully diluted, treasury excluded) so the chart can never disagree with
the analysis output.
"""

from __future__ import annotations

from html import escape
from typing import Any

from lib.captable.snapshot import _fmt

_ROLE_ORDER = ("founder", "investor", "employee", "departed")
_ROLE_COLORS = {
    "founder": "#2563eb",
    "investor": "#d97706",
    "employee": "#059669",
    "departed": "#dc2626",
}
_FALLBACK_COLORS = ("#7c3aed", "#0891b2", "#be185d", "#4d7c0f", "#64748b")
_SEVERITY_COLORS = {
    "info": "#64748b",
    "medium": "#d97706",
    "high": "#dc2626",
    "severe": "#7f1d1d",
}
_STATUS_COLORS = {
    "pass": "#059669",
    "ok": "#059669",
    "warn": "#d97706",
    "flag": "#dc2626",
    "fail": "#dc2626",
    "executed": "#059669",
    "term_sheet": "#d97706",
    "converted": "#64748b",
    "repaid": "#64748b",
    "active": "#059669",
    "expired_check_for_conversion": "#dc2626",
}


def _value(entry: Any) -> Any:
    if isinstance(entry, dict) and "value" in entry:
        return entry["value"]
    return entry


def _badge(text: Any, color: str = "#64748b") -> str:
    return (
        f'<span class="badge" style="background:{color}">'
        f"{escape(str(text))}</span>"
    )


def _severity_badge(severity: Any) -> str:
    return _badge(severity, _SEVERITY_COLORS.get(str(severity), "#64748b"))


def _status_badge(status: Any) -> str:
    return _badge(status, _STATUS_COLORS.get(str(status), "#64748b"))


def _role_color_map(roles: set[str]) -> dict[str, str]:
    """One color per role, identical in the bar, legend, and table."""
    colors = dict(_ROLE_COLORS)
    for index, role in enumerate(sorted(roles - set(_ROLE_COLORS))):
        colors[role] = _FALLBACK_COLORS[index % len(_FALLBACK_COLORS)]
    return colors


def _diluted_count(stakeholder: dict) -> float:
    diluted = stakeholder.get("diluted_count")
    if diluted is None:
        diluted = sum(
            h.get("count") or 0.0 for h in stakeholder.get("holdings", [])
        )
    return diluted or 0.0


def _diluted_denominator(snapshot: dict) -> float:
    """Same denominator as ``rubric.ownership_by_role``."""
    return sum(
        _diluted_count(s)
        for s in snapshot.get("stakeholders", [])
        if s.get("kind") != "treasury"
    )


def _sorted_roles(pct: dict[str, float]) -> list[str]:
    known = [r for r in _ROLE_ORDER if r in pct]
    other = sorted(r for r in pct if r not in _ROLE_ORDER)
    return known + other


def _ownership_bar(pct: dict[str, float], colors: dict[str, str]) -> str:
    if not pct:
        return "<p class='muted'>No holder data extracted.</p>"
    segments, legend = [], []
    for role in _sorted_roles(pct):
        share = pct[role]
        color = colors.get(role, "#64748b")
        segments.append(
            f'<div class="seg" title="{escape(role)}: {share:.1f}%" '
            f'style="width:{share:.2f}%;background:{color}"></div>'
        )
        legend.append(
            f'<span><i style="background:{color}"></i>'
            f"{escape(role)} {share:.1f}%</span>"
        )
    return (
        f'<div class="bar">{"".join(segments)}</div>'
        f'<div class="legend">{" ".join(legend)}</div>'
    )


def _holders_table(snapshot: dict, colors: dict[str, str]) -> str:
    stakeholders = snapshot.get("stakeholders", [])
    if not stakeholders:
        return "<p class='muted'>No holder data extracted.</p>"
    denominator = _diluted_denominator(snapshot)
    rows = []
    ordered = sorted(
        stakeholders,
        key=lambda s: (-_diluted_count(s), str(s.get("name", ""))),
    )
    for s in ordered:
        role = str(s.get("role", "unknown"))
        kind = s.get("kind")
        treasury = kind == "treasury"
        diluted = _diluted_count(s)
        issued = sum(h.get("count") or 0.0 for h in s.get("holdings", []))
        classes = ", ".join(
            f"{escape(str(h.get('class_id')))} {_fmt(h.get('count'))}"
            for h in s.get("holdings", [])
        )
        pct = (
            "excluded"
            if treasury
            else (f"{100.0 * diluted / denominator:.2f}%" if denominator
                  else "")
        )
        rows.append(
            f'<tr{" class=\"treasury\"" if treasury else ""}>'
            f"<td>{escape(str(s.get('name', '')))}"
            + (
                f" <span class='muted'>({escape(str(s.get('group')))})</span>"
                if s.get("group")
                else ""
            )
            + "</td>"
            f"<td>{_badge(role, colors.get(role, '#64748b'))}"
            + (f" {_badge(kind, '#334155')}" if kind not in
               (None, "person") else "")
            + "</td>"
            f"<td>{escape(classes)}</td>"
            f'<td class="num">{_fmt(issued)}</td>'
            f'<td class="num">{_fmt(diluted)}</td>'
            f'<td class="num">{escape(pct)}</td></tr>'
        )
    return (
        "<table><thead><tr><th>Holder</th><th>Classification</th>"
        "<th>Holdings by class</th><th>Issued</th><th>Fully diluted</th>"
        "<th>% FD</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _classes_section(snapshot: dict) -> str:
    classes = snapshot.get("share_classes", [])
    totals = snapshot.get("totals") or {}
    issued_by_class = {
        t.get("class_id"): t.get("issued_total")
        for t in totals.get("by_class", [])
    }
    rows = [
        "<tr>"
        f"<td>{escape(str(c.get('id', '')))}</td>"
        f"<td>{escape(str(c.get('name') or ''))}</td>"
        f'<td class="num">{_fmt(c.get("nominal_value"))}</td>'
        f'<td class="num">{_fmt(c.get("votes_per_share"))}</td>'
        f'<td class="num">{_fmt(issued_by_class.get(c.get("id")))}</td>'
        "</tr>"
        for c in classes
    ]
    for class_id, issued in issued_by_class.items():
        if not any(c.get("id") == class_id for c in classes):
            rows.append(
                f"<tr><td>{escape(str(class_id))}</td><td></td><td></td>"
                f'<td></td><td class="num">{_fmt(issued)}</td></tr>'
            )
    fd_definition = _value(snapshot.get("fully_diluted_definition")) or (
        "unstated"
    )
    return (
        "<table><thead><tr><th>Class</th><th>Name</th><th>Nominal</th>"
        "<th>Votes</th><th>Issued</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        f"<p>Fully diluted total (stated): "
        f"<strong>{_fmt(totals.get('diluted_total'))}</strong> · "
        f"FD definition: {escape(str(fd_definition))}</p>"
    )


def _pools_table(snapshot: dict) -> str:
    pools = snapshot.get("pools", [])
    if not pools:
        return "<p class='muted'>No pools in the cap table.</p>"
    rows = [
        "<tr>"
        f"<td>{escape(str(p.get('label') or ''))}</td>"
        f"<td>{_badge(p.get('kind', ''), '#334155')}</td>"
        f'<td class="num">{_fmt(p.get("total"))}</td>'
        f'<td class="num">{_fmt(p.get("granted"))}</td>'
        f'<td class="num">{_fmt(p.get("unallocated"))}</td>'
        "</tr>"
        for p in pools
    ]
    return (
        "<table><thead><tr><th>Pool</th><th>Kind</th><th>Total</th>"
        "<th>Granted</th><th>Unallocated</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _cla_section(snapshot: dict) -> str:
    convertibles = snapshot.get("convertibles", [])
    aggregation = snapshot.get("aggregation") or {}
    if not convertibles:
        return "<p class='muted'>No convertible loans found.</p>"
    maturity_by_doc = {
        f.get("document"): f for f in aggregation.get("maturity", [])
    }
    esign_by_doc = {
        e.get("document"): e for e in aggregation.get("esignature", [])
    }
    severity_by_doc = {
        a.get("document"): a.get("worst_severity")
        for a in snapshot.get("assessment", [])
    }
    rows = []
    for cla in convertibles:
        document = cla.get("document")
        lenders = ", ".join(
            str(_value(lender.get("name")) or "?")
            for lender in cla.get("lenders", [])
        )
        maturity = maturity_by_doc.get(document, {})
        maturity_cell = escape(
            str(maturity.get("maturity_date")
                or _value(cla.get("maturity_date")) or "")
        )
        if maturity.get("status"):
            maturity_cell += " " + _status_badge(maturity["status"])
        esign = esign_by_doc.get(document, {})
        corroborated = esign.get("corroborated")
        esign_cell = (
            ""
            if corroborated is None
            else _status_badge(
                {True: "corroborated", False: "no markers"}.get(
                    corroborated, corroborated
                )
            )
        )
        severity = severity_by_doc.get(document)
        rows.append(
            "<tr>"
            f"<td>{escape(str(document))}</td>"
            f"<td>{_status_badge(cla.get('status'))}</td>"
            f"<td>{escape(lenders)}</td>"
            f'<td class="num">{_fmt(_value(cla.get("principal_total")))} '
            f"{escape(str(_value(cla.get('currency')) or ''))}</td>"
            f'<td class="num">{_fmt(_value(cla.get("interest_rate_pct")))}'
            "</td>"
            f"<td>{maturity_cell}</td>"
            f'<td class="num">{_fmt(_value(cla.get("discount_pct")))}</td>'
            f'<td class="num">{_fmt(_value(cla.get("valuation_cap")))}</td>'
            f"<td>{_severity_badge(severity) if severity else ''}</td>"
            f"<td>{esign_cell}</td></tr>"
        )
    ten_twenty = aggregation.get("ten_twenty_rule") or {}
    summary = (
        f"<p>Outstanding principal (executed): <strong>"
        f"{_fmt(aggregation.get('outstanding_principal_total'))}</strong>"
        + (
            f" · {aggregation.get('outstanding_unknown_amounts')} "
            "loan(s) with undisclosed amount"
            if aggregation.get("outstanding_unknown_amounts")
            else ""
        )
        + f" · 10-rule {escape(str(ten_twenty.get('ten_rule', '?')))} "
        f"(max {_fmt(ten_twenty.get('max_lenders_on_identical_terms'))} "
        "lenders on identical terms) · 20-rule "
        f"{escape(str(ten_twenty.get('twenty_rule', '?')))} "
        f"({_fmt(ten_twenty.get('total_lenders_all_terms'))} lenders "
        "total)</p>"
    )
    return (
        "<table><thead><tr><th>Document</th><th>Status</th><th>Lenders</th>"
        "<th>Principal</th><th>Rate %</th><th>Maturity</th><th>Disc. %</th>"
        "<th>Cap</th><th>Assessment</th><th>E-sign</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>" + summary
    )


def _scenarios_section(
    analysis: dict | None, note: str | None = None
) -> str:
    if not analysis or not analysis.get("scenarios"):
        if note:
            return f"<p class='muted'>{escape(note)}</p>"
        return (
            "<p class='muted'>No computed scenarios stored — run "
            "<code>captable_analysis</code> and re-render to include "
            "them.</p>"
        )
    hypothetical = analysis.get("hypothetical_round") or {}
    rows = [
        "<tr>"
        f"<td>{escape(str(s.get('method')))}</td>"
        f'<td class="num">{_fmt(s.get("price_per_share"))}</td>'
        f'<td class="num">{_fmt(s.get("founders_post_round_pct"))}%</td>'
        f"<td>{'; '.join(escape(str(w)) for w in s.get('warnings', []))}"
        "</td></tr>"
        for s in analysis["scenarios"]
    ]
    flags = "".join(
        f"<p>{_severity_badge(f.get('severity'))} "
        f"{escape(str(f.get('detail')))}</p>"
        for f in analysis.get("scenario_flags", [])
    )
    stamp = analysis.get("stamp_duty") or {}
    return (
        "<p>Hypothetical round: pre-money "
        f"{_fmt(hypothetical.get('pre_money'))}"
        f", investment {_fmt(hypothetical.get('investment'))} "
        f"(computed {escape(str(analysis.get('valuation_date', '')))}; "
        "all defaults are recorded as assumptions).</p>"
        "<table><thead><tr><th>Conversion method</th><th>Price/share</th>"
        "<th>Founders post-round</th><th>Warnings</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        + flags
        + (
            f"<p>Stamp duty estimate: {_fmt(stamp.get('estimate_chf'))} CHF "
            f"(exemption remaining "
            f"{_fmt(stamp.get('exemption_remaining_chf'))} CHF).</p>"
            if stamp and stamp.get("estimate_chf") is not None
            else f"<p class='muted'>Stamp duty: {escape(str(stamp.get('note')))}</p>"
            if stamp
            else ""
        )
    )


def _validation_table(snapshot: dict) -> str:
    validation = snapshot.get("validation", [])
    if not validation:
        return "<p class='muted'>No validation results.</p>"
    rows = [
        "<tr>"
        f"<td>{escape(str(v.get('check')))}</td>"
        f"<td>{_status_badge(v.get('status'))}</td>"
        f"<td>{_severity_badge(v.get('severity'))}</td>"
        f"<td>{escape(str(v.get('detail') or ''))}</td></tr>"
        for v in validation
    ]
    return (
        "<table><thead><tr><th>Check</th><th>Status</th><th>Severity</th>"
        "<th>Detail</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _sources_table(snapshot: dict) -> str:
    sources = snapshot.get("sources", [])
    rows = [
        "<tr>"
        f"<td>{escape(str(s.get('doc')))}</td>"
        f"<td>{_badge(s.get('class', ''), '#334155')}</td>"
        f"<td>{escape(str(s.get('date') or ''))}</td></tr>"
        for s in sorted(
            sources,
            key=lambda s: (str(s.get("class")), str(s.get("doc"))),
        )
    ]
    return (
        "<table><thead><tr><th>Document</th><th>Classified as</th>"
        "<th>Date</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _list_section(items: list, empty_text: str) -> str:
    if not items:
        return f"<p class='muted'>{escape(empty_text)}</p>"
    return (
        "<ul>"
        + "".join(f"<li>{escape(str(item))}</li>" for item in items)
        + "</ul>"
    )


_CSS = """
body{font:14px/1.5 -apple-system,'Segoe UI',sans-serif;color:#1e293b;
  background:#f8fafc;margin:0;padding:24px;max-width:1100px;margin:auto}
h1{font-size:22px;margin:0 0 2px}h2{font-size:15px;margin:28px 0 8px;
  border-bottom:1px solid #e2e8f0;padding-bottom:4px}
table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}
th,td{border:1px solid #e2e8f0;padding:5px 8px;text-align:left;
  vertical-align:top}th{background:#f1f5f9}
td.num{text-align:right;font-variant-numeric:tabular-nums;
  white-space:nowrap}
.badge{color:#fff;border-radius:3px;padding:1px 6px;font-size:11px;
  white-space:nowrap}
.bar{display:flex;height:26px;border-radius:4px;overflow:hidden;
  background:#e2e8f0}.seg{height:100%}
.legend{margin-top:6px;font-size:12px}
.legend span{margin-right:14px}.legend i{display:inline-block;width:10px;
  height:10px;border-radius:2px;margin-right:4px}
.muted{color:#64748b}tr.treasury td{color:#94a3b8}
.meta{color:#64748b;font-size:12px;margin-bottom:18px}
details{margin-top:6px}summary{cursor:pointer;color:#475569}
"""


def render_html(
    snapshot: dict[str, Any],
    analysis: dict[str, Any] | None = None,
    *,
    scenarios_note: str | None = None,
) -> str:
    """Render the snapshot (and optional computed analysis) as one HTML page.

    Deterministic: same inputs produce byte-identical output.
    ``scenarios_note`` replaces the default "no scenarios" text, e.g. to
    say that stored scenarios were skipped as stale.
    """
    pct = {}
    denominator = _diluted_denominator(snapshot)
    if denominator:
        for s in snapshot.get("stakeholders", []):
            if s.get("kind") == "treasury":
                continue
            role = str(s.get("role", "unknown"))
            pct[role] = pct.get(role, 0.0) + (
                100.0 * _diluted_count(s) / denominator
            )
    colors = _role_color_map(
        {str(s.get("role", "unknown"))
         for s in snapshot.get("stakeholders", [])}
    )
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>Cap table — {escape(str(snapshot.get('dataset', '')))}"
        "</title>",
        f"<style>{_CSS}</style></head><body>",
        f"<h1>Cap table — {escape(str(snapshot.get('dataset', '')))}</h1>",
        "<p class='meta'>As of "
        f"{escape(str(snapshot.get('as_of_date', '?')))} · generated "
        f"{escape(str(snapshot.get('generated_at', ''))[:10])} · "
        f"{escape(str(snapshot.get('tool_version', '')))} · every number "
        "on this page is copied verbatim from the validated snapshot; "
        "percentages are computed in code.</p>",
        "<h2>Ownership by role (fully diluted, treasury excluded)</h2>",
        _ownership_bar(pct, colors),
        "<h2>Holders</h2>",
        _holders_table(snapshot, colors),
        "<h2>Share classes</h2>",
        _classes_section(snapshot),
        "<h2>Pools</h2>",
        _pools_table(snapshot),
        "<h2>Convertible loans</h2>",
        _cla_section(snapshot),
        "<h2>Conversion scenarios</h2>",
        _scenarios_section(analysis, scenarios_note),
        "<h2>Validation</h2>",
        _validation_table(snapshot),
        "<h2>Diligence questions</h2>",
        _list_section(
            snapshot.get("diligence_questions", []),
            "No open diligence questions.",
        ),
        "<details><summary>Assumptions ("
        f"{len(snapshot.get('assumptions', []))})</summary>",
        _list_section(snapshot.get("assumptions", []), "None."),
        "</details>",
        "<details><summary>Source documents ("
        f"{len(snapshot.get('sources', []))})</summary>",
        _sources_table(snapshot),
        "</details>",
        "</body></html>",
    ]
    return "".join(parts)
