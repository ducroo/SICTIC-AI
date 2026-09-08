"""Deterministic red-flag rubric over a stored cap-table snapshot.

Handbook-derived heuristics (design §1.4/§1.2), computed in Python; the
LLM narrative layer only phrases what these numbers already say.
"""

from __future__ import annotations

from typing import Any

from lib.infrastructure.configuration import load_repository_config


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


def founder_ownership_pct(snapshot: dict[str, Any]) -> float | None:
    """Unknown founder identity/counts are distinct from evidenced zero shares."""
    founders = [holder for holder in snapshot.get("stakeholders", [])
                if holder.get("role") == "founder" and holder.get("kind") != "treasury"]
    if not founders:
        return None
    for holder in founders:
        if holder.get("diluted_count") is None:
            holdings = holder.get("holdings") or []
            if not holdings or any(h.get("count") is None for h in holdings):
                return None
    return ownership_by_role(snapshot).get("founder")


def apply_rubric(snapshot: dict[str, Any], *, settings: dict | None = None) -> list[dict]:
    settings = load_repository_config("captable")["settings"] if settings is None else settings
    founder_minimum = settings["founder_majority_min_pct"]
    investor_ratio = settings["investor_dominance_ratio"]
    departed_maximum = settings["departed_ownership_max_pct"]
    findings = []
    pct = ownership_by_role(snapshot)
    founders = founder_ownership_pct(snapshot)
    investors = pct.get("investor", 0.0)
    departed = pct.get("departed", 0.0)

    if founders is None:
        findings.append(
            _finding(
                "founder_majority",
                "insufficient_evidence",
                "medium",
                "Founder ownership cannot be assessed: ownership data, usable "
                "share counts or founder-role information is missing. "
                "Missing founder information does not establish 0% ownership.",
            )
        )
    elif founders < founder_minimum:
        findings.append(
            _finding(
                "founder_majority",
                "flag",
                "high",
                f"Founders hold {founders:.1f}% fully diluted (<{founder_minimum:g}% "
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

    if founders is not None and investors > investor_ratio * max(founders, 1e-9):
        findings.append(
            _finding(
                "investor_dominance",
                "flag",
                "high",
                f"Investors ({investors:.1f}%) hold more than {investor_ratio:g} times the "
                f"founders ({founders:.1f}%) — handbook 'giant red flag'.",
            )
        )

    if departed > departed_maximum:
        findings.append(
            _finding(
                "dead_equity",
                "flag",
                "high",
                f"Departed holders own {departed:.1f}% fully diluted "
                f"(>{departed_maximum:g}% dead-equity threshold).",
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
