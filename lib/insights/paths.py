from pathlib import PurePosixPath

from lib.datasets.paths import dataset_location
from lib.slugify import slugify

MANIFEST_FILENAME = ".insight-manifest.json"


def model_slug(model: str) -> str:
    return slugify(model.split("/")[-1])


def insight_directory(dataset: str, skill: str, *, subdir: bool) -> str:
    root = dataset_location(dataset).insights_rel
    return f"{root}/{slugify(skill)}" if subdir else root


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
