"""Access to a dataset's parsed documents for cap-table/CLA analysis."""

from __future__ import annotations

from dataclasses import dataclass

from lib.datasets.paths import dataset_parsed_path, dataset_raw_path
from lib.datasets.source import parsed_filepath, snapshot_source_files
from lib.infrastructure.logging import get_logger
from lib.storage import get_storage

logger = get_logger(__name__)


@dataclass(frozen=True)
class ParsedDocument:
    """One source document together with its parsed Markdown text."""

    filename: str
    text: str


def normalize_for_matching(text: str) -> str:
    """Collapse whitespace so OCR quotes can be matched robustly."""
    return " ".join(text.split())


def load_parsed_documents(dataset_name: str) -> list[ParsedDocument]:
    """Return every source document of the dataset with its parsed text.

    Documents whose parsed Markdown does not exist (parse failures or a sync
    that has not run yet) are skipped with a warning rather than failing the
    whole run.
    """
    storage = get_storage()
    raw_rel = dataset_raw_path(dataset_name)
    parsed_rel = dataset_parsed_path(dataset_name)
    documents: list[ParsedDocument] = []
    for source in snapshot_source_files(storage, raw_rel):
        parsed_path = parsed_filepath(parsed_rel, source.filename)
        if not storage.exists(parsed_path):
            logger.warning(
                "[%s] No parsed text for %r; run a dataset sync first.",
                dataset_name,
                source.filename,
            )
            continue
        documents.append(
            ParsedDocument(
                filename=source.filename,
                text=storage.read_text(parsed_path),
            )
        )
    if not documents:
        raise ValueError(
            f"Dataset {dataset_name!r} has no parsed documents; "
            "run a dataset sync first."
        )
    return documents
