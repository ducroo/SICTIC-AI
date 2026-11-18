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

    [report] = await package.dataroom_review("dataroom-demo")

    assess.assert_awaited_once()
    assert assess.await_args.kwargs["skill_name"] == "dataroom_review"
    assert "**Model:**" not in report.content()
    assert report.content().startswith("# Data-room review")
