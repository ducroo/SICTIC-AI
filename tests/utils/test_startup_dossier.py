from lib.startups.dossier import STARTUP_DATASET_SUBDIRS, ensure_startup_dossier
from lib.startups.identity import canonical_startup_slug
from lib.storage import get_storage
from lib.datasets.paths import dataset_parsed_path, dataset_raw_path


def test_ensure_startup_dossier_creates_raw_and_parsed_layout(mock_env):
    slug = ensure_startup_dossier("Example Startup")
    storage = get_storage()

    assert slug == "example-startup"
    for root in (dataset_raw_path(slug), dataset_parsed_path(slug)):
        for subdir in STARTUP_DATASET_SUBDIRS:
            assert storage.is_dir(f"{root}/{subdir}")
    assert storage.exists(f"{dataset_raw_path(slug)}/__active_dataset__.md")


def test_canonical_startup_slug_uses_explicit_alias(mock_env):
    assert canonical_startup_slug("ExpertVision Ai") == "expertvision"
