from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from lib.env import get_env_var
from lib.slugify import slugify


@lru_cache(maxsize=1)
def startup_aliases() -> dict[str, str]:
    path = Path(get_env_var("REPO_PATH")) / "config" / "startup_aliases.json"
    if not path.exists():
        return {}
    aliases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(aliases, dict):
        raise ValueError(f"{path}: expected an object of startup slug aliases")
    return {slugify(source): slugify(target) for source, target in aliases.items()}


def canonical_startup_slug(startup: str) -> str:
    slug = slugify(startup)
    aliases = startup_aliases()
    seen = set()
    while slug in aliases:
        if slug in seen:
            raise ValueError(f"Circular startup alias involving {slug!r}")
        seen.add(slug)
        slug = aliases[slug]
    return slug
