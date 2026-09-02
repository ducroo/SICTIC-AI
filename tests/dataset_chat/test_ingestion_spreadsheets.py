from types import SimpleNamespace

from lib.datasets.conversion import spreadsheet_cache_is_current
from lib.infrastructure.document_conversion import (
    SPREADSHEET_CONVERSION_MARKER,
)


def test_legacy_spreadsheet_cache_is_stale():
    storage = SimpleNamespace(
        exists=lambda _path: True,
        read_text=lambda _path: "| old Docling output |\n",
    )

    assert spreadsheet_cache_is_current(storage, "model.xlsx.md", "model.xlsx") is False


def test_previous_compact_spreadsheet_cache_is_stale():
    storage = SimpleNamespace(
        exists=lambda _path: True,
        read_text=lambda _path: (
            "<!-- sictic-spreadsheet: compact-values-v1 -->\n\n## Sheet\n"
        ),
    )

    assert spreadsheet_cache_is_current(storage, "model.xlsx.md", "model.xlsx") is False


def test_unrounded_compact_spreadsheet_cache_is_stale():
    storage = SimpleNamespace(
        exists=lambda _path: True,
        read_text=lambda _path: (
            "<!-- sictic-spreadsheet: compact-values-v2 -->\n\n## Sheet\n"
        ),
    )

    assert spreadsheet_cache_is_current(storage, "model.xlsx.md", "model.xlsx") is False


def test_current_spreadsheet_conversion_cache_is_current():
    storage = SimpleNamespace(
        exists=lambda _path: True,
        read_text=lambda _path: (
            f"{SPREADSHEET_CONVERSION_MARKER}\n\n## Sheet\n"
        ),
    )

    assert spreadsheet_cache_is_current(storage, "model.xlsx.md", "model.xlsx") is True


def test_non_spreadsheet_cache_does_not_require_marker():
    storage = SimpleNamespace(
        exists=lambda _path: True,
        read_text=lambda _path: "| ordinary PDF markdown |\n",
    )

    assert spreadsheet_cache_is_current(storage, "report.pdf.md", "report.pdf") is True
