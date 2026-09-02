from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests

from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.logging import get_logger
from lib.slugify import slugify
from lib.startups.dossier import ensure_startup_dossier
from lib.storage import Storage, get_storage

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


@dataclass(frozen=True)
class PdfRecord:
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
    url: str,
    *,
    depth: int = 1,
    max_pages: int = 50,
    include_pdfs: bool = True,
    max_pdfs: int = 20,
    max_pdf_mb: int = 25,
    respect_robots: bool = True,
    session: requests.Session | None = None,
    storage: Storage | None = None,
) -> WebsiteImportResult:
    if depth < 0:
        raise ValueError("depth must be >= 0")
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")
    if max_pdfs < 0:
        raise ValueError("max_pdfs must be >= 0")

    start_url = _normalize_start_url(url)
    host = urlparse(start_url).netloc.lower()
    session = session or requests.Session()
    storage = storage or get_storage()

    dataset_slug = ensure_startup_dossier(startup_name, storage=storage, activate=False)
    location = dataset_location_for_domain(dataset_slug, "startups")
    website_root = f"{location.raw_rel}/website"
    staging_root = f"cache/startup_website_import/{dataset_slug}/website"
    storage.rmtree(staging_root)
    storage.mkdir(staging_root)

    robots = _load_robots(start_url, session) if respect_robots else None
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    linkedin_urls: set[str] = set()
    pdf_urls: list[str] = []
    page_paths: set[str] = set()
    pages_saved = 0
    failed_pages = 0

    while queue and pages_saved < max_pages:
        current_url, current_depth = queue.popleft()
        current_url = _normalize_url(current_url)
        if current_url in seen:
            continue
        seen.add(current_url)
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
        content_type = response.headers.get("content-type", "").lower()
        if _is_pdf_url(current_url, content_type):
            if include_pdfs and len(pdf_urls) < max_pdfs:
                pdf_urls.append(current_url)
            continue
        if "html" not in content_type and not current_url.endswith(("/", ".html", ".htm")):
            continue

        document = _parse_html(response.text)
        linkedin_urls.update(_extract_linkedin_profile_urls(response.text))
        page_path = _page_storage_path(staging_root, current_url, used_paths=page_paths)
        storage.write_text(
            page_path,
            _render_markdown_page(
                title=document.title,
                source_url=current_url,
                depth=current_depth,
                body=document.markdown(),
            ),
        )
        pages_saved += 1

        for link in document.links:
            absolute = _normalize_url(urljoin(current_url, link))
            if _is_linkedin_profile_url(absolute):
                linkedin_urls.add(_normalize_linkedin_profile_url(absolute))
            if not _same_host(absolute, host):
                continue
            if _is_excluded_url(absolute):
                continue
            if _is_pdf_url(absolute, ""):
                if include_pdfs and len(pdf_urls) < max_pdfs:
                    pdf_urls.append(absolute)
                continue
            if current_depth < depth and absolute not in seen:
                queue.append((absolute, current_depth + 1))

    pdf_records = []
    if include_pdfs:
        pdf_records = _download_pdfs(
            pdf_urls,
            write_root=staging_root,
            manifest_root=website_root,
            host=host,
            session=session,
            storage=storage,
            robots=robots,
            max_pdfs=max_pdfs,
            max_pdf_mb=max_pdf_mb,
        )

    if pages_saved == 0:
        storage.rmtree(staging_root)
        raise RuntimeError("Website import saved no HTML pages; leaving existing website data unchanged.")

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
            pdf_records=pdf_records,
        ),
    )
    storage.rmtree(website_root)
    _copy_tree(storage, staging_root, website_root)
    storage.rmtree(staging_root)

    return WebsiteImportResult(
        dataset_slug=dataset_slug,
        website_path=website_root,
        pages_saved=pages_saved,
        pdfs_saved=len(pdf_records),
        link_manifest_path=f"{website_root}/linkedin-and-resume-links.md",
        linkedin_urls_path=f"{website_root}/linkedin-urls.md",
        linkedin_urls_found=len(sorted_linkedin_urls),
        failed_pages=failed_pages,
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


def _is_pdf_url(url: str, content_type: str) -> bool:
    return "application/pdf" in content_type or urlparse(url).path.lower().endswith(".pdf")


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


def _pdf_storage_path(website_root: str, pdf_url: str, used_paths: set[str]) -> str:
    parsed = urlparse(pdf_url)
    filename = PurePosixPath(parsed.path).name or "document.pdf"
    stem = slugify(PurePosixPath(filename).stem) or "document"
    return _unique_storage_path(f"{website_root}/pdfs/{stem}.pdf", pdf_url, used_paths)


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


def _download_pdfs(
    urls: Iterable[str],
    *,
    write_root: str,
    manifest_root: str,
    host: str,
    session,
    storage: Storage,
    robots: RobotFileParser | None,
    max_pdfs: int,
    max_pdf_mb: int,
) -> list[PdfRecord]:
    records: list[PdfRecord] = []
    seen: set[str] = set()
    pdf_paths: set[str] = set()
    max_bytes = max_pdf_mb * 1024 * 1024
    for url in urls:
        if len(records) >= max_pdfs:
            break
        url = _normalize_url(url)
        if url in seen or not _same_host(url, host):
            continue
        seen.add(url)
        if robots and not robots.can_fetch(USER_AGENT, url):
            continue
        try:
            response = _fetch(session, url)
        except Exception as exc:
            logger.warning("Failed to download PDF %s: %s", url, exc)
            continue
        content_type = response.headers.get("content-type", "").lower()
        if not _is_pdf_url(url, content_type):
            continue
        content = response.content
        if len(content) > max_bytes:
            logger.warning("Skipping oversized PDF %s (%s bytes)", url, len(content))
            continue
        write_path = _pdf_storage_path(write_root, url, pdf_paths)
        local_path = f"{manifest_root}/{write_path.removeprefix(write_root).lstrip('/')}"
        storage.write_bytes(write_path, content)
        records.append(
            PdfRecord(
                url=url,
                local_path=local_path,
                possible_resume=bool(RESUME_HINT.search(url)),
            )
        )
    return records


def _copy_tree(storage: Storage, source_root: str, target_root: str) -> None:
    storage.mkdir(target_root)
    for relative_path, _mtime in storage.list_with_mtime(source_root, recursive=True):
        source_path = f"{source_root}/{relative_path}"
        target_path = f"{target_root}/{relative_path}"
        storage.write_bytes(target_path, storage.read_bytes(source_path))


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
    pdf_records: list[PdfRecord],
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
    lines.extend(["", "## Downloaded PDFs", ""])
    if pdf_records:
        for record in pdf_records:
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
