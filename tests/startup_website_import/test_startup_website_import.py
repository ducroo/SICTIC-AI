from __future__ import annotations

from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind

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
    url: str = ""

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


@pytest.mark.parametrize("url", ["https://www.amazon.in/book/dp/123", "https://smile.amazon.co.uk/", "https://amzn.to/book"])
def test_marketplace_input_is_skipped_without_fetching(mock_env, url):
    session = FakeSession({})
    result = startup_website_import("SPDYO", url, session=session)
    assert result.skipped_reason == "Marketplace URL is not a company website"
    assert not session.requested
    assert not get_storage().exists(result.website_path)


@pytest.mark.parametrize("target", ["https://abbey.io/blog/", "https://www.amazon.in/", "https://example.com.attacker.test/"])
def test_unapproved_homepage_redirect_is_not_saved_or_crawled(mock_env, target):
    session = FakeSession({"https://example.com/": FakeResponse(
        "<h1>Unrelated</h1><a href='/about'>About</a>", url=target)})
    with pytest.raises(InfrastructureError):
        startup_website_import("Example", "https://example.com", session=session, respect_robots=False)
    assert session.requested == ["https://example.com/"]
    storage = get_storage()
    assert not storage.exists("storage/startups/example/datasets/website")
    assert not any(".website-staging-" in name for name in storage.list("storage/startups/example/datasets"))


@pytest.mark.parametrize("target", ["https://www.example.com/", "https://example.com/"])
def test_canonical_redirect_still_crawls(mock_env, target):
    session = FakeSession({
        "http://example.com/": FakeResponse("<h1>Example</h1><a href='/about'>About</a>", url=target),
        target + "about": FakeResponse("<h1>About Example</h1>"),
    })
    result = startup_website_import("Example", "http://example.com", session=session, respect_robots=False)
    assert result.pages_saved == 2
    assert target + "about" in session.requested


def test_subpage_and_document_redirects_are_checked(mock_env):
    session = FakeSession({
        "https://example.com/": FakeResponse("<h1>Example</h1><a href='/news'>News</a><a href='/deck.pdf'>Deck</a>"),
        "https://example.com/news": FakeResponse("<h1>Other</h1>", url="https://unrelated.test/"),
        "https://example.com/deck.pdf": FakeResponse(content=b"%PDF-1.7 bad", url="https://unrelated.test/deck.pdf"),
    })
    result = startup_website_import("Example", "https://example.com", session=session, respect_robots=False)
    assert result.pages_saved == 1
    assert result.documents_saved == 0
    assert result.failed_pages == 2


@pytest.mark.parametrize("heading", ["KOITOTO Slot Gacor Slot777", "Online Casino — Free Spins Bonus"])
def test_gambling_landing_page_is_rejected(mock_env, heading):
    session = FakeSession({"https://example.com/": FakeResponse(
        f"<title>{heading}</title><h1>{heading}</h1><a href='/register-now'>Play</a>")})
    with pytest.raises(InfrastructureError):
        startup_website_import("Example", "https://example.com", session=session, respect_robots=False)
    assert session.requested == ["https://example.com/"]
    assert not get_storage().exists("storage/startups/example/datasets/website")


def test_spam_footer_removed_before_link_discovery_and_crawling(mock_env):
    company = "Alchimist Grid connects land, air and sea transportation with intelligent fleet monitoring and fuel governance."
    session = FakeSession({"https://example.com/": FakeResponse(f"""
        <title>Alchimist Grid</title><h1>Alchimist Grid</h1><p>{company}</p>
        <footer><p>Copyright Alchimist Grid</p><a href='/slot777'>Play</a>
        <a href='https://linkedin.com/in/spam/'>badak88</a><p>slot gacor</p></footer>
        <a href='https://linkedin.com/in/real-founder/'>Founder</a>
    """)})
    result = startup_website_import("Alchimist Grid", "https://example.com", session=session, respect_robots=False)
    storage = get_storage()
    text = storage.read_text(result.website_path + "/index.md")
    assert company in text
    assert "Copyright Alchimist Grid" in text
    assert "gacor" not in text and "badak88" not in text and "Play" not in text
    assert session.requested == ["https://example.com/"]
    links = storage.read_text(result.linkedin_urls_path)
    assert "/spam/" not in links and "/real-founder/" in links


def test_legitimate_gambling_references_are_preserved(mock_env):
    body = "We provide fraud prevention for online casinos. Our terms prohibit illegal gambling and bonus abuse."
    session = FakeSession({"https://example.com/": FakeResponse(f"<title>AML Compliance</title><h1>Risk controls</h1><p>{body}</p>")})
    result = startup_website_import("Example", "https://example.com", session=session, respect_robots=False)
    assert body in get_storage().read_text(result.website_path + "/index.md")


