from __future__ import annotations

import re
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests

from lib.datasets.paths import dataset_location_for_domain
from lib.datasets.source import list_source_files, parsed_filepath
from lib.datasets.chunking import split_markdown
from lib.infrastructure.logging import get_logger
from lib.infrastructure.document_formats import (
    DOCUMENT_EXTENSIONS, decode_document_text, detect_document_extension,
)
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.filesystem import replace_directory_snapshot
from lib.insights.locking import manifest_write_lock
from lib.slugify import slugify
from lib.startups.dossier import ensure_startup_dossier
from lib.startups.identity import canonical_startup_slug, startup_aliases
from lib.startups.website import excluded_company_website, website_from_evidence
from lib.storage import Storage, get_storage
from skills.startup_website_import.validation import redirect_allowed, screen_html

logger = get_logger(__name__)

USER_AGENT = "SICTIC-AI startup_website_import/1.0"
EXCLUDED_PATH_PARTS = (
    "privacy",
    "terms",
    "cookie",
    "cookies",
    "legal",
    "login",
    "signin",
    "signup",
    "register",
    "cart",
    "checkout",
)
RESUME_HINT = re.compile(r"(cv|resume|résumé|curriculum|bio|founder|team)", re.I)


@dataclass(frozen=True)
class WebsiteImportResult:
    dataset_slug: str
    website_path: str
    pages_saved: int
    pdfs_saved: int
    link_manifest_path: str
    linkedin_urls_path: str
    linkedin_urls_found: int
    failed_pages: int = 0
    skipped_reason: str | None = None
    documents_saved: int = 0


@dataclass(frozen=True)
class DocumentRecord:
    url: str
    local_path: str
    possible_resume: bool


class _HtmlDocument(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.links: list[str] = []
        self._skip_depth = 0
        self._current_href: str | None = None
        self._title_active = False
        self._blocks: list[str] = []
        self._current_tag: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value for key, value in attrs if value is not None}
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._title_active = True
        if tag == "a":
            href = attrs_dict.get("href")
            if href:
                self.links.append(href)
                self._current_href = href
        if tag == "img":
            alt = attrs_dict.get("alt")
            src = attrs_dict.get("src")
            if alt and self._current_tag:
                self._current_text.append(f"![{alt}]({src or ''})")
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "th", "td"}:
            self._flush_current()
            self._current_tag = tag
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._title_active = False
        if tag == "a":
            self._current_href = None
        if self._current_tag == tag:
            self._flush_current()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        text = _strip_inline_urls(text)
        if not text:
            return
        if self._title_active:
            self.title = f"{self.title} {text}".strip()
        if self._current_tag:
            self._current_text.append(text)

    def markdown(self) -> str:
        self._flush_current()
        return "\n\n".join(block for block in self._blocks if block).strip()

    def _flush_current(self) -> None:
        if not self._current_tag or not self._current_text:
            self._current_tag = None
            self._current_text = []
            return
        text = " ".join(self._current_text).strip()
        if not text:
            return
        if self._current_tag == "h1":
            self._blocks.append(f"# {text}")
        elif self._current_tag == "h2":
            self._blocks.append(f"## {text}")
        elif self._current_tag == "h3":
            self._blocks.append(f"### {text}")
        elif self._current_tag in {"h4", "h5", "h6"}:
            self._blocks.append(f"#### {text}")
        elif self._current_tag == "li":
            self._blocks.append(f"- {text}")
        elif self._current_tag == "blockquote":
            self._blocks.append(f"> {text}")
        elif self._current_tag in {"th", "td"}:
            self._blocks.append(text)
        else:
            self._blocks.append(text)
        self._current_tag = None
        self._current_text = []


