import asyncio

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from spike.runtime import review_pitch_deck_upload
from spike.web import create_app, render_page, render_report


def test_page_reviews_a_deck_and_hides_the_skill_picker():
    page = render_page()

    assert "Check your pitch deck" in page
    assert 'type="file"' in page
    assert "Hosting sponsored by Safe Swiss Cloud" in page
    assert 'href="https://safeswisscloud.com/"' in page
    assert "/static/safe-swiss-cloud-logo.svg" in page
    assert "/static/sictic-logo.svg" in page
    assert 'href="https://www.sictic.ch/"' in page
    assert "<select" not in page
    assert 'name="query"' not in page
    assert "Skills" not in page
    assert "We're working on your deck." in page
    assert "1. Receive the deck" in page
    assert "2. Extract the text" in page
    assert "3. Review the deck" in page
    assert "4. Prepare the report" in page
    assert "Elapsed 0:00" in page
    assert 'class="sponsor-logo"' in page
    assert "#4b5563" in page
    assert "/static/review.js" in page
    assert "max-width: 52rem" not in page
    assert "min-width: 42rem" not in page
    assert "table-layout: fixed" in page


def test_report_renderer_marks_status_cells():
    html = render_report(
        "# Pitch deck review\n\n"
        "- Fine. Clear.\n\n"
        "| No | Check | Status |\n"
        "| --- | --- | --- |\n"
        "| 1.1 | Valuation cap | Critical |\n"
    )

    assert "<h1>Pitch deck review</h1>" in html
    assert "<li>Fine. Clear.</li>" in html
    assert 'class="status-critical"' in html
    assert "Valuation cap" in html


def test_report_renderer_keeps_a_quoted_pipe_in_one_cell():
    html = render_report(
        "| No | Check | Status | Where in the deck |\n"
        "| --- | --- | --- | --- |\n"
        "| 1.1 | Customer and revenue | Fine | acme-deck.pdf \\| Page: 1 |\n"
    )

    assert "<td>acme-deck.pdf | Page: 1</td>" in html
    assert "<td>Page: 1</td>" not in html


@pytest.mark.asyncio
async def test_upload_rejects_a_non_deck():
    with pytest.raises(ValueError, match="PDF or PowerPoint"):
        await review_pitch_deck_upload(filename="notes.txt", payload=b"hello")


@pytest.mark.asyncio
async def test_review_form_returns_the_report(mocker):
    async def fake_review(*, filename, payload):
        assert filename == "deck.pdf"
        assert payload == b"%PDF-1.4"
        return "# Pitch deck review\n\n| No | Check | Status |\n| --- | --- | --- |\n| 1.1 | Team | Fine |\n"

    mocker.patch("spike.web.review_pitch_deck_upload", side_effect=fake_review)
    form = FormData()
    form.add_field("deck", b"%PDF-1.4", filename="deck.pdf", content_type="application/pdf")
    app = create_app()
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/review", data=form)
        text = await response.text()
        logo = await client.get("/static/safe-swiss-cloud-logo.svg")
        mark = await client.get("/static/sictic-logo.svg")
        missing = await client.get("/static/not-a-logo.svg")
        logo_body = await logo.read()

    assert response.status == 200
    assert "Review of deck.pdf" in text
    assert 'class="status-fine"' in text
    assert "Hosting sponsored by Safe Swiss Cloud" in text
    assert logo.status == 200
    assert b"<svg" in logo_body
    assert mark.status == 200
    assert missing.status == 404


@pytest.mark.asyncio
async def test_review_start_follows_extract_then_review(mocker):
    async def fake_prepare(files, temp_name="temp"):
        return temp_name

    async def fake_discard(_name):
        return None

    async def fake_skill(_name):
        class Insight:
            def content(self):
                return "report"

        return [Insight()]

    mocker.patch("spike.runtime.prepare_ephemeral_dataset", side_effect=fake_prepare)
    mocker.patch("spike.runtime.discard_ephemeral_dataset", side_effect=fake_discard)
    import importlib
    skill_module = importlib.import_module("skills.pitch_deck_review.pitch_deck_review")
    mocker.patch.object(skill_module, "pitch_deck_review", fake_skill)
    seen = []

    report = await review_pitch_deck_upload(
        filename="deck.pdf",
        payload=b"%PDF-1.4",
        on_progress=seen.append,
    )

    assert report == "report"
    assert seen == ["extract", "review"]


@pytest.mark.asyncio
async def test_review_start_returns_the_same_working_message(mocker):
    async def fake_review(*, filename, payload, on_progress=None):
        if on_progress:
            on_progress("extract")
            on_progress("review")
        return "# Pitch deck review\n\nReady\n"

    mocker.patch("spike.web.review_pitch_deck_upload", side_effect=fake_review)
    form = FormData()
    form.add_field("deck", b"%PDF-1.4", filename="deck.pdf", content_type="application/pdf")
    app = create_app()
    async with TestClient(TestServer(app)) as client:
        started = await client.post("/review/start", data=form)
        body = await started.json()
        assert started.status == 200
        assert body["message"] == "We're working on your deck."
        assert body["steps"][0]["state"] == "current"
        data = body
        for _ in range(30):
            status = await client.get("/review/status/" + body["job_id"])
            data = await status.json()
            if data["done"]:
                break
            await asyncio.sleep(0.02)
        rejected = FormData()
        rejected.add_field("deck", b"notes", filename="notes.txt")
        bad = await client.post("/review/start", data=rejected)
        bad_body = await bad.json()

    assert data["done"] is True
    assert data["error"] == ""
    assert [step["state"] for step in data["steps"]] == ["done", "done", "done", "done"]
    assert "Review of deck.pdf" in data["report_html"]
    assert bad.status == 400
    assert bad_body["error"] == "Upload a PDF or PowerPoint pitch deck."
