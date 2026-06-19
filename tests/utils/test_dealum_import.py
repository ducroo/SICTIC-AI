import json

import pytest

from lib.startups.dealum import (
    DealumApplicationAmbiguousError,
    DealumApplicationNotFoundError,
    import_startup_from_dealum,
    reconcile_dealum_startup,
)
from lib.startups.sources import ensure_startup_dataset
from lib.datasets.state import archive_dataset, dataset_archived_marker_path
from lib.datasets.paths import dataset_location_for_domain
from lib.storage import get_storage
from lib.datasets.paths import dataset_raw_path


APPLICATION = {
    "id": 491739,
    "name": "Avientus",
    "code": "JHXM-QZHJ-8684",
    "step": "Jury",
    "tags": ["SUD2026", "AFR"],
    "contact": {
        "firstName": "Johannes",
        "lastName": "Aicher",
        "email": "johannes@avientus.ch",
    },
    "answers": {
        "oneliner": "The ETH Spin Off Avientus develops drone logistics technology.",
        "pitch_deck": "https://files.dealum.com/2026-05/token/Avientus_Deck.pdf",
        "sictic_financials": "https://files.dealum.com/2026-05/token/financialplan.xlsx",
    },
}


class FakeDealumAdapter:
    def __init__(self, application=APPLICATION, applications=None):
        self.application = application
        self.applications = applications if applications is not None else [application]
        self.dealroom_id = "19180"
        self.downloads = 0

    def is_configured(self):
        return True

    def list_applications(self):
        return self.applications

    def extract_file_links(self, application):
        from lib.adapters.dealum import DealumAdapter

        return DealumAdapter(api_key="x", dealroom_id="y").extract_file_links(application)

    def file_metadata(self, url):
        return {
            "url": url,
            "resolved_url": url,
            "content_type": "application/octet-stream",
            "content_length": "4",
            "etag": "same",
        }

    def download_file(self, url):
        self.downloads += 1
        return b"test", self.file_metadata(url)


def test_dealum_import_creates_dataset_and_manifest(mock_env):
    adapter = FakeDealumAdapter()

    result = import_startup_from_dealum("Avientus", adapter=adapter)

    storage = get_storage()
    assert result.imported is True
    assert result.changed is True
    assert result.dataset_slug == "avientus"
    assert result.dealum_name == "Avientus"
    assert result.dealum_id == 491739
    assert result.dealum_url == (
        "https://app.dealum.com/#/dealroom/19180?application=491739"
    )
    assert result.application_code == "JHXM-QZHJ-8684"
    assert result.match_method == "normalized_name"
    assert result.downloaded_files == 2
    assert storage.exists("storage/startups/avientus/datasets/dealum/application.md")
    assert storage.exists("storage/startups/avientus/datasets/dealum/documents/Avientus_Deck.pdf")
    assert storage.exists("storage/startups/avientus/datasets/__active_dataset__.md")

    manifest = json.loads(storage.read_text("storage/startups/avientus/datasets/dealum/manifest.json"))
    assert manifest["dealum_id"] == 491739
    assert manifest["dealum_url"] == (
        "https://app.dealum.com/#/dealroom/19180?application=491739"
    )
    assert manifest["step"] == "Jury"
    assert len(manifest["files"]) == 2
    application_md = storage.read_text(
        "storage/startups/avientus/datasets/dealum/application.md"
    )
    assert (
        "- Dealum URL: https://app.dealum.com/#/dealroom/19180?application=491739"
        in application_md
    )


def test_dealum_import_unchanged_skips_rewrite_and_preserves_manual_files(mock_env):
    adapter = FakeDealumAdapter()
    storage = get_storage()
    storage.write_text("storage/startups/avientus/datasets/manual-note.md", "manual")

    first = import_startup_from_dealum("Avientus", adapter=adapter)
    application_mtime = storage.mtime(first.application_path)
    second = import_startup_from_dealum("Avientus", adapter=adapter)

    assert second.changed is False
    assert second.downloaded_files == 0
    assert second.skipped_files == 2
    assert storage.exists("storage/startups/avientus/datasets/manual-note.md")
    assert storage.mtime(first.application_path) == application_mtime


def test_dealum_import_marks_removed_file_stale(mock_env):
    adapter = FakeDealumAdapter()
    import_startup_from_dealum("Avientus", adapter=adapter)

    changed_application = dict(APPLICATION)
    changed_application["answers"] = {
        "oneliner": APPLICATION["answers"]["oneliner"],
        "pitch_deck": APPLICATION["answers"]["pitch_deck"],
    }
    import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter(changed_application))

    manifest = json.loads(get_storage().read_text("storage/startups/avientus/datasets/dealum/manifest.json"))
    stale = [item for item in manifest["files"] if item.get("stale")]
    assert len(stale) == 1
    assert stale[0]["filename"] == "financialplan.xlsx"


@pytest.mark.asyncio
async def test_ensure_startup_dataset_no_dealum_env_is_noop(mock_env):
    status = await ensure_startup_dataset("MissingCo")

    assert status.dealum_configured is False
    assert status.dataset_exists is False
    assert not get_storage().exists(
        dataset_location_for_domain("missingco", "startups").raw_rel
    )


