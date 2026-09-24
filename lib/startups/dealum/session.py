"""Run-scoped Dealum snapshots shared by composed bulk workflows."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from lib.infrastructure.dealum import DealumAdapter

if TYPE_CHECKING:
    from lib.startups.dealum.importing import DealumImportResult


@dataclass
class DealumSession:
    applications: list[dict[str, Any]] | None = None
    imports: dict[tuple[str, bool], "DealumImportResult"] = field(default_factory=dict)
    checked: set[str] = field(default_factory=set)
    source_imports_disabled: set[str] = field(default_factory=set)


_session: ContextVar[DealumSession | None] = ContextVar("dealum_session", default=None)


def current_session() -> DealumSession | None:
    return _session.get()


@contextmanager
def dealum_session():
    token = _session.set(DealumSession())
    try:
        yield _session.get()
    finally:
        _session.reset(token)


def list_applications(adapter: DealumAdapter) -> list[dict[str, Any]]:
    session = current_session()
    if session is None:
        return adapter.list_applications()
    if session.applications is None:
        session.applications = adapter.list_applications()
    return session.applications
