"""Render capitalization facts and scenario numbers without model rewriting."""
from __future__ import annotations

from html import escape

from lib.captable.data import render_data_markdown


def _cell(value) -> str:
    if value is None:
        return "—"
    return escape(str(value)).replace("|", "\\|").replace("\n", " ")


def _table(headers, rows) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return "\n".join(lines)


def render_report(data: dict, computed: dict, narrative: str) -> str:
    sections = [render_data_markdown(data).rstrip(),
        "## Ownership by role",
        _table(["Role", "Current ownership (%)"], computed["ownership_by_role_today"].items()),
        "## Share classes",
        _table(["Class", "Name", "Nominal value", "Votes per share"], [
            (c.get("id"), c.get("name"), c.get("nominal_value"), c.get("votes_per_share"))
            for c in data.get("share_classes", [])]),
        "## Pools",
        _table(["Pool", "Kind", "Total", "Granted", "Unallocated"], [
            (p.get("label"), p.get("kind"), p.get("total"), p.get("granted"), p.get("unallocated"))
            for p in data.get("pools", [])]),
        "## Sources",
        _table(["Document", "Class", "Source date"], [
            (s.get("doc"), s.get("class"), s.get("date")) for s in data.get("sources", [])]),
        "## Conversion scenarios",
        f"Analysis date: {_cell(computed['valuation_date'])}. Currency: {_cell(computed['currency'])}.",
        _table(["Hypothetical round input", "Amount"], computed["hypothetical_round"].items()),
        _table(["Method", "Round price per share", "Founders after round (%)"], [
            (s["method"], s["price_per_share"], s["founders_post_round_pct"])
            for s in computed["scenarios"]]),
        _table(["Method", "Holder", "Ownership after round (%)"], [
            (s["method"], holder, pct) for s in computed["scenarios"]
            for holder, pct in s["ownership_pct"].items()]),
        _table(["Method", "Loan", "Conversion price per share"], [
            (s["method"], loan, price) for s in computed["scenarios"]
            for loan, price in s["note_conversion_prices"].items()]),
        "## Accrued loan balances",
        _table(["Loan", "Currency", "Balance"], [
            (loan, computed["note_currencies"][loan], balance)
            for loan, balance in computed["note_balances"].items()]),
        "## Fixed maturity conversion",
        _table(["Document", "Currency", "Price per share", "Implied shares", "Implied company value"], [
            (m["document"], m["currency"], m["price_per_share"], m["implied_shares_at_balance"], m["implied_company_value_at_price"])
            for m in computed["maturity_conversion_at_fixed_price"]]),
        "## Stamp duty",
        _table(["Measure", "Value"], computed["stamp_duty"].items()),
        "## Findings",
        computed["rubric_scope_note"],
        _table(["Finding", "Status", "Severity", "Detail"], [
            (f["item"], f["status"], f["severity"], f["detail"])
            for f in computed["rubric"] + computed["scenario_flags"]]),
        "## Loan maturity and execution evidence",
        _table(["Document", "Maturity date", "Status", "Detail"], [
            (m.get("document"), m.get("maturity_date"), m.get("status"), m.get("detail"))
            for m in (data.get("aggregation") or {}).get("maturity", [])]),
        _table(["Document", "Signatures claimed complete", "Corroboration"], [
            (e.get("document"), e.get("signatures_complete_claimed"), e.get("corroborated"))
            for e in (data.get("aggregation") or {}).get("esignature", [])]),
        "## Loan term assessments",
        _table(["Document", "Term", "Status", "Severity", "Detail"], [
            (a["document"], f.get("item"), f.get("status"), f.get("severity"), f.get("detail"))
            for a in data.get("assessment", []) for f in a.get("findings", [])]),
        "## Scenario assumptions and warnings",
        "\n".join("- " + _cell(note) for note in computed["assumptions"] + [
            f"{s['method']}: {warning}" for s in computed["scenarios"] for warning in s["warnings"]]),
        "## Commentary", narrative.strip(),
    ]
    return "\n\n".join(sections) + "\n"