def startup_website_import(
    startup_name: str,
    url: str | None = None,
    *,
    depth: int | None = None,
    max_pages: int | None = None,
    include_pdfs: bool | None = None,
    max_pdfs: int | None = None,
    max_pdf_mb: int | None = None,
    respect_robots: bool | None = None,
    include_documents: bool | None = None,
    max_documents: int | None = None,
    max_document_mb: int | None = None,
    session: requests.Session | None = None,
    storage: Storage | None = None,
) -> WebsiteImportResult:
    """Acquire once, using shared crawl settings and an optional documented URL."""
    storage = storage or get_storage()
    slug = canonical_startup_slug(startup_name)
    website_root = f"{dataset_location_for_domain(slug, 'startups').raw_rel}/website"
    if list_source_files(storage, website_root):
        return _skipped_result(slug, website_root, "Website already imported")
    lock_path = Path(storage.local_path(f"cache/startup_website_import/{slug}/acquisition"))
    with manifest_write_lock(lock_path):
        # Another caller may have completed the crawl while this one waited.
        if list_source_files(storage, website_root):
            return _skipped_result(slug, website_root, "Website already imported")
        options = dict(load_repository_config("startup_website_import", "crawl"))
        options.update({key: value for key, value in {
            "depth": depth, "max_pages": max_pages, "include_pdfs": include_pdfs,
            "max_pdfs": max_pdfs, "max_pdf_mb": max_pdf_mb,
            "respect_robots": respect_robots,
        }.items() if value is not None})
        # Preserve old Python/CLI callers and configuration while exposing names
        # that describe the generalized document download policy.
        for old, new, value in (
            ("include_pdfs", "include_documents", include_documents),
            ("max_pdfs", "max_documents", max_documents),
            ("max_pdf_mb", "max_document_mb", max_document_mb),
        ):
            options[new] = value if value is not None else options.pop(old)
            options.pop(old, None)
        return _crawl_website(startup_name, url, session=session, storage=storage, **options)


