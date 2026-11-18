from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from spike.runtime import (
    check_dataroom_upload,
    check_pitch_deck_upload,
    normalize_review_kind,
    review_dataroom_upload,
)


def test_normalize_review_kind_accepts_known_modes():
    assert normalize_review_kind("dataroom") == "dataroom"
    assert normalize_review_kind("pitch-deck") == "pitch_deck"
    assert normalize_review_kind(None) == "pitch_deck"
    with pytest.raises(ValueError, match="pitch deck or data room"):
        normalize_review_kind("memo")


def test_check_dataroom_upload_requires_zip():
    assert check_dataroom_upload("room.zip", b"PK\x03\x04") == "room.zip"
    with pytest.raises(ValueError, match="ZIP"):
        check_dataroom_upload("deck.pdf", b"%PDF")
    with pytest.raises(ValueError, match="PDF or PowerPoint"):
        check_pitch_deck_upload("room.zip", b"PK")


@pytest.mark.asyncio
async def test_review_dataroom_upload_wires_extract_and_skill(monkeypatch):
    extracted = SimpleNamespace(files=("pitch.pdf", "corp/articles.pdf"))

    def fake_extract(payload, destination, **_kwargs):
        assert payload.startswith(b"PK")
        destination.mkdir(parents=True, exist_ok=True)
        for rel in extracted.files:
            path = destination / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"doc")
        return extracted

    prepare = AsyncMock(return_value="dataroom-abc")
    discard = AsyncMock()
    insight = SimpleNamespace(content=lambda: "# Data-room review\n")
    skill = AsyncMock(return_value=[insight])

    monkeypatch.setattr("lib.zip_extract.extract_dataroom_zip", fake_extract)
    monkeypatch.setattr("spike.runtime.prepare_ephemeral_dataset", prepare)
    monkeypatch.setattr("spike.runtime.discard_ephemeral_dataset", discard)
    monkeypatch.setattr(
        "skills.dataroom_review.dataroom_review.dataroom_review",
        skill,
    )

    steps = []
    report = await review_dataroom_upload(
        filename="room.zip",
        payload=b"PK\x03\x04fake",
        on_progress=steps.append,
    )

    assert report.startswith("# Data-room review")
    assert steps == ["extract", "review"]
    assert prepare.await_args.kwargs["relative_paths"] == [
        "pitch.pdf",
        "corp/articles.pdf",
    ]
    discard.assert_awaited_once()
    skill.assert_awaited_once()