def test_explicit_verified_redirect_mapping():
    from skills.startup_website_import.validation import redirect_allowed
    policy = {"approved_redirect_hosts": {"old.example": ["new.example"]}}
    assert redirect_allowed("https://old.example", "https://new.example/team", policy)
    assert not redirect_allowed("https://old.example", "https://unrelated.example", policy)


def test_spam_dominated_body_is_rejected_without_gambling_title():
    from lib.infrastructure.configuration import load_repository_config
    from skills.startup_website_import.validation import screen_html
    policy = load_repository_config("startup_website_import", "content_policy")
    assert screen_html("<h1>Welcome</h1><p>slot gacor</p><a href='/slot777'>Play</a>", policy)[0] is None


def test_bare_spam_footer_removed_but_long_mixed_passage_is_not_rewritten():
    from lib.infrastructure.configuration import load_repository_config
    from skills.startup_website_import.validation import screen_html
    policy = load_repository_config("startup_website_import", "content_policy")
    company = "<h1>Alchimist Grid</h1><p>Intelligent monitoring for land, air and sea transportation, with fuel governance and compliance reporting.</p>"
    footer = "badak88 dazbet rajajp88 hokigacor slot88 slot777 slot gacor idnslot mawar88 badak88"
    cleaned, reason = screen_html(company + f"<footer>{footer}</footer>", policy)
    assert cleaned is not None and "Alchimist Grid" in cleaned
    assert "badak88" not in cleaned and "Removed" in reason
    assert screen_html(company + "<p>This is a long mixed passage with slot gacor plus unrelated ordinary words that cannot be safely separated.</p>", policy)[0] is None


def test_amazon_host_check_uses_domain_boundaries():
    from lib.startups.website import excluded_company_website
    assert not excluded_company_website("https://amazonian.example/")
    assert not excluded_company_website("https://aws.amazon.com.example/")


def test_verified_redirect_reloads_destination_robots(mock_env, mocker):
    from lib.infrastructure.configuration import load_repository_config
    policy = dict(load_repository_config("startup_website_import", "content_policy"))
    policy["approved_redirect_hosts"] = {"example.com": ["new.example"]}
    def config(*sections):
        return policy if sections[-1] == "content_policy" else load_repository_config(*sections)
    mocker.patch("skills.startup_website_import.startup_website_import.load_repository_config", side_effect=config)
    session = FakeSession({
        "https://example.com/robots.txt": FakeResponse("User-agent: *\nAllow: /\n"),
        "https://example.com/": FakeResponse("<h1>Example moved</h1><a href='/private'>Private</a>", url="https://new.example/"),
        "https://new.example/robots.txt": FakeResponse("User-agent: *\nDisallow: /private\n"),
    })
    result = startup_website_import("Example", "https://example.com", session=session)
    assert result.pages_saved == 1
    assert "https://new.example/robots.txt" in session.requested
    assert "https://new.example/private" not in session.requested


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
                content=b"%PDF-1.7 founder",
                headers={"content-type": "application/pdf"},
            ),
            "https://example.com/files/team-bio.pdf": FakeResponse(
                content=b"%PDF-1.7 team",
                headers={"content-type": "application/pdf"},
            ),
        }
    )
    storage = get_storage()

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
    ) == b"%PDF-1.7 founder"
    assert storage.read_bytes(
        "storage/startups/example/datasets/website/pdfs/team-bio.pdf"
    ) == b"%PDF-1.7 team"

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
                content=b"%PDF-1.7 deck",
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


def test_startup_website_import_preserves_other_sources_when_no_pages_saved(mock_env):
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
    storage.write_text("storage/startups/example/datasets/data-room/existing.md", "old")

    with pytest.raises(InfrastructureError, match="saved no HTML pages") as caught:
        startup_website_import(
            "Example",
            "https://example.com",
            session=session,
            storage=storage,
        )

    assert isinstance(caught.value, RuntimeError)
    assert caught.value.provider == "website"
    assert caught.value.kind == InfrastructureErrorKind.SERVICE_UNAVAILABLE
    assert storage.read_text("storage/startups/example/datasets/data-room/existing.md") == "old"
    assert not storage.exists("cache/startup_website_import/example/website")


@pytest.mark.parametrize("url", [None, "https://example.com", "https://different.example"])
def test_existing_snapshot_never_scraped_again(mock_env, url):
    storage = get_storage()
    path = "storage/startups/example/datasets/website/index.md"
    storage.write_text(path, "Original snapshot")
    before = storage.mtime(path)
    session = FakeSession({})
    result = startup_website_import("Example", url, session=session, storage=storage)
    assert result.skipped_reason == "Website already imported"
    assert result.pages_saved == 0
    assert session.requested == []
    assert storage.read_text(path) == "Original snapshot"
    assert storage.mtime(path) == before


