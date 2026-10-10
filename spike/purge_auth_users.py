"""Delete Firebase Auth profiles older than a retention window.

Uses the Identity Toolkit Admin REST API with FIREBASE_SERVICE_ACCOUNT_JSON.
No Cloud Functions required — run from the VPS via cron or the admin API.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account

from lib.infrastructure.logging import get_logger
from spike.app_check import firebase_project_id

logger = get_logger(__name__)

DEFAULT_RETENTION_DAYS = 60
_DOWNLOAD_URL = (
    "https://identitytoolkit.googleapis.com/identitytoolkit/v3/relyingparty/downloadAccount"
)
_DELETE_URL = (
    "https://identitytoolkit.googleapis.com/identitytoolkit/v3/relyingparty/deleteAccount"
)


@dataclass(frozen=True)
class AuthUserRecord:
    local_id: str
    email: str
    created_at_ms: int
    display_name: str


@dataclass(frozen=True)
class PurgeResult:
    retention_days: int
    scanned: int
    deleted: int
    dry_run: bool
    deleted_emails: tuple[str, ...]


def _service_account_info() -> dict[str, Any]:
    raw = (os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
    if not raw:
        raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON is not configured.")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON.") from error
    if not isinstance(info, dict):
        raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON must be a JSON object.")
    return info


def _access_token(info: dict[str, Any]) -> str:
    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/identitytoolkit",
            "https://www.googleapis.com/auth/cloud-platform",
            "https://www.googleapis.com/auth/firebase",
        ],
    )
    credentials.refresh(GoogleAuthRequest())
    if not credentials.token:
        raise RuntimeError("Could not refresh the Firebase service-account token.")
    return credentials.token


def _post_json(url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Identity Toolkit HTTP {error.code}: {detail}") from error
    return json.loads(raw) if raw else {}


def _project_id(info: dict[str, Any], project_id: str | None = None) -> str:
    """Prefer an explicit id, then the service-account project, then env."""
    for candidate in (
        project_id,
        str(info.get("project_id") or ""),
        firebase_project_id(),
    ):
        cleaned = (candidate or "").strip()
        if cleaned:
            return cleaned
    raise ValueError("FIREBASE_PROJECT_ID is not configured.")


def list_auth_users(*, project_id: str | None = None) -> list[AuthUserRecord]:
    """Return Auth users for the Firebase project."""
    info = _service_account_info()
    project = _project_id(info, project_id)
    token = _access_token(info)
    users: list[AuthUserRecord] = []
    next_page: str | None = None
    while True:
        body: dict[str, Any] = {"targetProjectId": project, "maxResults": 1000}
        if next_page:
            body["nextPageToken"] = next_page
        payload = _post_json(_DOWNLOAD_URL, token, body)
        for row in payload.get("users") or []:
            created_raw = str(row.get("createdAt") or "0")
            try:
                created_at_ms = int(created_raw)
            except ValueError:
                created_at_ms = 0
            users.append(
                AuthUserRecord(
                    local_id=str(row.get("localId") or ""),
                    email=str(row.get("email") or ""),
                    created_at_ms=created_at_ms,
                    display_name=str(row.get("displayName") or ""),
                )
            )
        next_page = payload.get("nextPageToken")
        if not next_page:
            break
    return [user for user in users if user.local_id]


def delete_auth_user(local_id: str, *, project_id: str | None = None) -> None:
    info = _service_account_info()
    project = _project_id(info, project_id)
    if not local_id.strip():
        raise ValueError("local_id is required.")
    token = _access_token(info)
    _post_json(
        _DELETE_URL,
        token,
        {"localId": local_id, "targetProjectId": project},
    )


def purge_auth_users_older_than(
    *,
    days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
    project_id: str | None = None,
    now_ms: int | None = None,
) -> PurgeResult:
    """Delete Auth profiles whose createdAt is older than ``days``."""
    if days < 1:
        raise ValueError("days must be at least 1.")
    cutoff_ms = (now_ms if now_ms is not None else int(time.time() * 1000)) - days * 86_400_000
    users = list_auth_users(project_id=project_id)
    stale = [user for user in users if user.created_at_ms and user.created_at_ms < cutoff_ms]
    deleted_emails: list[str] = []
    for user in stale:
        label = user.email or user.local_id
        if dry_run:
            logger.info("Would delete Auth user %s (createdAt=%s)", label, user.created_at_ms)
            deleted_emails.append(label)
            continue
        delete_auth_user(user.local_id, project_id=project_id)
        logger.info("Deleted Auth user %s", label)
        deleted_emails.append(label)
    return PurgeResult(
        retention_days=days,
        scanned=len(users),
        deleted=len(deleted_emails),
        dry_run=dry_run,
        deleted_emails=tuple(deleted_emails),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Delete Firebase Auth profiles older than the retention window.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"Retention window in days (default {DEFAULT_RETENTION_DAYS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List profiles that would be deleted without deleting them.",
    )
    args = parser.parse_args(argv)
    result = purge_auth_users_older_than(days=args.days, dry_run=args.dry_run)
    print(
        json.dumps(
            {
                "retention_days": result.retention_days,
                "scanned": result.scanned,
                "deleted": result.deleted,
                "dry_run": result.dry_run,
                "deleted_emails": list(result.deleted_emails),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
