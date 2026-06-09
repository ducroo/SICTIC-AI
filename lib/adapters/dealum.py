from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import requests

from lib.logger import get_logger

logger = get_logger(__name__)


DEALUM_BASE_URL = "https://app.dealum.com/api/integrations"


@dataclass(frozen=True)
class DealumFileLink:
    field: str
    url: str
    filename: str


class DealumAdapter:
    """Small REST client for Dealum's integration API."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        dealroom_id: Optional[str] = None,
        base_url: str = DEALUM_BASE_URL,
        timeout: int = 30,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("DEALUM_API_KEY")
        self.dealroom_id = dealroom_id if dealroom_id is not None else os.environ.get("DEALUM_DEALROOM_ID")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key and self.dealroom_id)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError("DEALUM_API_KEY is not configured.")
        return {"X-Access-Token": self.api_key}

    def list_applications(self) -> list[dict[str, Any]]:
        if not self.dealroom_id:
            raise ValueError("DEALUM_DEALROOM_ID is not configured.")
        url = f"{self.base_url}/dealrooms/{self.dealroom_id}/applications"
        logger.info("[dealum-api] Listing applications: dealroom_id=%s", self.dealroom_id)
        response = requests.get(url, headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Dealum applications response was not a list.")
        logger.info(
            "[dealum-api] Listed %d applications: dealroom_id=%s",
            len(data),
            self.dealroom_id,
        )
        return data

    def extract_file_links(self, application: dict[str, Any]) -> list[DealumFileLink]:
        answers = application.get("answers") or {}
        if not isinstance(answers, dict):
            return []

        links: list[DealumFileLink] = []
        seen: set[str] = set()
        for field, value in answers.items():
            if not isinstance(value, str):
                continue
            for url in _extract_urls(value):
                if "files.dealum.com" not in urlparse(url).netloc:
                    continue
                if url in seen:
                    continue
                seen.add(url)
                links.append(DealumFileLink(field=field, url=url, filename=safe_filename_from_url(url)))
        return links

    def file_metadata(self, url: str) -> dict[str, Any]:
        response = requests.head(url, allow_redirects=True, timeout=self.timeout)
        response.raise_for_status()
        return {
            "url": url,
            "resolved_url": response.url,
            "content_type": response.headers.get("content-type"),
            "content_length": response.headers.get("content-length"),
            "etag": response.headers.get("etag"),
        }

    def download_file(self, url: str) -> tuple[bytes, dict[str, Any]]:
        response = requests.get(url, allow_redirects=True, timeout=self.timeout)
        response.raise_for_status()
        metadata = {
            "url": url,
            "resolved_url": response.url,
            "content_type": response.headers.get("content-type"),
            "content_length": response.headers.get("content-length"),
            "etag": response.headers.get("etag"),
        }
        return response.content, metadata


def _extract_urls(value: str) -> list[str]:
    return re.findall(r"https?://[^\s\"'<>]+", value)


def safe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = unquote(parsed.path.rsplit("/", 1)[-1] or "dealum-file")
    name = re.sub(r"[^A-Za-z0-9._ -]+", "-", name).strip(" .-")
    return name or "dealum-file"