def test_optional_url_uses_documented_website_then_reuses_snapshot(mock_env):
    storage = get_storage()
    storage.write_text("storage/startups/example/datasets/application.md", "Website: https://example.com")
    session = FakeSession({"https://example.com/": FakeResponse("<h1>Example</h1>")})
    result = startup_website_import("Example", session=session, respect_robots=False)
    assert result.pages_saved == 1
    assert session.requested == ["https://example.com/"]
    second = startup_website_import("Example", session=session, respect_robots=False)
    assert second.skipped_reason == "Website already imported"
    assert session.requested == ["https://example.com/"]


def test_missing_or_ambiguous_url_does_not_guess(mock_env):
    storage = get_storage()
    session = FakeSession({})
    result = startup_website_import("Example", session=session)
    assert result.skipped_reason == "No unambiguous documented website"
    storage.write_text("storage/startups/example/datasets/application.md",
                       "Website: https://one.example\nWebsite: https://two.example")
    result = startup_website_import("Example", session=session)
    assert result.skipped_reason == "No unambiguous documented website"
    assert session.requested == []


def test_cli_accepts_startup_without_url_and_reports_skip(mock_env):
    from typer.testing import CliRunner
    from skills.startup_website_import.__main__ import app
    get_storage().write_text("storage/startups/example/datasets/website/index.md", "Saved page")
    result = CliRunner().invoke(app, ["Example"])
    assert result.exit_code == 0
    assert "Website already imported" in result.output


def test_snapshot_check_precedes_url_resolution_and_option_validation(mock_env, mocker):
    storage = get_storage()
    storage.write_text("storage/startups/example/datasets/website/index.md", "Saved")
    config = mocker.patch("skills.startup_website_import.startup_website_import.load_repository_config")
    result = startup_website_import("Example", "invalid", depth=-1, max_pages=0)
    assert result.skipped_reason == "Website already imported"
    config.assert_not_called()


