from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from lib.env import get_env_var
from lib.slugify import slugify
from lib.storage import get_storage


@dataclass(frozen=True)
class DatasetLocation:
    name: str
    slug: str
    domain: str
    dataset_path: str
    parsed_path: str
    insights_path: str
    dataset_root: str
    parsed_root: str
    insights_root: str
    active_marker: str = "__active_dataset__.md"

    @property
    def raw_rel(self) -> str:
        return f"{self.dataset_root}/{self.dataset_path}".strip("/")

    @property
    def parsed_rel(self) -> str:
        return f"{self.parsed_root}/{self.parsed_path}".strip("/")

    @property
    def insights_rel(self) -> str:
        return f"{self.insights_root}/{self.insights_path}".strip("/")

    @property
    def active_marker_rel(self) -> str:
        return f"{self.raw_rel}/{self.active_marker}"


def _config_path() -> Path:
    return Path(get_env_var("REPO_PATH")) / "config" / "storage_domains.json"


@lru_cache(maxsize=1)
def storage_domain_config() -> Dict[str, Any]:
    path = _config_path()
    with path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    if "domains" not in config or "default_domain" not in config:
        raise ValueError(f"{path}: missing required storage domain keys.")
    return config


def reset_storage_domain_config() -> None:
    storage_domain_config.cache_clear()


def _domain_config(domain: str) -> Dict[str, Any]:
    config = storage_domain_config()
    domains = config["domains"]
    if domain not in domains:
        raise KeyError(f"Unknown storage domain: {domain}")
    return domains[domain]


def _resolve_path_template(template: str, slug: str) -> str:
    return template.format(dataset=slug, slug=slug).strip("/")


def _location_path(entry: Dict[str, Any], dconf: Dict[str, Any], key: str, slug: str) -> str:
    legacy_path = entry.get("path") or slug
    if key in entry:
        return entry[key].strip("/")

    template_key = f"{key}_template"
    if template_key in entry:
        return _resolve_path_template(entry[template_key], slug)
    if template_key in dconf:
        return _resolve_path_template(dconf[template_key], legacy_path.strip("/"))

    return legacy_path.strip("/")


def dataset_location(dataset_name: str, *, domain: Optional[str] = None) -> DatasetLocation:
    config = storage_domain_config()
    slug = slugify(dataset_name)

    explicit = config.get("datasets", {}).get(slug)
    derived = config.get("derived_datasets", {}).get(slug)
    entry = explicit or derived or {}

    resolved_domain = domain or entry.get("domain") or config["default_domain"]
    dconf = _domain_config(resolved_domain)
    dataset_path = _location_path(entry, dconf, "dataset_path", slug)
    parsed_path = _location_path(entry, dconf, "parsed_path", slug)
    insights_path = _location_path(entry, dconf, "insights_path", slug)

    return DatasetLocation(
        name=dataset_name,
        slug=slug,
        domain=resolved_domain,
        dataset_path=dataset_path,
        parsed_path=parsed_path,
        insights_path=insights_path,
        dataset_root=dconf["dataset_root"].strip("/"),
        parsed_root=dconf["parsed_root"].strip("/"),
        insights_root=dconf["insights_root"].strip("/"),
        active_marker=dconf.get("active_marker", "__active_dataset__.md"),
    )


def dataset_raw_path(dataset_name: str, *, domain: Optional[str] = None) -> str:
    return dataset_location(dataset_name, domain=domain).raw_rel


def dataset_parsed_path(dataset_name: str, *, domain: Optional[str] = None) -> str:
    return dataset_location(dataset_name, domain=domain).parsed_rel


def dataset_insights_path(dataset_name: str, *, domain: Optional[str] = None) -> str:
    return dataset_location(dataset_name, domain=domain).insights_rel


def dataset_active_marker_path(dataset_name: str, *, domain: Optional[str] = None) -> str:
    return dataset_location(dataset_name, domain=domain).active_marker_rel


def list_dataset_names(domain: str) -> list[str]:
    dconf = _domain_config(domain)
    root = dconf["dataset_root"].strip("/")
    storage = get_storage()
    if not storage.exists(root):
        return []
    return [
        item
        for item in storage.list(root)
        if storage.is_dir(f"{root}/{item}")
    ]


def iter_domains() -> Iterable[str]:
    return storage_domain_config()["domains"].keys()