def _crawl_website(
    startup_name: str,
    url: str | None = None,
    *,
    depth: int = 1,
    max_pages: int = 50,
    include_documents: bool = True,
    max_documents: int = 20,
    max_document_mb: int = 25,
    respect_robots: bool = True,
    session: requests.Session | None = None,
    storage: Storage | None = None,
) -> WebsiteImportResult:
    if depth < 0:
        raise ValueError("depth must be >= 0")
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")
    if max_documents < 0:
        raise ValueError("max_documents must be >= 0")
    if max_document_mb < 1:
        raise ValueError("max_document_mb must be >= 1")

    storage = storage or get_storage()
    dataset_slug = canonical_startup_slug(startup_name)
    location = dataset_location_for_domain(dataset_slug, "startups")
    website_root = f"{location.raw_rel}/website"
    if url is None:
        names = [dataset_slug, *(alias for alias in startup_aliases()
                                if canonical_startup_slug(alias) == dataset_slug)]
        chunks = []
        for filename, mtime in list_source_files(storage, location.raw_rel):
            path = (f"{location.raw_rel}/{filename}" if filename.lower().endswith(".md")
                    else parsed_filepath(location.parsed_rel, filename))
            if storage.exists(path):
                chunks.extend(split_markdown(storage.read_text(path), filename, mtime))
        url = website_from_evidence(names, chunks)
    if not url:
        return _skipped_result(dataset_slug, website_root, "No unambiguous documented website")

    start_url = _normalize_start_url(url)
    if excluded_company_website(start_url):
        logger.warning("Skipping marketplace URL as company website: %s", start_url)
        return _skipped_result(dataset_slug, website_root, "Marketplace URL is not a company website")
    policy = load_repository_config("startup_website_import", "content_policy")
    host = urlparse(start_url).netloc.lower()
    session = session or requests.Session()
    ensure_startup_dossier(startup_name, storage=storage, activate=False)
    # A sibling staging directory permits atomic rename even when cache is on
    # another filesystem. Hidden staging files do not count as dataset activity.
    staging_root = f"{location.raw_rel}/.website-staging-{uuid.uuid4().hex}"
    storage.mkdir(staging_root)

    robots = _load_robots(start_url, session) if respect_robots else None
    seen: set[str] = set()
    queue: deque[tuple[str, int, bool]] = deque([(start_url, 0, False)])
    linkedin_urls: set[str] = set()
    document_records: list[DocumentRecord] = []
    document_paths: set[str] = set()
    saved_urls: set[str] = set()
    page_paths: set[str] = set()
    pages_saved = 0
    failed_pages = 0

    while queue:
        current_url, current_depth, document_link = queue.popleft()
        current_url = _normalize_url(current_url)
        if current_url in seen:
            continue
        seen.add(current_url)
        if document_link:
            if not include_documents or len(document_records) >= max_documents:
                continue
        elif pages_saved >= max_pages:
            continue
        if not _same_host(current_url, host):
            continue
        if _is_excluded_url(current_url):
            logger.info("Skipping low-value website path: %s", current_url)
            continue
        if robots and not robots.can_fetch(USER_AGENT, current_url):
            logger.info("Skipping robots-disallowed URL: %s", current_url)
            continue

        try:
            response = _fetch(session, current_url)
        except Exception as exc:
            failed_pages += 1
            logger.warning("Failed to fetch website page %s: %s", current_url, exc)
            continue
        resolved_url = _normalize_url(getattr(response, "url", None) or current_url)
        if excluded_company_website(resolved_url) or not redirect_allowed(current_url, resolved_url, policy):
            failed_pages += 1
            logger.warning("Skipping unapproved website destination: %s -> %s", current_url, resolved_url)
            continue
        if resolved_url in saved_urls:
            continue
        content = response.content
        if len(content) > max_document_mb * 1024 * 1024:
            failed_pages += 1
            logger.warning("Skipping oversized website response %s -> %s (%d bytes)",
                           current_url, resolved_url, len(content))
            continue
        content_type = response.headers.get("content-type", "")
        extension = detect_document_extension(
            content, filename=resolved_url, content_type=content_type,
        )
        if extension is None:
            failed_pages += 1
            logger.warning("Skipping unknown or unsupported website content %s -> %s (Content-Type: %s)",
                           current_url, resolved_url, content_type)
            continue
        claimed_extension = PurePosixPath(urlparse(current_url).path).suffix.lower()
        if claimed_extension and claimed_extension != extension:
            logger.info("Website content format: %s -> %s; detected %s (Content-Type: %s)",
                        current_url, resolved_url, extension, content_type)
        if extension != ".html":
            if not include_documents or len(document_records) >= max_documents:
                continue
            write_path = _document_storage_path(staging_root, current_url, extension, document_paths)
            if extension in {".txt", ".md", ".json", ".csv"}:
                storage.write_text(write_path, decode_document_text(content, content_type=content_type))
            else:
                storage.write_bytes(write_path, content)
            local_path = f"{website_root}/{write_path.removeprefix(staging_root).lstrip('/')}"
            document_records.append(DocumentRecord(
                url=resolved_url, local_path=local_path,
                possible_resume=bool(RESUME_HINT.search(current_url)),
            ))
            saved_urls.add(resolved_url)
            continue
        if pages_saved >= max_pages:
            continue
        html = decode_document_text(content, content_type=content_type)
        html, reason = screen_html(html, policy)
        if reason:
            logger.warning("Website content check for %s: %s", resolved_url, reason)
        if html is None:
            failed_pages += 1
            continue
        document = _parse_html(html)
        linkedin_urls.update(_extract_linkedin_profile_urls(html))
        page_path = _page_storage_path(staging_root, resolved_url, used_paths=page_paths)
        storage.write_text(
            page_path,
            _render_markdown_page(
                title=document.title,
                source_url=resolved_url,
                depth=current_depth,
                body=document.markdown(),
            ),
        )
        pages_saved += 1
        saved_urls.add(resolved_url)
        # Follow the homepage's canonical host after normal www/domain redirects.
        if current_url == start_url:
            host = urlparse(resolved_url).netloc.lower()
            if respect_robots and urlparse(start_url).netloc.lower() != host:
                robots = _load_robots(resolved_url, session)

        for link in document.links:
            absolute = _normalize_url(urljoin(resolved_url, link))
            if _is_linkedin_profile_url(absolute):
                linkedin_urls.add(_normalize_linkedin_profile_url(absolute))
            if not _same_host(absolute, host):
                continue
            if _is_excluded_url(absolute):
                continue
            suffix = PurePosixPath(urlparse(absolute).path).suffix.lower()
            if suffix in DOCUMENT_EXTENSIONS:
                if include_documents and len(document_records) < max_documents:
                    queue.append((absolute, current_depth + 1, True))
                continue
            if current_depth < depth and absolute not in seen:
                queue.append((absolute, current_depth + 1, False))

    if pages_saved == 0:
        storage.rmtree(staging_root)
        raise InfrastructureError(
            "Website import saved no HTML pages; leaving existing website data unchanged.",
            kind=InfrastructureErrorKind.SERVICE_UNAVAILABLE,
            provider="website", operation="import",
        )

    staging_link_manifest_path = f"{staging_root}/linkedin-and-resume-links.md"
    staging_linkedin_urls_path = f"{staging_root}/linkedin-urls.md"
    sorted_linkedin_urls = sorted(linkedin_urls)
    storage.write_text(
        staging_linkedin_urls_path,
        _render_linkedin_urls(
            start_url=start_url,
            linkedin_urls=sorted_linkedin_urls,
        ),
    )
    storage.write_text(
        staging_link_manifest_path,
        _render_link_manifest(
            start_url=start_url,
            linkedin_urls=sorted_linkedin_urls,
            document_records=document_records,
        ),
    )
    try:
        replace_directory_snapshot(Path(storage.local_path(staging_root)),
                                   Path(storage.local_path(website_root)))
    finally:
        storage.rmtree(staging_root)

    return WebsiteImportResult(
        dataset_slug=dataset_slug,
        website_path=website_root,
        pages_saved=pages_saved,
        pdfs_saved=sum(record.local_path.endswith(".pdf") for record in document_records),
        documents_saved=len(document_records),
        link_manifest_path=f"{website_root}/linkedin-and-resume-links.md",
        linkedin_urls_path=f"{website_root}/linkedin-urls.md",
        linkedin_urls_found=len(sorted_linkedin_urls),
        failed_pages=failed_pages,
    )


