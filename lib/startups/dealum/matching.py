from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lib.adapters.dealum import DealumAdapter
from lib.logger import get_logger
from lib.slugify import slugify
from lib.startups.identity import canonical_startup_slug

logger = get_logger(__name__)

DEALUM_APP_URL = (
    "https://app.dealum.com/#/dealroom/{dealroom_id}"
    "?application={application_id}"
)


@dataclass(frozen=True)
class DealumMatch:
    requested_startup: str
    matched_name: str
    dataset_slug: str
    dealum_id: Any
    dealum_url: str | None
    application_code: str | None
    step: str | None
    match_method: str
    application: dict[str, Any]


class DealumReconciliationError(ValueError):
    """Base error for startup-name reconciliation against Dealum."""


class DealumApplicationNotFoundError(DealumReconciliationError):
    """Raised when no exact Dealum name or application code matches."""


class DealumApplicationAmbiguousError(DealumReconciliationError):
    """Raised when an exact lookup identifies more than one application."""


def dealum_application_url(
    dealroom_id: str | None,
    application_id: Any,
) -> str | None:
    if not dealroom_id or application_id in (None, ""):
        return None
    return DEALUM_APP_URL.format(
        dealroom_id=dealroom_id,
        application_id=application_id,
    )


def reconcile_dealum_startup(
    startup: str,
    *,
    adapter: DealumAdapter | None = None,
) -> DealumMatch:
    requested = startup.strip()
    if not requested:
        raise DealumReconciliationError(
            "Provide a startup name or Dealum application code."
        )

    adapter = adapter or DealumAdapter()
    if not adapter.is_configured():
        raise ValueError(
            "Dealum is not configured. Set DEALUM_API_KEY and "
            "DEALUM_DEALROOM_ID."
        )

    target_slug = slugify(requested)
    target_code = requested.casefold()
    logger.info(
        "[dealum-reconcile] Starting reconciliation: "
        "requested=%r normalized=%r",
        requested,
        target_slug,
    )
    try:
        applications = adapter.list_applications()
    except Exception:
        logger.exception(
            "[dealum-reconcile] Failed to retrieve Dealum applications: "
            "requested=%r",
            requested,
        )
        raise

    logger.info(
        "[dealum-reconcile] Retrieved %d Dealum applications for "
        "requested=%r",
        len(applications),
        requested,
    )
    name_matches = [
        application
        for application in applications
        if slugify(str(application.get("name") or "")) == target_slug
    ]
    if name_matches:
        return _dealum_match(
            requested,
            name_matches,
            "normalized_name",
            adapter.dealroom_id,
        )

    code_matches = [
        application
        for application in applications
        if str(application.get("code") or "").strip().casefold()
        == target_code
    ]
    if code_matches:
        return _dealum_match(
            requested,
            code_matches,
            "application_code",
            adapter.dealroom_id,
        )

    logger.warning(
        "[dealum-reconcile] No exact match: requested=%r normalized=%r "
        "applications_checked=%d",
        requested,
        target_slug,
        len(applications),
    )
    raise DealumApplicationNotFoundError(
        f"No exact Dealum application match for '{requested}'. "
        "Provide the startup name as shown in Dealum or its application code."
    )


def _dealum_match(
    requested: str,
    applications: list[dict[str, Any]],
    match_method: str,
    dealroom_id: str | None,
) -> DealumMatch:
    if len(applications) > 1:
        candidates = [
            {
                "name": application.get("name"),
                "id": application.get("id"),
                "code": application.get("code"),
                "step": application.get("step"),
            }
            for application in applications
        ]
        logger.error(
            "[dealum-reconcile] Ambiguous exact match: requested=%r "
            "method=%s candidates=%s",
            requested,
            match_method,
            candidates,
        )
        names = ", ".join(
            f"{item.get('name') or 'unnamed'} "
            f"({item.get('code') or item.get('id') or 'no identifier'})"
            for item in candidates
        )
        raise DealumApplicationAmbiguousError(
            f"Multiple Dealum applications match '{requested}': {names}."
        )

    application = applications[0]
    matched_name = str(application.get("name") or requested).strip()
    match = DealumMatch(
        requested_startup=requested,
        matched_name=matched_name,
        dataset_slug=canonical_startup_slug(matched_name),
        dealum_id=application.get("id"),
        dealum_url=dealum_application_url(
            dealroom_id,
            application.get("id"),
        ),
        application_code=application.get("code"),
        step=application.get("step"),
        match_method=match_method,
        application=application,
    )
    logger.info(
        "[dealum-reconcile] Matched requested=%r to name=%r id=%r "
        "code=%r step=%r method=%s dataset_slug=%r url=%r",
        requested,
        match.matched_name,
        match.dealum_id,
        match.application_code,
        match.step,
        match.match_method,
        match.dataset_slug,
        match.dealum_url,
    )
    return match
