from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from lib.infrastructure.dealum import DealumAdapter
from lib.infrastructure.logging import get_logger
from lib.slugify import slugify
from lib.startups.identity import canonical_startup_slug

logger = get_logger(__name__)

DEALUM_APP_URL = (
    "https://app.dealum.com/#/dealroom/{dealroom_id}"
    "?application={application_id}"
)
APPLICATION_DATE_FIELDS = (
    "createDate",
    "applicationDate",
    "submittedAt",
    "createdAt",
    "updatedAt",
    "joinDate",
    "moveDate",
    "reviewDate",
)


@dataclass(frozen=True)
class DealumMatch:
    requested_startup: str
    matched_name: str
    dataset_slug: str
    dealum_id: Any
    dealum_url: str | None
    application_code: str | None
    application_date: str | None
    step: str | None
    match_method: str
    selection_method: str
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
    applications: list[dict[str, Any]] | None = None,
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
    if applications is None:
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
        application = _select_latest_application(
            requested,
            applications,
            match_method,
        )
        selection_method = "latest_application_date"
    else:
        application = applications[0]
        selection_method = "single_match"

    matched_name = str(application.get("name") or requested).strip()
    application_date = _application_date_value(application)
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
        application_date=application_date,
        step=application.get("step"),
        match_method=match_method,
        selection_method=selection_method,
        application=application,
    )
    logger.info(
        "[dealum-reconcile] Matched requested=%r to name=%r id=%r "
        "code=%r date=%r step=%r method=%s selection=%s dataset_slug=%r url=%r",
        requested,
        match.matched_name,
        match.dealum_id,
        match.application_code,
        match.application_date,
        match.step,
        match.match_method,
        match.selection_method,
        match.dataset_slug,
        match.dealum_url,
    )
    return match


def _select_latest_application(
    requested: str,
    applications: list[dict[str, Any]],
    match_method: str,
) -> dict[str, Any]:
    dated = [
        (_application_datetime(application), application)
        for application in applications
    ]
    dated = [
        (date, application)
        for date, application in dated
        if date is not None
    ]
    if not dated:
        _raise_ambiguous(
            requested,
            applications,
            match_method,
            "no usable dates",
        )

    dated.sort(key=lambda item: item[0], reverse=True)
    latest_date = dated[0][0]
    latest = [
        application
        for date, application in dated
        if date == latest_date
    ]
    if len(latest) > 1:
        _raise_ambiguous(
            requested,
            latest,
            match_method,
            f"tied latest date {latest_date.isoformat()}",
        )

    selected = latest[0]
    logger.info(
        "[dealum-reconcile] Multiple exact matches for %r; selected latest "
        "application id=%r date=%r",
        requested,
        selected.get("id"),
        _application_date_value(selected),
    )
    return selected


def _application_date_value(application: dict[str, Any]) -> str | None:
    for field in APPLICATION_DATE_FIELDS:
        value = application.get(field)
        if value:
            return str(value)
    return None


def _application_datetime(application: dict[str, Any]) -> datetime | None:
    value = _application_date_value(application)
    if not value:
        return None
    if value.isdigit():
        timestamp = int(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _raise_ambiguous(
    requested: str,
    applications: list[dict[str, Any]],
    match_method: str,
    reason: str,
) -> None:
    candidates = [
        {
            "name": application.get("name"),
            "id": application.get("id"),
            "code": application.get("code"),
            "date": _application_date_value(application),
            "step": application.get("step"),
        }
        for application in applications
    ]
    logger.error(
        "[dealum-reconcile] Ambiguous exact match: requested=%r "
        "method=%s reason=%s candidates=%s",
        requested,
        match_method,
        reason,
        candidates,
    )
    names = ", ".join(
        f"{item.get('name') or 'unnamed'} "
        f"({item.get('code') or item.get('id') or 'no identifier'}, "
        f"date={item.get('date') or 'unknown'})"
        for item in candidates
    )
    raise DealumApplicationAmbiguousError(
        f"Multiple Dealum applications match '{requested}' and latest cannot "
        f"be determined ({reason}): {names}."
    )
