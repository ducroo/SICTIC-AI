from types import SimpleNamespace

from lib.adapters.docling import SPREADSHEET_MARKDOWN_MARKER
from lib.datasets.conversion import spreadsheet_cache_is_current


def test_legacy_spreadsheet_cache_is_stale():
    storage = SimpleNamespace(
        exists=lambda _path: True,
        read_text=lambda _path: "| old Docling output |\n",
    )

    assert spreadsheet_cache_is_current(storage, "model.xlsx.md", "model.xlsx") is False


def test_versioned_spreadsheet_cache_is_current():
    storage = SimpleNamespace(
        exists=lambda _path: True,
        read_text=lambda _path: f"{SPREADSHEET_MARKDOWN_MARKER}\n\n## Sheet\n",
    )

    assert spreadsheet_cache_is_current(storage, "model.xlsx.md", "model.xlsx") is True


def test_non_spreadsheet_cache_does_not_require_marker():
    storage = SimpleNamespace(
        exists=lambda _path: True,
        read_text=lambda _path: "| ordinary PDF markdown |\n",
    )

    assert spreadsheet_cache_is_current(storage, "report.pdf.md", "report.pdf") is True
