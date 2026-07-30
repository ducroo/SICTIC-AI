from pathlib import PurePosixPath
import re

from lib.datasets.paths import dataset_location
from lib.slugify import slugify

MANIFEST_FILENAME = ".insight-manifest.json"


def model_slug(model: str) -> str:
    return slugify(model.split("/")[-1])


def insight_directory(
    dataset: str,
    skill: str,
    *,
    subdir: bool,
    run_id: str | None = None,
) -> str:
    root = dataset_location(dataset).insights_rel
    directory = f"{root}/{slugify(skill)}" if subdir else root
    if run_id is None:
        return directory
    if not subdir:
        raise ValueError("run_id requires subdir=True.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        raise ValueError(f"Invalid insight run identifier: {run_id!r}")
    return f"{directory}/{run_id}"


def insight_filename(
    dataset: str,
    skill: str,
    model: str,
    *,
    identifier: str | None,
    subdir: bool,
) -> str:
    identity = identifier or dataset
    core = slugify(f"{identity}-{model_slug(model)}")
    if subdir:
        return f"{core}.md"
    return f"{slugify(skill)}-{core}.md"


def insight_base(
    dataset: str,
    skill: str,
    *,
    identifier: str | None,
    subdir: bool,
) -> str:
    identity = slugify(identifier or dataset)
    return identity if subdir else f"{slugify(skill)}-{identity}"


def insight_manifest_path(dataset: str) -> str:
    location = dataset_location(dataset)
    parsed_dataset_root = str(PurePosixPath(location.parsed_rel).parent)
    return f"{parsed_dataset_root}/insights/{MANIFEST_FILENAME}"
