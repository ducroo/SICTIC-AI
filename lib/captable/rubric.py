"""Deterministic red-flag rubric over a stored cap-table snapshot.

Handbook-derived heuristics (design §1.4/§1.2), computed in Python; the
LLM narrative layer only phrases what these numbers already say.
"""

from __future__ import annotations

from typing import Any


def _finding(item: str, status: str, severity: str, detail: str) -> dict:
    return {"item": item, "status": status, "severity": severity,
            "detail": detail}


def ownership_by_role(snapshot: dict[str, Any]) -> dict[str, float]:
    """Fully-diluted percentage per role (treasury excluded)."""
    by_role: dict[str, float] = {}
    total = 0.0
    for stakeholder in snapshot.get("stakeholders", []):
        if stakeholder.get("kind") == "treasury":
            continue
        diluted = stakeholder.get("diluted_count")
        if diluted is None:
            diluted = sum(
                h.get("count") or 0.0
                for h in stakeholder.get("holdings", [])
            )
        by_role[stakeholder.get("role", "unknown")] = (
            by_role.get(stakeholder.get("role", "unknown"), 0.0) + diluted
        )
        total += diluted
    if not total:
        return {}
    return {role: 100.0 * count / total for role, count in by_role.items()}


def apply_rubric(snapshot: dict[str, Any]) -> list[dict]:
    findings = []
    pct = ownership_by_role(snapshot)
    founders = pct.get("founder", 0.0)
    investors = pct.get("investor", 0.0)
    departed = pct.get("departed", 0.0)

    if founders and founders < 50:
        findings.append(
            _finding(
                "founder_majority",
                "flag",
                "high",
                f"Founders hold {founders:.1f}% fully diluted (<50% "
                "pre-Series-A is the handbook's 'costly mistakes were "
                "made' signal).",
            )
        )
    else:
        findings.append(
            _finding(
                "founder_majority",
                "ok",
                "info",
                f"Founders hold {founders:.1f}% fully diluted.",
            )
        )

    if founders and investors > 2 * founders:
        findings.append(
            _finding(
                "investor_dominance",
                "flag",
                "high",
                f"Investors ({investors:.1f}%) hold more than twice the "
                f"founders ({founders:.1f}%) — handbook 'giant red flag'.",
            )
        )

    if departed > 10:
        findings.append(
            _finding(
                "dead_equity",
                "flag",
                "high",
                f"Departed holders own {departed:.1f}% fully diluted "
                "(>10% dead-equity threshold).",
            )
        )
    elif departed:
        findings.append(
            _finding(
                "dead_equity",
                "ok",
                "info",
                f"Departed holders own {departed:.1f}% fully diluted.",
            )
        )

    fd_definition = (snapshot.get("fully_diluted_definition") or {}).get(
        "value"
    )
    if fd_definition in (None, "unstated"):
        findings.append(
            _finding(
                "fd_definition",
                "flag",
                "medium",
                "The source does not state which fully-diluted definition "
                "its numbers use (full pools vs granted-only) — clarify "
                "before negotiating a fully-diluted pre-money valuation.",
            )
        )
    return findings
