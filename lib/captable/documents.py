"""Access to a dataset's parsed documents for cap-table/CLA analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lib.datasets.paths import dataset_parsed_path, dataset_raw_path
from lib.datasets.source import list_source_files, parsed_filepath
from lib.infrastructure.logging import get_logger
from lib.storage import get_storage

logger = get_logger(__name__)


@dataclass(frozen=True)
class ParsedDocument:
    """One source document together with its parsed Markdown text."""

    filename: str
    text: str


def normalize_for_matching(text: str) -> str:
    """Project text to a bare alphanumeric stream for quote matching.

    Robust against markdown table pipes the model drops when quoting,
    punctuation/OCR wobble, and intra-word spacing artifacts ("E m i l"
    for "Hakan"). The original quote text is what gets stored; this
    projection is only used to confirm the quote exists in the document.
    """
    return re.sub(r"[^0-9a-zA-ZÀ-ɏ]+", "", text).casefold()


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
    for filename, _mtime in list_source_files(storage, raw_rel):
        parsed_path = parsed_filepath(parsed_rel, filename)
        if not storage.exists(parsed_path):
            logger.warning(
                "[%s] No parsed text for %r; run a dataset sync first.",
                dataset_name,
                filename,
            )
            continue
        documents.append(
            ParsedDocument(
                filename=filename,
                text=storage.read_text(parsed_path),
            )
        )
    if not documents:
        raise ValueError(
            f"Dataset {dataset_name!r} has no parsed documents; "
            "run a dataset sync first."
        )
    return documents
