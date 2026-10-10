"""Verify Firebase Auth ID tokens for the pitch-deck API."""

from __future__ import annotations

import os
import time
from typing import Any

import jwt
from jwt import PyJWKClient

from lib.infrastructure.logging import get_logger
from spike.app_check import firebase_project_id

logger = get_logger(__name__)

AUTH_JWKS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/"
    "securetoken@system.gserviceaccount.com"
)
AUTH_HEADER = "Authorization"
_jwks_client: PyJWKClient | None = None


def auth_required() -> bool:
    flag = (os.environ.get("SPIKE_REQUIRE_AUTH") or "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if flag in {"1", "true", "yes", "on"}:
        return True
    return bool(firebase_project_id())


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(AUTH_JWKS_URL, cache_keys=True)
    return _jwks_client


def expected_issuer(project_id: str) -> str:
    return f"https://securetoken.google.com/{project_id}"


def id_token_from_headers(headers: Any) -> str:
    if headers is None:
        return ""
    value = headers.get(AUTH_HEADER) or headers.get(AUTH_HEADER.lower()) or ""
    text = str(value).strip()
    if text.lower().startswith("bearer "):
        return text[7:].strip()
    return ""


def verify_id_token(token: str, *, project_id: str | None = None) -> dict[str, Any]:
    """Return Firebase Auth claims, or raise ValueError when the token is invalid."""
    cleaned = token.strip()
    if not cleaned:
        raise ValueError("Sign-in is required.")
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
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except Exception as error:
        logger.warning("Firebase Auth token verification failed: %s", error)
        raise ValueError("Sign-in token is invalid.") from error
    if claims.get("iss") != expected_issuer(project):
        raise ValueError("Sign-in token issuer is invalid.")
    if not str(claims.get("sub") or "").strip():
        raise ValueError("Sign-in token subject is invalid.")
    if claims.get("email_verified") is not True:
        raise ValueError("Verify your email before using the review.")
    return claims


def reset_jwks_client() -> None:
    """Test helper."""
    global _jwks_client
    _jwks_client = None
    _ = time.time()
