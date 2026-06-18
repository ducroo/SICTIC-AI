from __future__ import annotations

from dataclasses import dataclass

import pytest

from lib.storage import get_storage
from skills.startup_website_import.startup_website_import import (
    startup_website_import,
)


@dataclass
class FakeResponse:
    text: str = ""
    content: bytes = b""
    headers: dict[str, str] | None = None
    status_code: int = 200

    def __post_init__(self):
        if self.headers is None:
            self.headers = {"content-type": "text/html"}
        if not self.content:
            self.content = self.text.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]):
        self.responses = responses
        self.requested: list[str] = []

    def get(self, url: str, **_kwargs):
        self.requested.append(url)
        if url not in self.responses:
            return FakeResponse(status_code=404)
        return self.responses[url]


def test_startup_website_import_crawls_pages_pdfs_and_link_manifest(mock_env):
    session = FakeSession(
        {
            "https://example.com/robots.txt": FakeResponse(
                "User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain"},
            ),
            "https://example.com/": FakeResponse(
                """
                <html>
                  <head><title>Example Startup</title></head>
                  <body>
                    <h1>Example Startup</h1>
                    <p>Climate intelligence for buildings.</p>
                    <a href="/about">About</a>
                    <a href="/team/">Team</a>
                    <a href="/blog/post">Blog</a>
                    <a href="/broken">Broken</a>
                    <a href="/privacy">Privacy</a>
                    <a href="/files/founder-cv.pdf">Founder CV</a>
                    <a href="https://www.linkedin.com/in/jane-founder/">Jane</a>
                    <p>Advisor: https://ch.linkedin.com/in/advisor-founder?trk=public_profile</p>
                    <a href="https://other.example/page">External</a>
                  </body>
                </html>
                """,
            ),
            "https://example.com/about": FakeResponse(
                "<html><head><title>About</title></head><body><h1>About</h1><p>About text.</p></body></html>",
            ),
            "https://example.com/team/": FakeResponse(
                """
                <html><head><title>Team</title></head><body>
                <h1>Team</h1>
                <p>Meet the team.</p>
                <a href="https://www.linkedin.com/in/john-founder/">John</a>
                <a href="/files/team-bio.pdf">Team bio</a>
                </body></html>
                """,
            ),
            "https://example.com/blog/post": FakeResponse(
                "<html><head><title>News</title></head><body><h1>News</h1><p>Interesting update.</p></body></html>",
            ),
            "https://example.com/files/founder-cv.pdf": FakeResponse(
                content=b"%PDF founder",
                headers={"content-type": "application/pdf"},
            ),
            "https://example.com/files/team-bio.pdf": FakeResponse(
                content=b"%PDF team",
                headers={"content-type": "application/pdf"},
            ),
        }
    )
    storage = get_storage()
    storage.write_text("storage/startups/example/datasets/website/stale.md", "old")

    result = startup_website_import(
        "Example",
        "https://example.com",
        session=session,
        storage=storage,
    )

    assert result.dataset_slug == "example"
    assert result.pages_saved == 4
    assert result.pdfs_saved == 2
    assert result.linkedin_urls_found == 3
    assert result.failed_pages == 1
    assert not storage.exists("storage/startups/example/datasets/__active_dataset__.md")
    assert not storage.exists("storage/startups/example/datasets/website/stale.md")
    assert not storage.exists("cache/startup_website_import/example/website")
    assert storage.exists("storage/startups/example/datasets/website/index.md")
    assert storage.exists("storage/startups/example/datasets/website/about.md")
    assert storage.exists("storage/startups/example/datasets/website/team.md")
    assert storage.exists("storage/startups/example/datasets/website/blog/post.md")
    index_page = storage.read_text("storage/startups/example/datasets/website/index.md")
    index_body = index_page.split("---", 2)[-1]
    assert "[About](" not in index_body
    assert "https://example.com" not in index_body
    assert "linkedin.com/in/jane-founder" not in index_body
    assert "ch.linkedin.com/in/advisor-founder" not in index_body
    assert storage.read_bytes(
        "storage/startups/example/datasets/website/pdfs/founder-cv.pdf"
    ) == b"%PDF founder"
    assert storage.read_bytes(
        "storage/startups/example/datasets/website/pdfs/team-bio.pdf"
    ) == b"%PDF team"

    manifest = storage.read_text(
        "storage/startups/example/datasets/website/linkedin-and-resume-links.md"
    )
    assert "https://www.linkedin.com/in/jane-founder/" in manifest
    assert "https://www.linkedin.com/in/john-founder/" in manifest
    assert "possible resume/CV" in manifest
    linkedin_urls = storage.read_text(
        "storage/startups/example/datasets/website/linkedin-urls.md"
    )
    assert result.linkedin_urls_path == "storage/startups/example/datasets/website/linkedin-urls.md"
    assert "count: 3" in linkedin_urls
    assert "https://www.linkedin.com/in/jane-founder/" in linkedin_urls
    assert "https://www.linkedin.com/in/john-founder/" in linkedin_urls
    assert "https://ch.linkedin.com/in/advisor-founder/" in linkedin_urls
    assert "?trk=" not in linkedin_urls
    assert "https://example.com/privacy" not in session.requested


