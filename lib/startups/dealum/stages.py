"""Dealum stage labels used by bulk refresh eligibility and skill selection."""

ALWAYS_ACTIVE_STAGES = frozenset({
    "Under Review", "Jury", "Pitching", "Jury reserves (for pitching)",
})
INACTIVITY_STAGES = frozenset({
    "Application", "Rejected by Jury", "Rejected for other reason",
    "Not selected to pitch",
})
PITCHED_STAGE = "Pitched @ SICTIC"
RESEARCH_STAGES = frozenset({"Jury", "Pitching", "Jury reserves (for pitching)", PITCHED_STAGE})
KNOWN_STAGES = ALWAYS_ACTIVE_STAGES | INACTIVITY_STAGES | {PITCHED_STAGE}


def canonical_stage(value: str | None) -> str:
    normalized = " ".join(str(value or "").split()).casefold()
    for stage in KNOWN_STAGES:
        if stage.casefold() == normalized:
            return stage
    raise ValueError(f"Unknown or missing Dealum stage: {value!r}")
