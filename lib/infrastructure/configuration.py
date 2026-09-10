"""Access repository configuration and environment variables."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Final, Literal, overload

from dotenv import load_dotenv

from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)
logger = logging.getLogger(__name__)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DOTENV_PATH: Final[Path] = _REPO_ROOT / ".env"

if _DOTENV_PATH.exists():
    load_dotenv(_DOTENV_PATH, override=True)


@overload
def get_env_var(name: str, *, required: Literal[True] = True) -> str: ...


@overload
def get_env_var(name: str, *, required: Literal[False]) -> str | None: ...


def get_env_var(name: str, *, required: bool = True) -> str | None:
    """Return an environment variable, treating blank values as absent."""
    value = os.environ.get(name)
    if value is not None:
        value = value.strip()
    if value:
        return value
    if required:
        raise InfrastructureError(
            f"Required environment variable {name!r} is missing or empty",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="environment",
            operation="read_variable",
        )
    return None


def config_cache_key(*sections: object) -> str:
    """Return a stable cache key for effective configuration sections."""
    return json.dumps(
        sections,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _repo_root() -> Path:
    return Path(get_env_var("REPO_PATH")).expanduser()


def _source_dir() -> Path:
    return _repo_root() / "config"


def _local_data_root() -> Path:
    configured = os.environ.get("LOCAL_DATA_PATH") or get_env_var("REPO_PATH")
    root = Path(configured).expanduser()
    if not root.is_absolute():
        raise InfrastructureError(
            f"LOCAL_DATA_PATH must be absolute, got: {configured}",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="environment",
            operation="resolve_local_data_path",
        )
    return root


def _local_cache_paths() -> tuple[Path, Path]:
    """Return the directory and file used for compiled configuration."""
    cache_dir = _local_data_root() / "cache"
    return cache_dir, cache_dir / "config.json"


def _configuration_error(message: str) -> InfrastructureError:
    return InfrastructureError(
        message,
        kind=InfrastructureErrorKind.CONFIGURATION,
        provider="repository",
        operation="load_configuration",
    )


def _build_tree_from_local_files(
    config_files: list[Path],
    source_dir: Path,
) -> dict[str, Any]:
    """Build a nested configuration tree from Markdown and JSON files."""
    tree: dict[str, Any] = {}
    for filepath in sorted(config_files):
        try:
            relpath = filepath.relative_to(source_dir)
        except ValueError:
            logger.warning(
                "File %s is not relative to %s. Skipping.",
                filepath,
                source_dir,
            )
            continue

        cur = tree
        for segment in relpath.parts[:-1]:
            existing = cur.get(segment)
            if not isinstance(existing, dict):
                existing = {}
                cur[segment] = existing
            cur = existing

        stem = filepath.stem
        if stem in cur:
            raise _configuration_error(
                f"Duplicate configuration key {stem!r} from {filepath}"
            )

        try:
            content = filepath.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise _configuration_error(
                f"Failed to read configuration file {filepath}: {error}"
            ) from error

        if filepath.suffix == ".json":
            try:
                cur[stem] = json.loads(content)
            except json.JSONDecodeError as error:
                raise _configuration_error(
                    f"Invalid JSON configuration file {filepath}: {error}"
                ) from error
        else:
            cur[stem] = content

    return tree


def _load_configuration_tree() -> dict[str, Any]:
    source_dir = _source_dir()
    cache_dir, cache_file = _local_cache_paths()

    if not source_dir.is_dir():
        raise _configuration_error(
            f"Cannot find repository configuration directory at {source_dir}"
        )

    config_files = [
        path
        for pattern in ("*.md", "*.json")
        for path in source_dir.rglob(pattern)
    ]
    if not config_files:
        raise _configuration_error(
            f"No configuration files found in {source_dir}"
        )

    latest_source_mtime = max(path.stat().st_mtime for path in config_files)
    if cache_file.exists() and cache_file.stat().st_mtime >= latest_source_mtime:
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                return cached
            logger.warning("Compiled configuration cache is not an object; rebuilding")
        except (OSError, json.JSONDecodeError) as error:
            logger.warning(
                "Failed to load compiled configuration cache: %s; rebuilding",
                error,
            )

    config_data = _build_tree_from_local_files(config_files, source_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        cache_file.write_text(
            json.dumps(config_data, indent=4),
            encoding="utf-8",
        )
        logger.info(
            "Rebuilt configuration cache from %d local files",
            len(config_files),
        )
    except OSError as error:
        logger.warning("Failed to write compiled configuration cache: %s", error)

    return config_data


def load_repository_config(*sections: str) -> Any:
    """Load the complete configuration tree or one nested configuration path."""
    value: Any = _load_configuration_tree()
    traversed: list[str] = []
    for section in sections:
        traversed.append(section)
        if not isinstance(value, dict) or section not in value:
            path = ".".join(traversed)
            raise _configuration_error(
                f"Configuration section {path!r} does not exist"
            )
        value = value[section]
    return value
