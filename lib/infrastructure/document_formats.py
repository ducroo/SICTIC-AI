"""Identify downloaded documents by content, independently of HTTP/URL claims.

Detection identifies a format, not whether every page or archive member is valid.
Conversion remains responsible for validating and reading the whole document.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
import zlib
from pathlib import PurePosixPath
from urllib.parse import urlparse

import filetype


# Formats handled by the existing document-conversion stack. Media and generic
# archives are intentionally excluded from website evidence acquisition.
DOCUMENT_EXTENSIONS = frozenset({
    ".pdf", ".docx", ".xlsx", ".xlsm", ".xls", ".pptx", ".rtf",
    ".txt", ".md", ".json", ".csv",
})


def decode_document_text(content: bytes, *, content_type: str = "") -> str:
    """Decode text without silently discarding bytes or accepting binary data."""
    encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        text = content.decode(encoding)
    except UnicodeError:
        # Legacy website encodings may be explicitly declared by the server or
        # HTML metadata. Do not guess an encoding for unidentified binary data.
        declaration = re.search(r"charset\s*=\s*[\"']?([\w.-]+)", content_type, re.I)
        if declaration is None:
            meta = re.search(br"<meta\b[^>]*\bcharset\s*=\s*[\"']?([\w.-]+)",
                             content[:8192], re.I)
            charset = meta[1].decode("ascii") if meta else None
        else:
            charset = declaration[1]
        if not charset:
            raise
        try:
            text = content.decode(charset)
        except LookupError as error:
            raise ValueError("Unknown document character encoding") from error
    if any(ord(char) < 32 and char not in "\t\r\n\f" for char in text):
        raise ValueError("Document contains binary control characters")
    return text


def detect_document_extension(
    content: bytes, *, filename: str = "", content_type: str = "",
) -> str | None:
    """Return a supported extension (or HTML) from the downloaded bytes.

    Names and headers only disambiguate already verified text (Markdown/CSV).
    They can never turn HTML or arbitrary binary data into an Office file or PDF.
    """
    if not content:
        return None
    if content.startswith(b"%PDF-"):
        return ".pdf"
    if content.startswith(b"PK"):
        return _office_extension(content)
    if content.startswith(b"{\\rtf"):
        return ".rtf"
    detected = filetype.guess(content)
    if detected is not None:
        extension = f".{detected.extension}"
        # PDF and OOXML require the checks above; unsupported binary types must
        # never fall through to the permissive plain-text branch.
        return extension if extension == ".xls" else None
    try:
        text = decode_document_text(content, content_type=content_type)
    except (UnicodeError, ValueError):
        return None
    if not text.strip():
        return None
    try:
        if isinstance(json.loads(text), (dict, list)):
            return ".json"
    except ValueError:
        pass
    if re.match(
        r"\s*(?:<!--.*?-->\s*)*(?:<\?xml.*?\?>\s*)?"
        r"(?:<!doctype\s+html\b|<(?:html|head|body|title|meta|link|script|style|h[1-6]|p|div|table|a|ul|ol|section)\b[^>]*>)",
        text, re.I | re.S,
    ):
        return ".html"
    # Unknown XML is not a plain-text document supported by our converters.
    if text.lstrip().startswith("<"):
        return None
    suffix = PurePosixPath(urlparse(filename).path).suffix.lower()
    mime = content_type.partition(";")[0].strip().lower()
    if suffix == ".csv" or mime == "text/csv":
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
            rows = list(csv.reader(io.StringIO(text[:8192]), dialect))
            if len(rows) >= 2 and len(rows[0]) > 1:
                return ".csv"
        except csv.Error:
            pass
    if suffix == ".md" or mime in {"text/markdown", "text/x-markdown"}:
        return ".md"
    if mime in {"text/css", "text/javascript", "application/javascript"}:
        return None
    return ".txt"


def _office_extension(content: bytes) -> str | None:
    """Inspect the ZIP directory, rather than trusting an Office suffix."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names:
                return None
            matches = [extension for member, extension in (
                ("word/document.xml", ".docx"),
                ("xl/workbook.xml", ".xlsx"),
                ("ppt/presentation.xml", ".pptx"),
            ) if member in names]
            if len(matches) != 1:
                return None
            extension = matches[0]
            if extension == ".xlsx":
                info = archive.getinfo("[Content_Types].xml")
                if info.file_size > 256 * 1024:
                    return None
                if b"macroEnabled.main+xml" in archive.read(info):
                    return ".xlsm"
            return extension
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError, EOFError, zlib.error):
        return None
