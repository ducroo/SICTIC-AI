import pytest

from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.storage import get_storage
from skills.dd_priorities.dd_priorities import dd_priorities


def _create_startup_dataset(name: str) -> None:
    location = dataset_location_for_domain(name, "startups")
    get_storage().mkdir(location.raw_rel)


@pytest.mark.asyncio
async def test_dd_priorities_synthesizes_saved_dd_checks_report(
    mock_env,
    monkeypatch,
):
    _create_startup_dataset("avientus")
    source = InsightFile("avientus", "dd_checks", "manual")
    source.save(
        "# DD Checks\n\n"
        "| No | Line-Item | Status | Summary | Concerns |\n"
        "|---|---|---|---|---|\n"
        "| 4.1.3 | Cash Position | Not Found | Cash is unverified. | "
        "Can current cash be verified? |\n"
    )
    prompts = []

    async def fake_llm_chat(prompt):
        prompts.append(prompt)
        return (
            "## 1. Unverified liquidity\n"
            "- **Concern type:** Missing information\n"
            "- **DD category:** Financial\n"
            "- **Severity:** High\n"
            "- **Supporting checks:** 4.1.3\n"
            "- **Existing citations:** None\n\n"
            "**Summary:** Current liquidity cannot be verified.\n\n"
            "**Why it matters:** Runway cannot be assessed.\n\n"
            "**Recommended follow-up:** Obtain current bank statements."
        )

    monkeypatch.setattr(
        "skills.dd_priorities.dd_priorities.generate_markdown",
        fake_llm_chat,
    )

    [insight] = await dd_priorities("Avientus")
    path = insight.path

    assert path.startswith("storage/startups/avientus/insights/dd-priorities-")
    # A manual report has no most-important-findings section and is used completely.
    assert "Cash is unverified" in prompts[0]
    assert "up to five" in prompts[0]
    assert "Unverified liquidity" in get_storage().read_text(path)


@pytest.mark.asyncio
async def test_dd_priorities_uses_only_most_important_findings(
    mock_env,
    monkeypatch,
):
    _create_startup_dataset("avientus")
    InsightFile("avientus", "dd_checks", "manual").save(
        "# M&A Due Diligence Checks for Avientus\n\n"
        "**Industry type:** software\n\n"
        "## Most important findings\n\n"
        "| Importance | No | Check | Status |\n"
        "|---|---|---|---|\n"
        "| 9 | 4.1.3 | Cash Position | Critical |\n\n"
        "## Chapter: 1_elevator\n\n"
        "| No | Check | Status | Importance |\n"
        "|---|---|---|---|\n"
        "| 1.1.1 | Pitch deck | Fine | 2 |\n"
    )
    prompts = []

    async def fake_llm_chat(prompt):
        prompts.append(prompt)
        return "## 1. Unverified liquidity"

    monkeypatch.setattr(
        "skills.dd_priorities.dd_priorities.generate_markdown",
        fake_llm_chat,
    )

    await dd_priorities("Avientus")

    assert "| 9 | 4.1.3 | Cash Position | Critical |" in prompts[0]
    assert "Pitch deck" not in prompts[0]


@pytest.mark.asyncio
async def test_dd_priorities_requires_existing_dd_checks_report(mock_env):
    with pytest.raises(ValueError, match="Run /dd_checks missing-startup first"):
        await dd_priorities("missing-startup")


@pytest.mark.asyncio
async def test_dd_priorities_rejects_empty_dd_checks_report(mock_env):
    _create_startup_dataset("avientus")
    InsightFile("avientus", "dd_checks", "manual").save("")

    with pytest.raises(ValueError, match="report for 'avientus' is empty"):
        await dd_priorities("avientus")


@pytest.mark.asyncio
async def test_dd_priorities_resolves_startup_alias(
    mock_env,
    monkeypatch,
):
    _create_startup_dataset("expertvision")
    InsightFile("expertvision", "dd_checks", "manual").save("# DD Checks")

    async def fake_llm_chat(prompt):
        return "No material concerns supported."

    monkeypatch.setattr(
        "skills.dd_priorities.dd_priorities.generate_markdown",
        fake_llm_chat,
    )

    [insight] = await dd_priorities("ExpertVision Ai")
    path = insight.path

    assert path.startswith("storage/startups/expertvision/insights/dd-priorities-")