def test_startup_website_import_can_disable_pdfs_and_depth(mock_env):
    session = FakeSession(
        {
            "https://example.com/robots.txt": FakeResponse(
                "User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain"},
            ),
            "https://example.com/": FakeResponse(
                """
                <html><head><title>Home</title></head><body>
                <a href="/about">About</a>
                <a href="/deck.pdf">Deck</a>
                </body></html>
                """,
            ),
            "https://example.com/about": FakeResponse(
                "<html><head><title>About</title></head><body><p>About</p></body></html>",
            ),
            "https://example.com/deck.pdf": FakeResponse(
                content=b"%PDF deck",
                headers={"content-type": "application/pdf"},
            ),
        }
    )

    result = startup_website_import(
        "Example",
        "https://example.com",
        depth=0,
        include_pdfs=False,
        session=session,
        storage=get_storage(),
    )

    storage = get_storage()
    assert result.pages_saved == 1
    assert result.pdfs_saved == 0
    assert storage.exists("storage/startups/example/datasets/website/index.md")
    assert not storage.exists("storage/startups/example/datasets/website/about.md")
    assert not storage.exists("storage/startups/example/datasets/website/pdfs/deck.pdf")


def test_startup_website_import_preserves_existing_website_when_no_pages_saved(mock_env):
    session = FakeSession(
        {
            "https://example.com/robots.txt": FakeResponse(
                "User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain"},
            ),
            "https://example.com/": FakeResponse(status_code=500),
        }
    )
    storage = get_storage()
    storage.write_text("storage/startups/example/datasets/website/stale.md", "old")

    with pytest.raises(RuntimeError, match="saved no HTML pages"):
        startup_website_import(
            "Example",
            "https://example.com",
            session=session,
            storage=storage,
        )

    assert storage.read_text("storage/startups/example/datasets/website/stale.md") == "old"
    assert not storage.exists("cache/startup_website_import/example/website")


def test_startup_website_import_keeps_colliding_paths_distinct(mock_env):
    session = FakeSession(
        {
            "https://example.com/robots.txt": FakeResponse(
                "User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain"},
            ),
            "https://example.com/": FakeResponse(
                """
                <html><head><title>Home</title></head><body>
                <a href="/about">About plain</a>
                <a href="/about/">About slash</a>
                <a href="/files/deck.pdf">Deck A</a>
                <a href="/other/deck.pdf">Deck B</a>
                </body></html>
                """,
            ),
            "https://example.com/about": FakeResponse(
                "<html><head><title>About A</title></head><body><p>A</p></body></html>",
            ),
            "https://example.com/about/": FakeResponse(
                "<html><head><title>About B</title></head><body><p>B</p></body></html>",
            ),
            "https://example.com/files/deck.pdf": FakeResponse(
                content=b"%PDF deck a",
                headers={"content-type": "application/pdf"},
            ),
            "https://example.com/other/deck.pdf": FakeResponse(
                content=b"%PDF deck b",
                headers={"content-type": "application/pdf"},
            ),
        }
    )

    result = startup_website_import(
        "Example",
        "https://example.com",
        session=session,
        storage=get_storage(),
    )

    storage = get_storage()
    website_files = storage.list_with_mtime(
        "storage/startups/example/datasets/website",
        recursive=True,
    )
    names = {name for name, _mtime in website_files}

    assert result.pages_saved == 3
    assert result.pdfs_saved == 2
    assert "about.md" in names
    assert any(name.startswith("about-") and name.endswith(".md") for name in names)
    assert "pdfs/deck.pdf" in names
    assert any(name.startswith("pdfs/deck-") and name.endswith(".pdf") for name in names)