def _skipped_result(dataset: str, website_root: str, reason: str) -> WebsiteImportResult:
    logger.info("[%s] Website import skipped: %s", dataset, reason)
    return WebsiteImportResult(
        dataset_slug=dataset, website_path=website_root, pages_saved=0, pdfs_saved=0,
        link_manifest_path=f"{website_root}/linkedin-and-resume-links.md",
        linkedin_urls_path=f"{website_root}/linkedin-urls.md", linkedin_urls_found=0,
        skipped_reason=reason,
    )


def _fetch(session, url: str):
    response = session.get(url, headers={"user-agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    return response


def _load_robots(start_url: str, session) -> RobotFileParser | None:
    parsed = urlparse(start_url)
    robots_url = urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        response = _fetch(session, robots_url)
        parser.parse(response.text.splitlines())
    except Exception as exc:
        logger.info("Could not load robots.txt from %s: %s", robots_url, exc)
        return None
    return parser


def _normalize_start_url(url: str) -> str:
    if not re.match(r"^https?://", url, flags=re.I):
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Unsupported website URL: {url}")
    return _normalize_url(url)


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            parsed.query,
            "",
        )
    )


def _same_host(url: str, host: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == host


def _is_excluded_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    parts = [part for part in path.split("/") if part]
    return any(part in EXCLUDED_PATH_PARTS for part in parts)


def _is_linkedin_profile_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.lower().endswith("linkedin.com") and "/in/" in parsed.path.lower()


def _extract_linkedin_profile_urls(text: str) -> set[str]:
    matches = re.findall(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^\s\"'<>)]*", text, flags=re.I)
    return {_normalize_linkedin_profile_url(match) for match in matches}


def _strip_inline_urls(text: str) -> str:
    return " ".join(
        re.sub(r"https?://[^\s\"'<>)]*", "", text).split()
    ).strip()


def _normalize_linkedin_profile_url(url: str) -> str:
    parsed = urlparse(url.strip().rstrip(".,;:"))
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path + "/", "", "", ""))


