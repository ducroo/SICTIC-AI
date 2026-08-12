"""Reconcile dataset sources into parsed Markdown files."""

from __future__ import annotations

from lib.adapters.docling import (
    ConversionStatus,
    DoclingAdapter,
    SPREADSHEET_MARKDOWN_MARKER,
    is_spreadsheet_filename,
)
from lib.datasets.manifest import (
    MANIFEST_FILENAME,
    PARSER_VERSION,
    IngestionManifest,
    content_hash,
    ignored_parse_is_current as manifest_ignored_parse_is_current,
)
from lib.datasets.models import IngestionFailure, IngestionResult
from lib.datasets.text_normalization import (
    normalize_extracted_text,
    requires_text_normalization,
)
from lib.datasets.source import (
    SourceDocument,
    parsed_filepath,
    snapshot_source_files,
)
from lib.env import get_env_var
from lib.logger import get_logger
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
            SPREADSHEET_MARKDOWN_MARKER
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

    manifest.save()
    if not files_to_convert:
        logger.info("[%s] No source files require conversion.", dataset_name)
        return result

    logger.info(
        "[%s] Converting %s source documents.",
        dataset_name,
        len(files_to_convert),
    )
    try:
        max_concurrent = int(get_env_var("OLLAMA_NUM_PARALLEL"))
    except Exception:
        max_concurrent = 10

    docling = DoclingAdapter(concurrency_limit=max_concurrent)
    completed = 0
    async for conversion in docling.extract_documents(files_to_convert):
        completed += 1
        source = source_by_name[conversion.filename]
        state = manifest.state(conversion.filename)
        if conversion.status is ConversionStatus.FAILED:
            state["attempted_source_sha256"] = source.sha256
            state["last_conversion_error"] = conversion.error
            result.failures.append(
                IngestionFailure(
                    filename=conversion.filename,
                    stage="conversion",
                    error=conversion.error,
                )
            )
            logger.error(
                "[%s] Conversion failed %s/%s for %s: %s",
                dataset_name,
                completed,
                len(files_to_convert),
                conversion.filename,
                conversion.error,
            )
        elif conversion.status is ConversionStatus.IGNORED_EMPTY:
            parsed_path = parsed_filepath(
                parsed_rel,
                conversion.filename,
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
                    "ignored_reason": (
                        conversion.reason or "no_extractable_text"
                    ),
                }
            )
            result.ignored += 1
            logger.warning(
                "[%s] Ignored %s/%s with no extractable text: %s (%s)",
                dataset_name,
                completed,
                len(files_to_convert),
                conversion.filename,
                state["ignored_reason"],
            )
        else:
            parsed_path = parsed_filepath(
                parsed_rel,
                conversion.filename,
            )
            parsed_text = normalize_extracted_text(conversion.text)
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
                conversion.filename,
            )
        manifest.save()
    return result
