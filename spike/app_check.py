"""Verify Firebase App Check tokens for the pitch-deck API."""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.request import urlopen

import jwt
from jwt import PyJWKClient

from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

APP_CHECK_JWKS_URL = "https://firebaseappcheck.googleapis.com/v1/jwks"
APP_CHECK_ISSUER = "https://firebaseappcheck.googleapis.com/"
HEADER_NAME = "X-Firebase-AppCheck"

_jwks_client: PyJWKClient | None = None


def firebase_project_id() -> str:
    configured = (os.environ.get("FIREBASE_PROJECT_ID") or "").strip()
    if configured:
        return configured
    raw = (os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
    if not raw:
        return ""
    try:
        return str(json.loads(raw).get("project_id") or "").strip()
    except json.JSONDecodeError:
        logger.warning("FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON.")
        return ""


def app_check_required() -> bool:
    flag = (os.environ.get("SPIKE_REQUIRE_APP_CHECK") or "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if flag in {"1", "true", "yes", "on"}:
        return True
    return bool(firebase_project_id())


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(APP_CHECK_JWKS_URL, cache_keys=True)
    return _jwks_client


def verify_app_check_token(token: str, *, project_id: str | None = None) -> dict[str, Any]:
    """Return App Check claims, or raise ValueError when the token is invalid."""
    cleaned = token.strip()
    if not cleaned:
        raise ValueError("App Check token is missing.")
    project = (project_id or firebase_project_id()).strip()
    if not project:
        raise ValueError("FIREBASE_PROJECT_ID is not configured.")
    try:
        signing_key = _jwks().get_signing_key_from_jwt(cleaned)
        claims = jwt.decode(
            cleaned,
            signing_key.key,
            algorithms=["RS256"],
            audience=project,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except Exception as error:
        raise ValueError("App Check token is invalid.") from error
    if claims.get("iss") != APP_CHECK_ISSUER:
        raise ValueError("App Check token issuer is invalid.")
    subject = str(claims.get("sub") or "")
    if f":web:" not in subject and f":{project}:" not in subject:
        # Accept any app under this project. Subjects look like
        # 1:PROJECT_NUMBER:web:APP_ID.
        if not subject.startswith("1:"):
            raise ValueError("App Check token subject is invalid.")
    return claims


def token_from_headers(headers: Any) -> str:
    if headers is None:
        return ""
    value = headers.get(HEADER_NAME) or headers.get(HEADER_NAME.lower())
    return str(value or "").strip()


def jwks_reachable() -> bool:
    """Cheap readiness check used by health endpoints."""
    try:
        with urlopen(APP_CHECK_JWKS_URL, timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def reset_jwks_client() -> None:
    """Test helper."""
    global _jwks_client
    _jwks_client = None
    # Touch time so static analyzers keep the import used in tests that mock it.
    _ = time.time()
