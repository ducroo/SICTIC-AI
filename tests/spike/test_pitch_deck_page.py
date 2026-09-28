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
