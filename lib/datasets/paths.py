"""Dataset domain configuration, discovery, and path resolution."""

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
    if "domains" not in config:
        raise ValueError(f"{path}: missing required storage domain keys.")
    return config


def _domain_config(domain: str) -> Dict[str, Any]:
    config = storage_domain_config()
    domains = config["domains"]
    if domain not in domains:
        raise KeyError(f"Unknown storage domain: {domain}")
    return domains[domain]


def _resolve_path_template(template: str, slug: str) -> str:
    return template.format(dataset=slug, slug=slug).strip("/")


def _location_path(dconf: Dict[str, Any], key: str, slug: str) -> str:
    template_key = f"{key}_template"
    if template_key in dconf:
        return _resolve_path_template(dconf[template_key], slug)

    return slug


def dataset_location_for_domain(dataset_name: str, domain: str) -> DatasetLocation:
    """Construct a dataset location for creation in an explicit domain."""
    slug = slugify(dataset_name)
    dconf = _domain_config(domain)

    return DatasetLocation(
        name=dataset_name,
        slug=slug,
        domain=domain,
        dataset_path=_location_path(dconf, "dataset_path", slug),
        parsed_path=_location_path(dconf, "parsed_path", slug),
        insights_path=_location_path(dconf, "insights_path", slug),
        dataset_root=dconf["dataset_root"].strip("/"),
        parsed_root=dconf["parsed_root"].strip("/"),
        insights_root=dconf["insights_root"].strip("/"),
        active_marker=dconf.get("active_marker", "__active_dataset__.md"),
    )


def find_dataset_location(dataset_name: str) -> Optional[DatasetLocation]:
    """Find an existing dataset by its globally unique name."""
    storage = get_storage()
    matches = []
    for domain in iter_domains():
        location = dataset_location_for_domain(dataset_name, domain)
        if storage.is_dir(location.raw_rel):
            matches.append(location)

    if len(matches) > 1:
        locations = ", ".join(location.raw_rel for location in matches)
        raise ValueError(
            f"Dataset '{slugify(dataset_name)}' exists in multiple domains: {locations}"
        )
    return matches[0] if matches else None


def dataset_location(dataset_name: str) -> DatasetLocation:
    location = find_dataset_location(dataset_name)
    if location is None:
        roots = ", ".join(
            _domain_config(domain)["dataset_root"].strip("/")
            for domain in iter_domains()
        )
        raise FileNotFoundError(
            f"Dataset '{slugify(dataset_name)}' was not found under: {roots}"
        )
    return location


def dataset_raw_path(dataset_name: str) -> str:
    return dataset_location(dataset_name).raw_rel


def dataset_parsed_path(dataset_name: str) -> str:
    return dataset_location(dataset_name).parsed_rel


def dataset_insights_path(dataset_name: str) -> str:
    return dataset_location(dataset_name).insights_rel


def dataset_active_marker_path(dataset_name: str) -> str:
    return dataset_location(dataset_name).active_marker_rel


def list_dataset_names(domain: str) -> list[str]:
    dconf = _domain_config(domain)
    root = dconf["dataset_root"].strip("/")
    storage = get_storage()
    if not storage.exists(root):
        return []
    return [
        item
        for item in storage.list(root)
        if storage.is_dir(
            dataset_location_for_domain(item, domain).raw_rel
        )
    ]


def list_all_dataset_names(
    domains: Iterable[str] | None = None,
) -> list[str]:
    """Return all present dataset names across configured storage domains."""
    selected_domains = domains or iter_domains()
    return sorted(
        {
            slugify(name)
            for domain in selected_domains
            for name in list_dataset_names(domain)
        }
    )


def iter_domains() -> Iterable[str]:
    return storage_domain_config()["domains"].keys()