@pytest.mark.asyncio
async def test_ensure_startup_dataset_dealum_preflight_preserves_archive_state(
    mock_env,
    mocker,
):
    storage = get_storage()
    location = dataset_location_for_domain("avientus", "startups")
    storage.mkdir(location.raw_rel)
    archive_dataset("avientus")
    mocker.patch(
        "lib.startups.sources.DealumAdapter",
        return_value=FakeDealumAdapter(),
    )

    status = await ensure_startup_dataset(
        "Avientus",
        refresh_dealum=True,
        sync_after_import=False,
    )

    assert status.dealum_imported is True
    assert not storage.exists(location.active_marker_rel)
    assert storage.exists(dataset_archived_marker_path("avientus"))


def test_reconcile_dealum_startup_matches_normalized_name(mock_env, caplog):
    novoviz = {
        **APPLICATION,
        "id": 991,
        "name": "NovoViz",
        "code": "NOVO-991",
        "step": "Selected for pitching",
    }

    match = reconcile_dealum_startup(
        "novoviz",
        adapter=FakeDealumAdapter(novoviz),
    )

    assert match.matched_name == "NovoViz"
    assert match.dataset_slug == "novoviz"
    assert match.dealum_url == (
        "https://app.dealum.com/#/dealroom/19180?application=991"
    )
    assert match.match_method == "normalized_name"
    assert match.step == "Selected for pitching"
    assert "Matched requested='novoviz' to name='NovoViz'" in caplog.text


def test_reconcile_dealum_startup_matches_exact_application_code(mock_env):
    novoviz = {
        **APPLICATION,
        "id": 991,
        "name": "NovoViz",
        "code": "NOVO-991",
    }

    match = reconcile_dealum_startup(
        " novo-991 ",
        adapter=FakeDealumAdapter(novoviz),
    )

    assert match.matched_name == "NovoViz"
    assert match.match_method == "application_code"


def test_reconcile_dealum_startup_rejects_substring_match(mock_env):
    novoviz = {
        **APPLICATION,
        "name": "NovoViz Medical Imaging",
        "code": "NOVO-991",
    }

    with pytest.raises(DealumApplicationNotFoundError, match="No exact Dealum application match"):
        reconcile_dealum_startup(
            "novoviz",
            adapter=FakeDealumAdapter(novoviz),
        )


def test_reconcile_dealum_startup_selects_latest_duplicate_name(mock_env, caplog):
    applications = [
        {
            **APPLICATION,
            "id": 1,
            "name": "NovoViz",
            "code": "NOVO-1",
            "applicationDate": "2026-01-15T09:00:00Z",
        },
        {
            **APPLICATION,
            "id": 2,
            "name": "novoviz",
            "code": "NOVO-2",
            "applicationDate": "2026-04-20T09:00:00Z",
        },
    ]

    match = reconcile_dealum_startup(
        "novoviz",
        adapter=FakeDealumAdapter(applications=applications),
    )

    assert match.dealum_id == 2
    assert match.application_code == "NOVO-2"
    assert match.application_date == "2026-04-20T09:00:00Z"
    assert match.selection_method == "latest_application_date"
    assert "selected latest application id=2" in caplog.text


def test_reconcile_dealum_startup_selects_latest_duplicate_create_date_millis(mock_env):
    applications = [
        {
            **APPLICATION,
            "id": 1,
            "name": "NovoViz",
            "code": "NOVO-1",
            "createDate": 1774170000000,
        },
        {
            **APPLICATION,
            "id": 2,
            "name": "novoviz",
            "code": "NOVO-2",
            "createDate": 1776770000000,
        },
    ]

    match = reconcile_dealum_startup(
        "novoviz",
        adapter=FakeDealumAdapter(applications=applications),
    )

    assert match.dealum_id == 2
    assert match.application_code == "NOVO-2"
    assert match.application_date == "1776770000000"
    assert match.selection_method == "latest_application_date"


def test_reconcile_dealum_startup_rejects_duplicate_name_without_dates(mock_env, caplog):
    applications = [
        {**APPLICATION, "id": 1, "name": "NovoViz", "code": "NOVO-1"},
        {**APPLICATION, "id": 2, "name": "novoviz", "code": "NOVO-2"},
    ]

    with pytest.raises(DealumApplicationAmbiguousError, match="latest cannot be determined"):
        reconcile_dealum_startup(
            "novoviz",
            adapter=FakeDealumAdapter(applications=applications),
        )

    assert "Ambiguous exact match" in caplog.text


def test_dealum_import_manifest_records_selected_application_date(mock_env):
    applications = [
        {
            **APPLICATION,
            "id": 1,
            "name": "Avientus",
            "code": "OLD",
            "applicationDate": "2026-01-15T09:00:00Z",
        },
        {
            **APPLICATION,
            "id": 2,
            "name": "Avientus",
            "code": "NEW",
            "applicationDate": "2026-04-20T09:00:00Z",
        },
    ]

    result = import_startup_from_dealum(
        "Avientus",
        adapter=FakeDealumAdapter(applications=applications),
    )

    manifest = json.loads(get_storage().read_text(result.manifest_path))
    assert result.dealum_id == 2
    assert result.application_date == "2026-04-20T09:00:00Z"
    assert result.selection_method == "latest_application_date"
    assert manifest["dealum_id"] == 2
    assert manifest["application_date"] == "2026-04-20T09:00:00Z"
    assert manifest["selection_method"] == "latest_application_date"
