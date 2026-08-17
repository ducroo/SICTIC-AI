import json

import pytest

from lib.startups.dealum import (
    DealumApplicationAmbiguousError,
    DealumApplicationNotFoundError,
    import_startup_from_dealum,
    reconcile_dealum_startup,
)
from lib.startups.dealum.manifest import LAST_SUCCESSFUL_PULL_AT
from lib.startups.sources import _dealum_sync_due, ensure_startup_dataset
from lib.datasets.source import snapshot_source_files
from lib.datasets.state import archive_dataset, dataset_archived_marker_path
from lib.datasets.paths import dataset_location_for_domain
from lib.storage import get_storage


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


def test_dealum_file_link_keeps_apostrophes_in_filename():
    application = {
        "answers": {
            "pitch_deck": (
                "https://files.dealum.com/2026-01/token/"
                "PROUD's%20pitch%20deck.pdf"
            )
        }
    }

    links = FakeDealumAdapter(application=application).extract_file_links(application)

    assert len(links) == 1
    assert links[0].url.endswith("PROUD's%20pitch%20deck.pdf")
    assert links[0].filename == "PROUD-s pitch deck.pdf"


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


def test_dealum_import_unchanged_replaces_snapshot_and_preserves_manual_files(
    mock_env,
    mocker,
):
    adapter = FakeDealumAdapter()
    storage = get_storage()
    storage.write_text("storage/startups/avientus/datasets/manual-note.md", "manual")
    mock_time = mocker.patch(
        "lib.startups.dealum.importing._successful_pull_time",
        side_effect=[100, 200],
    )

    first = import_startup_from_dealum("Avientus", adapter=adapter)
    first_manifest = json.loads(storage.read_text(first.manifest_path))
    first_sources = [
        (source.filename, source.sha256)
        for source in snapshot_source_files(
            storage,
            dataset_location_for_domain("avientus", "startups").raw_rel,
        )
    ]
    second = import_startup_from_dealum("Avientus", adapter=adapter)
    second_manifest = json.loads(storage.read_text(second.manifest_path))
    second_sources = [
        (source.filename, source.sha256)
        for source in snapshot_source_files(
            storage,
            dataset_location_for_domain("avientus", "startups").raw_rel,
        )
    ]

    assert second.changed is False
    assert second.downloaded_files == 2
    assert second.skipped_files == 0
    assert adapter.downloads == 4
    assert first_manifest[LAST_SUCCESSFUL_PULL_AT] == 100
    assert second_manifest[LAST_SUCCESSFUL_PULL_AT] == 200
    assert first_manifest["snapshot_hash"] == second_manifest["snapshot_hash"]
    assert first_sources == second_sources
    assert storage.exists("storage/startups/avientus/datasets/manual-note.md")
    assert mock_time.call_count == 2


def test_dealum_import_removes_files_deleted_from_dealum(mock_env):
    adapter = FakeDealumAdapter()
    import_startup_from_dealum("Avientus", adapter=adapter)

    changed_application = dict(APPLICATION)
    changed_application["answers"] = {
        "oneliner": APPLICATION["answers"]["oneliner"],
        "pitch_deck": APPLICATION["answers"]["pitch_deck"],
    }
    result = import_startup_from_dealum(
        "Avientus",
        adapter=FakeDealumAdapter(changed_application),
    )

    manifest = json.loads(
        get_storage().read_text(
            "storage/startups/avientus/datasets/dealum/manifest.json"
        )
    )
    assert result.changed is True
    assert result.stale_files == 1
    assert len(manifest["files"]) == 1
    assert manifest["files"][0]["filename"] == "Avientus_Deck.pdf"
    assert not get_storage().exists(
        "storage/startups/avientus/datasets/dealum/documents/"
        "financialplan.xlsx"
    )


def test_dealum_import_failure_preserves_previous_snapshot_and_timestamp(
    mock_env,
    mocker,
):
    storage = get_storage()
    mocker.patch(
        "lib.startups.dealum.importing._successful_pull_time",
        return_value=100,
    )
    first = import_startup_from_dealum(
        "Avientus",
        adapter=FakeDealumAdapter(),
    )
    previous_manifest = storage.read_text(first.manifest_path)
    previous_application = storage.read_text(first.application_path)

    class FailingAdapter(FakeDealumAdapter):
        def download_file(self, url):
            if url.endswith("financialplan.xlsx"):
                raise RuntimeError("attachment download failed")
            return super().download_file(url)

    changed_application = {
        **APPLICATION,
        "answers": {
            **APPLICATION["answers"],
            "oneliner": "This update must not be installed partially.",
        },
    }
    with pytest.raises(RuntimeError, match="attachment download failed"):
        import_startup_from_dealum(
            "Avientus",
            adapter=FailingAdapter(changed_application),
        )

    assert storage.read_text(first.manifest_path) == previous_manifest
    assert storage.read_text(first.application_path) == previous_application
    assert storage.exists(
        "storage/startups/avientus/datasets/dealum/documents/"
        "financialplan.xlsx"
    )


