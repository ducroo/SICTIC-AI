"""Resolve stages and update markers for the candidate bulk-refresh scope."""

from lib.datasets.paths import find_dataset_location
from lib.datasets.state import activate_dataset, archive_dataset, is_active_dataset, is_archived_dataset, update_dataset_inactivity
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.dealum import DealumAdapter
from lib.infrastructure.logging import get_logger
from lib.startups.dealum import DealumApplicationNotFoundError, import_startup_from_dealum, reconcile_dealum_startup
from lib.startups.dealum.session import current_session, list_applications
from lib.startups.dealum.stages import ALWAYS_ACTIVE_STAGES, canonical_stage
from lib.startups.identity import canonical_startup_slug
from lib.startups.dossier import ensure_startup_dossier

logger = get_logger(__name__)


def update_dataset_states(
    names: tuple[str, ...], *, discover: bool, excluded: set[str],
) -> tuple[tuple[str, ...], dict[str, str | None], dict[str, str]]:
    """Return candidate names, resolved stages and isolated acquisition/state errors.

    None denotes a successful no-match (or a community dataset), never an API failure.
    """
    names = list(names)
    stages: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    imports: list[str] = []
    adapter = DealumAdapter()
    applications = None
    lookup_error = None
    if discover or any(
        (location := find_dataset_location(name)) is None or location.domain == "startups"
        for name in names
    ):
        try:
            if not adapter.is_configured():
                raise ValueError("Dealum is not configured; startup stages cannot be determined")
            applications = list_applications(adapter)
        except Exception as error:
            lookup_error = str(error)
            if discover:
                errors["Dealum discovery"] = lookup_error

    if discover and applications is not None:
        for application in applications:
            name = str(application.get("name") or "").strip()
            if not name:
                continue
            slug = canonical_startup_slug(name)
            if slug in names or slug in excluded or find_dataset_location(slug) is not None:
                continue
            # Selection still belongs to the shared matcher (latest application/ties).
            try:
                match = reconcile_dealum_startup(name, adapter=adapter, applications=applications)
                stage = canonical_stage(match.step)
                if stage in ALWAYS_ACTIVE_STAGES:
                    names.append(slug)
            except Exception as error:
                errors[slug] = str(error)

    months = load_repository_config("bulk_refresh", "lifecycle")["inactivity_months"]
    for name in names:
        location = find_dataset_location(name)
        try:
            if location is not None and location.domain == "community":
                stages[name] = None
                update_dataset_inactivity(name, months=months)
                continue
            if lookup_error:
                raise ValueError(lookup_error)
            lookup = name
            try:
                match = reconcile_dealum_startup(lookup, adapter=adapter, applications=applications)
            except DealumApplicationNotFoundError:
                if location is None:
                    raise ValueError(f"Missing dossier '{name}' has no matching Dealum application")
                stages[name] = None
                update_dataset_inactivity(name, months=months)
            else:
                stage = canonical_stage(match.step)
                stages[name] = stage
                if location is None and stage not in ALWAYS_ACTIVE_STAGES:
                    raise ValueError(
                        f"Missing dossier '{name}' cannot be created for stage '{stage}'"
                    )
                if location is not None and is_archived_dataset(name):
                    archive_dataset(name)
                elif stage in ALWAYS_ACTIVE_STAGES:
                    if location is None:
                        ensure_startup_dossier(name, activate=True)
                    else:
                        activate_dataset(name)
                else:
                    update_dataset_inactivity(name, months=months)

                # Activity is decided from the current local data before acquiring
                # anything. Downloads cannot extend the life of an expired dossier.
                if not is_active_dataset(name) or stage == "Application":
                    session = current_session()
                    if session is not None:
                        session.source_imports_disabled.add(name)
                        session.checked.add(name)
                    continue
                imports.append(lookup)
            session = current_session()
            if session is not None:
                session.checked.add(name)
                if is_archived_dataset(name):
                    session.source_imports_disabled.add(name)
        except Exception as error:
            logger.exception("[%s] Dataset state/source update failed", name)
            errors[name] = str(error)
    # All candidate states have now been decided. Only active, non-Application
    # dossiers are hydrated, including newly created ones.
    for name in imports:
        try:
            import_startup_from_dealum(
                name, adapter=adapter, applications=applications, activate=False,
            )
        except Exception as error:
            logger.exception("[%s] Dataset source acquisition failed", name)
            errors[name] = str(error)
    return tuple(names), stages, errors
