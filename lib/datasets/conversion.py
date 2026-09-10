"""Reconcile dataset sources into parsed Markdown files."""

from __future__ import annotations

import asyncio

from lib.infrastructure.document_conversion import (
    DocumentConversion,
    SPREADSHEET_CONVERSION_MARKER,
    convert_document,
)
from lib.datasets.manifest import (
    MANIFEST_FILENAME,
    PARSER_VERSION,
    IngestionManifest,
    content_hash,
    ignored_parse_is_current as manifest_ignored_parse_is_current,
)
from lib.datasets.models import IngestionFailure, IngestionResult
from lib.datasets.spreadsheet_markdown import is_spreadsheet_filename
from lib.infrastructure.document_conversion.normalization import (
    requires_text_normalization,
)
from lib.datasets.source import (
    SourceDocument,
    parsed_filepath,
    snapshot_source_files,
)
from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.errors import InfrastructureError
from lib.infrastructure.logging import get_logger
from lib.slugify import slugify
from lib.storage import get_storage

logger = get_logger(__name__)


def spreadsheet_cache_is_current(
    storage,
    parsed_path: str,
    filename: str,
) -> bool:
    if not is_spreadsheet_filename(filename) or not storage.exists(parsed_path):
        return True
    try:
        return storage.read_text(parsed_path).startswith(
            SPREADSHEET_CONVERSION_MARKER
        )
    except Exception as error:
        logger.warning(
            "Failed to inspect spreadsheet cache %s: %s",
            parsed_path,
            error,
        )
        return False


def ignored_parse_is_current(
    source: SourceDocument,
    state: dict | None,
) -> bool:
    return manifest_ignored_parse_is_current(
        state,
        source_sha256=source.sha256,
    )


def _successful_parse_is_current(
    storage,
    parsed_path: str,
    source: SourceDocument,
    state: dict | None,
) -> bool:
    if (
        not state
        or state.get("source_sha256") != source.sha256
        or state.get("parser_version") != PARSER_VERSION
        or not storage.exists(parsed_path)
        or not spreadsheet_cache_is_current(
            storage,
            parsed_path,
            source.filename,
        )
    ):
        return False
    parsed_text = storage.read_text(parsed_path)
    return (
        not requires_text_normalization(parsed_text)
        and state.get("parsed_sha256") == content_hash(parsed_text)
    )


def _can_adopt_legacy_parse(
    storage,
    parsed_path: str,
    source: SourceDocument,
) -> bool:
    parsed_mtime = storage.mtime(parsed_path) or 0.0
    if not storage.exists(parsed_path):
        return False
    return (
        parsed_mtime >= source.mtime
        and not requires_text_normalization(storage.read_text(parsed_path))
        and spreadsheet_cache_is_current(
            storage,
            parsed_path,
            source.filename,
        )
    )