def test_dealum_stage_and_operational_dates_do_not_change_snapshot(
    mock_env,
):
    first = import_startup_from_dealum(
        "Avientus",
        adapter=FakeDealumAdapter(),
    )
    changed_application = {
        **APPLICATION,
        "step": "Under review",
        "moveDate": 1_999_999_999_000,
        "reviewDate": 1_999_999_999_001,
    }

    second = import_startup_from_dealum(
        "Avientus",
        adapter=FakeDealumAdapter(changed_application),
    )

    assert first.changed is True
    assert second.changed is False
    application_md = get_storage().read_text(second.application_path)
    assert "- Step:" not in application_md
    manifest = json.loads(get_storage().read_text(second.manifest_path))
    assert manifest["step"] == "Under review"


def test_dealum_rotated_attachment_url_does_not_change_snapshot(
    mock_env,
):
    import_startup_from_dealum(
        "Avientus",
        adapter=FakeDealumAdapter(),
    )
    changed_application = {
        **APPLICATION,
        "answers": {
            **APPLICATION["answers"],
            "pitch_deck": (
                "https://files.dealum.com/rotated-token/"
                "Avientus_Deck.pdf"
            ),
        },
    }

    second = import_startup_from_dealum(
        "Avientus",
        adapter=FakeDealumAdapter(changed_application),
    )

    assert second.changed is False
    application_md = get_storage().read_text(second.application_path)
    assert "rotated-token" not in application_md
    assert (
        "dealum-attachment:pitch_deck:Avientus_Deck.pdf"
        in application_md
    )


def test_dealum_sync_due_is_per_startup_and_uses_six_hour_timestamp(
    mock_env,
    mocker,
    monkeypatch,
):
    storage = get_storage()
    monkeypatch.delenv("DEALUM_SYNC_TTL_SECONDS", raising=False)
    now = 1_000_000
    for startup, last_pull in (
        ("freshco", now - 21_599),
        ("stale-co", now - 21_600),
    ):
        manifest_path = (
            f"{dataset_location_for_domain(startup, 'startups').raw_rel}"
            "/dealum/manifest.json"
        )
        storage.write_text(
            manifest_path,
            json.dumps({LAST_SUCCESSFUL_PULL_AT: last_pull}),
        )
    mocker.patch("lib.startups.sources.time.time", return_value=now)

    assert _dealum_sync_due("freshco") is False
    assert _dealum_sync_due("stale-co") is True


def test_dealum_sync_due_treats_legacy_manifest_without_timestamp_as_due(
    mock_env,
):
    storage = get_storage()
    storage.write_text(
        f"{dataset_location_for_domain('legacy-co', 'startups').raw_rel}"
        "/dealum/manifest.json",
        json.dumps({"last_sync": 999_999_999}),
    )

    assert _dealum_sync_due("legacy-co") is True


@pytest.mark.asyncio
async def test_ensure_startup_dataset_skips_dealum_within_freshness_window(
    mock_env,
    mocker,
    monkeypatch,
):
    storage = get_storage()
    monkeypatch.delenv("DEALUM_SYNC_TTL_SECONDS", raising=False)
    manifest_path = (
        f"{dataset_location_for_domain('avientus', 'startups').raw_rel}"
        "/dealum/manifest.json"
    )
    storage.write_text(
        manifest_path,
        json.dumps({LAST_SUCCESSFUL_PULL_AT: 1_000_000}),
    )
    mocker.patch("lib.startups.sources.time.time", return_value=1_021_599)
    mocker.patch(
        "lib.startups.sources.DealumAdapter",
        return_value=FakeDealumAdapter(),
    )
    import_mock = mocker.patch(
        "lib.startups.sources.import_startup_from_dealum",
    )

    status = await ensure_startup_dataset(
        "Avientus",
        sync_after_import=False,
    )

    assert status.dataset_exists is True
    assert status.dealum_checked is False
    import_mock.assert_not_called()


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