def test_concurrent_calls_only_scrape_once(mock_env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    started, release = Event(), Event()

    class BlockingSession(FakeSession):
        def get(self, url, **kwargs):
            started.set()
            assert release.wait(5)
            return super().get(url, **kwargs)

    session = BlockingSession({"https://example.com/": FakeResponse("<h1>Example</h1>")})
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(startup_website_import, "Example", "https://example.com",
                                session=session, respect_robots=False)
        assert started.wait(5)
        second = executor.submit(startup_website_import, "Example", "https://example.com",
                                 session=session, respect_robots=False)
        release.set()
        assert first.result().pages_saved == 1
        assert second.result().skipped_reason == "Website already imported"
    assert session.requested == ["https://example.com/"]


def test_failed_publication_leaves_no_partial_snapshot_and_can_retry(mock_env, mocker):
    import importlib
    module = importlib.import_module("skills.startup_website_import.startup_website_import")
    session = FakeSession({"https://example.com/": FakeResponse("<h1>Example</h1>")})
    publish = mocker.patch.object(module, "replace_directory_snapshot", side_effect=OSError("disk error"))
    with pytest.raises(OSError, match="disk error"):
        startup_website_import("Example", "https://example.com", session=session, respect_robots=False)
    assert not get_storage().exists("storage/startups/example/datasets/website")
    mocker.stop(publish)
    assert startup_website_import("Example", "https://example.com", session=session, respect_robots=False).pages_saved == 1


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
                content=b"%PDF-1.7 deck a",
                headers={"content-type": "application/pdf"},
            ),
            "https://example.com/other/deck.pdf": FakeResponse(
                content=b"%PDF-1.7 deck b",
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


def test_redirected_pdf_to_homepage_is_not_saved_as_pdf(mock_env):
    home = "<h1>Home</h1><a href='/old.pdf'>Old deck</a>"
    session = FakeSession({
        "https://example.com/": FakeResponse(home),
        "https://example.com/old.pdf": FakeResponse(home, url="https://example.com/"),
    })
    result = startup_website_import("Example", "https://example.com", session=session,
                                    respect_robots=False)
    assert result.pages_saved == 1
    assert result.documents_saved == 0
    assert not get_storage().exists("storage/startups/example/datasets/website/pdfs/old.pdf")
    assert session.requested.count("https://example.com/old.pdf") == 1


def test_html_download_uses_final_url_and_follows_relative_links(mock_env):
    session = FakeSession({
        "https://example.com/": FakeResponse("<h1>Home</h1><a href='/old.pdf'>Team</a>"),
        "https://example.com/old.pdf": FakeResponse(
            "<h1>Team</h1><a href='bio.docx'>Bio</a>",
            headers={"content-type": "application/pdf"}, url="https://example.com/team/",
        ),
        "https://example.com/team/bio.docx": FakeResponse(content=b"%PDF-1.7\nBio"),
    })
    result = startup_website_import("Example", "https://example.com", session=session,
                                    respect_robots=False)
    storage = get_storage()
    root = "storage/startups/example/datasets/website"
    assert result.pages_saved == 2
    assert result.pdfs_saved == result.documents_saved == 1
    assert "source_url: https://example.com/team/" in storage.read_text(f"{root}/team.md")
    assert storage.read_bytes(f"{root}/pdfs/bio.pdf").startswith(b"%PDF-")
    assert not storage.exists(f"{root}/pdfs/old.pdf")


def test_supported_downloads_use_detected_extensions(mock_env):
    import io
    import zipfile

    office = io.BytesIO()
    with zipfile.ZipFile(office, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    session = FakeSession({
        "https://example.com/": FakeResponse(
            "<h1>Home</h1><a href='/bio.pdf'>Bio</a><a href='/download'>Deck</a>"
            "<a href='/team.csv'>Team</a><a href='/bad.xlsx'>Bad</a>"
        ),
        "https://example.com/bio.pdf": FakeResponse(content=office.getvalue()),
        "https://example.com/download": FakeResponse(content=b"%PDF-1.7\nDeck"),
        "https://example.com/team.csv": FakeResponse(content=b"Name,Role\nJane,Founder\n"),
        "https://example.com/bad.xlsx": FakeResponse(content=b"PK\x03\x04broken"),
    })
    result = startup_website_import("Example", "https://example.com", session=session,
                                    respect_robots=False)
    root = "storage/startups/example/datasets/website"
    storage = get_storage()
    assert result.documents_saved == 3
    assert result.pdfs_saved == 1
    assert result.failed_pages == 1
    assert storage.read_bytes(f"{root}/documents/bio.docx") == office.getvalue()
    assert storage.exists(f"{root}/documents/team.csv")
    assert storage.exists(f"{root}/pdfs/download.pdf")
    assert not storage.exists(f"{root}/documents/bad.xlsx")
    manifest = storage.read_text(f"{root}/linkedin-and-resume-links.md")
    assert "documents/bio.docx" in manifest
    assert "bad.xlsx" not in manifest
    assert all(session.requested.count(url) == 1 for url in session.responses)


@pytest.mark.parametrize("options", [
    {"max_documents": 1}, {"max_pdfs": 1},
])
def test_download_limit_is_shared_across_document_types(mock_env, options):
    session = FakeSession({
        "https://example.com/": FakeResponse(
            "<h1>Home</h1><a href='/a.txt'>Text</a><a href='/b.pdf'>PDF</a>"),
        "https://example.com/a.txt": FakeResponse(content=b"Company notes"),
        "https://example.com/b.pdf": FakeResponse(content=b"%PDF-1.7\nDeck"),
    })
    result = startup_website_import("Example", "https://example.com", session=session,
                                    respect_robots=False, max_pages=1, **options)
    assert result.documents_saved == 1
    assert "https://example.com/b.pdf" not in session.requested


@pytest.mark.parametrize("flag", ["--no-documents", "--no-pdfs"])
def test_cli_supports_document_and_legacy_flags(mock_env, mocker, flag):
    from typer.testing import CliRunner
    from skills.startup_website_import.__main__ import app

    session = FakeSession({"https://example.com/": FakeResponse(
        "<h1>Home</h1><a href='/bio.docx'>Bio</a><a href='/deck.pdf'>Deck</a>",
    )})
    mocker.patch("skills.startup_website_import.startup_website_import.requests.Session",
                 return_value=session)
    result = CliRunner().invoke(app, ["Example", "https://example.com", flag, "--ignore-robots"])
    assert result.exit_code == 0, result.output
    assert "DOCUMENTS: 0" in result.output
    assert session.requested == ["https://example.com/"]


def test_oversized_document_is_skipped_and_later_document_is_saved(mock_env):
    session = FakeSession({
        "https://example.com/": FakeResponse(
            "<h1>Home</h1><a href='/huge.pdf'>Large</a><a href='/small.txt'>Small</a>"),
        "https://example.com/huge.pdf": FakeResponse(content=b"%PDF-1.7\n" + b"x" * 1024 * 1024),
        "https://example.com/small.txt": FakeResponse(content=b"Company notes"),
    })
    result = startup_website_import("Example", "https://example.com", session=session,
                                    respect_robots=False, max_document_mb=1, max_documents=1)
    assert result.failed_pages == 1
    assert result.documents_saved == 1
    assert result.pdfs_saved == 0


def test_declared_html_encoding_is_preserved_in_markdown(mock_env):
    session = FakeSession({"https://example.com/": FakeResponse(
        content=b"<h1>Z\xfcrich</h1>", headers={"content-type": "text/html; charset=iso-8859-1"},
    )})
    startup_website_import("Example", "https://example.com", session=session, respect_robots=False)
    assert "Zürich" in get_storage().read_text("storage/startups/example/datasets/website/index.md")
