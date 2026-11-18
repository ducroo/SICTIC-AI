from unittest.mock import AsyncMock

import pytest

from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.storage import get_storage


@pytest.mark.asyncio
async def test_dataroom_review_requires_dataset(mock_env, monkeypatch):
    from skills.dataroom_review import dataroom_review as package

    monkeypatch.setattr(
        "skills.dataroom_review.dataroom_review.find_dataset_location",
        lambda _name: None,
    )
    with pytest.raises(FileNotFoundError, match="was not found"):
        await package.dataroom_review("missing-room")


@pytest.mark.asyncio
async def test_dataroom_review_uses_assess_dd_dataset(mock_env, monkeypatch):
    from skills.dataroom_review import dataroom_review as package

    location = dataset_location_for_domain("dataroom-demo", "generated")
    get_storage().mkdir(location.raw_rel)
    monkeypatch.setattr(
        "skills.dataroom_review.dataroom_review.find_dataset_location",
        lambda _name: location,
    )
    insight = InsightFile("dataroom-demo", "dataroom_review", "manual")
    insight.save(
        "# Data-room review\n\n**Product type:** general\n\n**Model:** x\n\n## Chapter\nDone\n"
    )
    assess = AsyncMock(return_value=[insight])
    monkeypatch.setattr(
        "skills.dataroom_review.dataroom_review.assess_dd_dataset",
        assess,
    )
    monkeypatch.setattr(
        "skills.dataroom_review.dataroom_review.format_ignored_documents_section",
        lambda _slug: "",
    )

    [report] = await package.dataroom_review("dataroom-demo")

    assess.assert_awaited_once()
    assert assess.await_args.kwargs["skill_name"] == "dataroom_review"
    assert "**Model:**" not in report.content()
    assert report.content().startswith("# Data-room review")


@pytest.mark.asyncio
async def test_dataroom_review_lists_unreadable_documents(mock_env, monkeypatch):
    from skills.dataroom_review import dataroom_review as package

    location = dataset_location_for_domain("dataroom-demo", "generated")
    get_storage().mkdir(location.raw_rel)
    monkeypatch.setattr(
        "skills.dataroom_review.dataroom_review.find_dataset_location",
        lambda _name: location,
    )
    insight = InsightFile("dataroom-demo", "dataroom_review", "manual")
    insight.save("# Data-room review\n\n**Product type:** general\n\n## Chapter\nDone\n")
    assess = AsyncMock(return_value=[insight])
    monkeypatch.setattr(
        "skills.dataroom_review.dataroom_review.assess_dd_dataset",
        assess,
    )
    monkeypatch.setattr(
        "skills.dataroom_review.dataroom_review.format_ignored_documents_section",
        lambda _slug: (
            "## Documents that could not be processed\n\n"
            "| Document | Reason |\n"
            "| --- | --- |\n"
            "| `bad.pptx` | PowerPoint file is not valid for conversion "
            "(often empty or missing slides). |\n"
        ),
    )

    [report] = await package.dataroom_review("dataroom-demo")

    text = report.content()
    assert "## Documents that could not be processed" in text
    assert "`bad.pptx`" in text
    assert text.index("Documents that could not be processed") < text.index(
        "**Product type:**"
    )
