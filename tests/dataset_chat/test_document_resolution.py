from lib.datasets.documents import resolve_document_path
from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.storage import get_storage


def _create_startup_dataset(name: str) -> None:
    location = dataset_location_for_domain(name, "startups")
    storage = get_storage()
    storage.mkdir(location.raw_rel)
    storage.mkdir(location.parsed_rel)


def test_resolve_document_path_returns_best_match_and_score(mock_env):
    _create_startup_dataset("acme")
    location = dataset_location_for_domain("acme", "startups")
    storage = get_storage()
    storage.write_text(
        f"{location.parsed_rel}/legal/Shareholders Agreement 2025.pdf.md",
        "# Shareholders Agreement\n",
    )
    storage.write_text(
        f"{location.parsed_rel}/legal/Articles of Association.pdf.md",
        "# Articles\n",
    )
    manifest = IngestionManifest.load(storage, location.parsed_rel)
    manifest.documents = {
        "legal/Shareholders Agreement 2025.pdf": {},
        "legal/Articles of Association.pdf": {},
    }
    manifest.save()

    matched_path, score = resolve_document_path(
        "acme",
        "legal/shareholders agrement 2025.pdf",
    )
    exact_path, exact_score = resolve_document_path(
        "acme",
        "legal/Shareholders Agreement 2025.pdf",
    )

    assert matched_path == "legal/Shareholders Agreement 2025.pdf"
    assert 78 < score < 100
    assert exact_path == "legal/Shareholders Agreement 2025.pdf"
    assert exact_score == 100