def _parse_html(html: str) -> _HtmlDocument:
    document = _HtmlDocument()
    document.feed(html)
    document.close()
    return document


def _page_storage_path(
    website_root: str,
    page_url: str,
    *,
    used_paths: set[str],
) -> str:
    parsed = urlparse(page_url)
    parts = [slugify(part) for part in parsed.path.split("/") if part]
    if not parts:
        path = f"{website_root}/index.md"
        return _unique_storage_path(path, page_url, used_paths)
    if "." in parts[-1]:
        parts[-1] = PurePosixPath(parts[-1]).stem
    directory = "/".join(parts[:-1])
    filename = f"{parts[-1]}.md"
    path = f"{website_root}/{directory}/{filename}" if directory else f"{website_root}/{filename}"
    return _unique_storage_path(path, page_url, used_paths)


def _document_storage_path(
    website_root: str, url: str, extension: str, used_paths: set[str],
) -> str:
    parsed = urlparse(url)
    filename = PurePosixPath(parsed.path).name or "document"
    stem = slugify(PurePosixPath(filename).stem) or "document"
    directory = "pdfs" if extension == ".pdf" else "documents"
    return _unique_storage_path(f"{website_root}/{directory}/{stem}{extension}", url, used_paths)


def _unique_storage_path(path: str, source_url: str, used_paths: set[str]) -> str:
    if path not in used_paths:
        used_paths.add(path)
        return path
    suffix = sha256(source_url.encode("utf-8")).hexdigest()[:8]
    base, ext = path.rsplit(".", 1)
    candidate = f"{base}-{suffix}.{ext}"
    counter = 2
    while candidate in used_paths:
        candidate = f"{base}-{suffix}-{counter}.{ext}"
        counter += 1
    used_paths.add(candidate)
    return candidate


def _render_markdown_page(
    *,
    title: str,
    source_url: str,
    depth: int,
    body: str,
) -> str:
    title = title or source_url
    fetched_at = datetime.now(timezone.utc).isoformat()
    return (
        "---\n"
        f'title: "{_escape_frontmatter(title)}"\n'
        f"source_url: {source_url}\n"
        f"source_depth: {depth}\n"
        f"fetched_at: {fetched_at}\n"
        "---\n\n"
        f"{body}\n"
    )


def _render_link_manifest(
    *,
    start_url: str,
    linkedin_urls: list[str],
    document_records: list[DocumentRecord],
) -> str:
    lines = [
        "---",
        f"source_url: {start_url}",
        f"fetched_at: {datetime.now(timezone.utc).isoformat()}",
        "---",
        "",
        "# LinkedIn and Resume Links",
        "",
        "## LinkedIn Profiles",
        "",
    ]
    if linkedin_urls:
        lines.extend(f"- {url}" for url in linkedin_urls)
    else:
        lines.append("_None found._")
    lines.extend(["", "## Downloaded Documents", ""])
    if document_records:
        for record in document_records:
            marker = " possible resume/CV" if record.possible_resume else ""
            lines.append(f"- [{record.url}]({record.local_path}){marker}")
    else:
        lines.append("_None downloaded._")
    lines.append("")
    return "\n".join(lines)


def _render_linkedin_urls(
    *,
    start_url: str,
    linkedin_urls: list[str],
) -> str:
    lines = [
        "---",
        f"source_url: {start_url}",
        f"fetched_at: {datetime.now(timezone.utc).isoformat()}",
        f"count: {len(linkedin_urls)}",
        "---",
        "",
        "# LinkedIn URLs",
        "",
    ]
    if linkedin_urls:
        lines.extend(f"- {url}" for url in linkedin_urls)
    else:
        lines.append("_None found._")
    lines.append("")
    return "\n".join(lines)


def _escape_frontmatter(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