async def reconcile_conversions(
    dataset_name: str,
    raw_rel: str,
    parsed_rel: str,
    *,
    sources: list[SourceDocument] | None = None,
    manifest: IngestionManifest | None = None,
    result: IngestionResult | None = None,
) -> IngestionResult:
    """Reconcile source files to parsed Markdown using content hashes."""
    storage = get_storage()
    sources = sources or snapshot_source_files(storage, raw_rel)
    manifest = manifest or IngestionManifest.load(storage, parsed_rel)
    result = result or IngestionResult(dataset=slugify(dataset_name))
    source_names = {source.filename for source in sources}
    expected_parsed = {
        parsed_filepath(parsed_rel, source.filename).removeprefix(
            f"{parsed_rel}/"
        )
        for source in sources
    }

    for parsed_name, _mtime in storage.list_with_mtime(
        parsed_rel,
        recursive=True,
    ):
        if parsed_name == MANIFEST_FILENAME or parsed_name in expected_parsed:
            continue
        storage.remove(f"{parsed_rel}/{parsed_name}")
        result.removed_parsed += 1
        logger.info("[%s] Removed parsed orphan %s.", dataset_name, parsed_name)

    for filename in list(manifest.documents):
        if filename not in source_names:
            manifest.remove(filename)

    files_to_convert: list[dict] = []
    source_by_name = {source.filename: source for source in sources}
    for source in sources:
        parsed_path = parsed_filepath(parsed_rel, source.filename)
        state = manifest.documents.get(source.filename)

        if ignored_parse_is_current(source, state):
            continue
        if _successful_parse_is_current(
            storage,
            parsed_path,
            source,
            state,
        ):
            continue
        if state is None and _can_adopt_legacy_parse(
            storage,
            parsed_path,
            source,
        ):
            parsed_text = storage.read_text(parsed_path)
            manifest.documents[source.filename] = {
                "source_sha256": source.sha256,
                "source_mtime": source.mtime,
                "parsed_sha256": content_hash(parsed_text),
                "parser_version": PARSER_VERSION,
            }
            continue

        files_to_convert.append(
            {
                "filename": source.filename,
                "local_path": storage.local_path(
                    f"{raw_rel}/{source.filename}"
                ),
            }
        )

    files_to_convert.sort(key=lambda item: item["local_path"].stat().st_size)
    manifest.save()
    if not files_to_convert:
        logger.info("[%s] No source files require conversion.", dataset_name)
        return result

    logger.info(
        "[%s] Converting %s source documents.",
        dataset_name,
        len(files_to_convert),
    )
    completed = 0
    tasks = [
        asyncio.create_task(_convert_source(file_data))
        for file_data in files_to_convert
    ]
    for task in asyncio.as_completed(tasks):
        filename, conversion, conversion_error = await task
        completed += 1
        source = source_by_name[filename]
        state = manifest.state(filename)
        if conversion_error is not None and not _is_unsupported_format_error(
            conversion_error
        ):
            error_text = _short_error(conversion_error)
            state["attempted_source_sha256"] = source.sha256
            state["last_conversion_error"] = error_text
            result.failures.append(
                IngestionFailure(
                    filename=filename,
                    stage="conversion",
                    error=error_text,
                )
            )
            logger.error(
                "[%s] Conversion failed %s/%s for %s: %s",
                dataset_name,
                completed,
                len(files_to_convert),
                filename,
                error_text,
            )
        elif conversion_error is not None or not conversion.markdown:
            parsed_path = parsed_filepath(
                parsed_rel,
                filename,
            )
            if storage.exists(parsed_path):
                storage.remove(parsed_path)
                result.removed_parsed += 1
            state.clear()
            state.update(
                {
                    "source_sha256": source.sha256,
                    "source_mtime": source.mtime,
                    "parser_version": PARSER_VERSION,
                    "ignored_reason": _ignored_reason(
                        filename,
                        files_to_convert,
                        conversion_error,
                    ),
                }
            )
            result.ignored += 1
            logger.warning(
                "[%s] Ignored %s/%s with no extractable text: %s (%s)",
                dataset_name,
                completed,
                len(files_to_convert),
                filename,
                state["ignored_reason"],
            )
        else:
            parsed_path = parsed_filepath(
                parsed_rel,
                filename,
            )
            parsed_text = conversion.markdown
            storage.write_text(parsed_path, parsed_text)
            state.update(
                {
                    "source_sha256": source.sha256,
                    "source_mtime": source.mtime,
                    "parsed_sha256": content_hash(parsed_text),
                    "parser_version": PARSER_VERSION,
                }
            )
            state.pop("attempted_source_sha256", None)
            state.pop("last_conversion_error", None)
            result.converted += 1
            logger.info(
                "[%s] Converted %s/%s: %s",
                dataset_name,
                completed,
                len(files_to_convert),
                filename,
            )
            for warning in conversion.warnings:
                logger.warning(
                    "[%s] Conversion warning for %s: %s",
                    dataset_name,
                    filename,
                    warning,
                )
        manifest.save()
    return result


async def _convert_source(
    file_data: dict,
) -> tuple[str, DocumentConversion | None, Exception | None]:
    filename = file_data["filename"]
    path = file_data["local_path"]

    try:
        conversion = await convert_document(path)
        return filename, conversion, None
    except Exception as error:
        return filename, None, error


def _is_unsupported_format_error(error: Exception) -> bool:
    return (
        isinstance(error, InfrastructureError)
        and error.operation == "check_format"
    )


def _ignored_reason(
    filename: str,
    files_to_convert: list[dict],
    error: Exception | None,
) -> str:
    if error is not None:
        return "unsupported_format"
    path = next(
        item["local_path"]
        for item in files_to_convert
        if item["filename"] == filename
    )
    return "empty_source" if path.stat().st_size == 0 else "no_extractable_text"


def _short_error(error: Exception, limit: int = 500) -> str:
    text = str(error).replace("\n", " ").strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text
