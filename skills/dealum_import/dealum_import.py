from __future__ import annotations

from lib.startups.dealum import DealumImportResult, import_startup_from_dealum


async def dealum_import(startup: str) -> DealumImportResult:
    return import_startup_from_dealum(startup)
