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
    "createDate": "2026-05-01T09:00:00Z",
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
        from lib.infrastructure.dealum import DealumAdapter

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


@pytest.mark.parametrize("filename,expected", [
    ("notes.md", "notes.md.txt"),
    ("notes.MD", "notes.MD.txt"),
    ("notes.md.txt", "notes.md.txt"),
    ("deck.pdf", "deck.pdf"),
])
def test_append_txt_to_md_filename(filename, expected):
    from lib.startups.dealum.importing import append_txt_to_md_filename

    assert append_txt_to_md_filename(filename) == expected


def test_dealum_markdown_paths_manifest_and_repeat_import(mock_env):
    application = {
        **APPLICATION,
        "answers": {
            **APPLICATION["answers"],
            "notes": "https://files.dealum.com/token/notes.md",
        },
    }
    adapter = FakeDealumAdapter(application)
    storage = get_storage()
    root = "storage/startups/avientus/datasets/dealum/2026-05-01"
    storage.write_text(f"{root}/manifest.json", json.dumps({"dealum_id": APPLICATION["id"]}))
    storage.write_text(f"{root}/application.md", "legacy application")
    storage.write_text(f"{root}/documents/notes.md", "legacy attachment")

    first = import_startup_from_dealum("Avientus", adapter=adapter)

    assert first.application_path == f"{root}/application.md.txt"
    assert not storage.exists(f"{root}/application.md")
    assert not storage.exists(f"{root}/documents/notes.md")
    manifest = json.loads(storage.read_text(first.manifest_path))
    attachment = next(item for item in manifest["files"] if item["field"] == "notes")
    assert attachment["filename"] == "notes.md.txt"
    assert attachment["path"] == f"{root}/documents/notes.md.txt"
    assert storage.read_bytes(attachment["path"]) == b"test"
    sources = snapshot_source_files(storage, root)
    assert {source.filename for source in sources} >= {
        "application.md.txt", "documents/notes.md.txt",
    }
    for path in (first.application_path, attachment["path"]):
        storage.set_mtime(path, 1_000_000_000)

    second = import_startup_from_dealum("Avientus", adapter=adapter)

    assert not second.changed
    assert [
        (source.filename, source.sha256) for source in sources
    ] == [
        (source.filename, source.sha256) for source in snapshot_source_files(storage, root)
    ]
    for path in (first.application_path, attachment["path"]):
        assert storage.mtime(path) == 1_000_000_000


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
    assert storage.exists("storage/startups/avientus/datasets/dealum/2026-05-01/application.md.txt")
    assert storage.exists("storage/startups/avientus/datasets/dealum/2026-05-01/documents/Avientus_Deck.pdf")
    assert storage.exists("storage/startups/avientus/datasets/__active_dataset__.md")

    manifest = json.loads(storage.read_text("storage/startups/avientus/datasets/dealum/2026-05-01/manifest.json"))
    assert manifest["dealum_id"] == 491739
    assert manifest["dealum_url"] == (
        "https://app.dealum.com/#/dealroom/19180?application=491739"
    )
    assert manifest["step"] == "Jury"
    assert len(manifest["files"]) == 2
    application_md = storage.read_text(
        "storage/startups/avientus/datasets/dealum/2026-05-01/application.md.txt"
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
            "storage/startups/avientus/datasets/dealum/2026-05-01/manifest.json"
        )
    )
    assert result.changed is True
    assert result.stale_files == 1
    assert len(manifest["files"]) == 1
    assert manifest["files"][0]["filename"] == "Avientus_Deck.pdf"
    assert not get_storage().exists(
        "storage/startups/avientus/datasets/dealum/2026-05-01/documents/"
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
        "storage/startups/avientus/datasets/dealum/2026-05-01/documents/"
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


def test_unchanged_dealum_sources_are_not_replaced(mock_env, mocker):
    first = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter())
    storage = get_storage()
    source = "storage/startups/avientus/datasets/dealum/2026-05-01/documents/financialplan.xlsx"
    storage.set_mtime(first.application_path, 1_000_000_000)
    storage.set_mtime(source, 1_000_000_001)
    from pathlib import Path
    before = Path(storage.local_path(source)).stat().st_ino
    before_ctime = Path(storage.local_path(source)).stat().st_ctime_ns
    swap = mocker.patch("lib.startups.dealum.importing._replace_directory_snapshot")
    import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter())
    assert storage.mtime(first.application_path) == 1_000_000_000
    assert storage.mtime(source) == 1_000_000_001
    assert Path(storage.local_path(source)).stat().st_ino == before
    assert Path(storage.local_path(source)).stat().st_ctime_ns == before_ctime
    swap.assert_not_called()


def test_partial_dealum_update_reuses_unchanged_attachments(mock_env):
    from pathlib import Path
    first = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter())
    storage = get_storage()
    source = "storage/startups/avientus/datasets/dealum/2026-05-01/documents/financialplan.xlsx"
    storage.set_mtime(source, 1_000_000_001)
    before_inode = Path(storage.local_path(source)).stat().st_ino
    old_application = storage.read_text(first.application_path)
    changed = {**APPLICATION, "answers": {**APPLICATION["answers"], "description": "New substantive business evidence"}}
    result = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter(changed))
    assert result.changed
    assert storage.read_text(result.application_path) != old_application
    assert storage.mtime(source) == 1_000_000_001
    assert Path(storage.local_path(source)).stat().st_ino == before_inode


def test_bulk_session_reuses_import_without_changing_direct_import_behavior(mock_env):
    from lib.startups.dealum.session import dealum_session
    adapter = FakeDealumAdapter()
    with dealum_session():
        first = import_startup_from_dealum("Avientus", adapter=adapter, activate=False)
        second = import_startup_from_dealum("Avientus", adapter=adapter, activate=False)
        assert first is second
    third = import_startup_from_dealum("Avientus", adapter=adapter, activate=False)
    assert third is not first


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
            "createDate": None,
            "applicationDate": "2026-01-15T09:00:00Z",
        },
        {
            **APPLICATION,
            "id": 2,
            "name": "novoviz",
            "code": "NOVO-2",
            "createDate": None,
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
        {**APPLICATION, "createDate": None, "id": 1, "name": "NovoViz", "code": "NOVO-1"},
        {**APPLICATION, "createDate": None, "id": 2, "name": "novoviz", "code": "NOVO-2"},
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
            "createDate": "2026-01-15T09:00:00Z",
        },
        {
            **APPLICATION,
            "id": 2,
            "name": "Avientus",
            "code": "NEW",
            "createDate": "2026-04-20T09:00:00Z",
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


def dated_applications():
    return [
        {**APPLICATION, "id": 1, "code": "OLD", "createDate": "2025-01-06T09:00:00Z", "step": "Rejected by Jury"},
        {**APPLICATION, "id": 2, "code": "NEW", "createDate": "2026-06-30T09:00:00Z", "step": "Jury"},
    ]


def test_vocating_alias_import_uses_merged_dossier(mock_env):
    application = {**APPLICATION, "name": "Vocating.ai"}
    result = import_startup_from_dealum("vocating", adapter=FakeDealumAdapter(application))
    assert result.dataset_slug == "vocating-ai"
    assert result.match_method == "startup_alias"
    assert get_storage().exists(result.application_path)
    assert not get_storage().exists(dataset_location_for_domain("vocating", "startups").raw_rel)


def test_import_all_applications_and_update_only_one(mock_env):
    from lib.startups.dealum.manifest import dealum_url_for_startup, read_manifest
    from skills.deep_dive_invitation.deep_dive_invitation import _dealum_contact

    applications = dated_applications()
    adapter = FakeDealumAdapter(applications=applications)
    result = import_startup_from_dealum("Avientus", adapter=adapter)
    storage = get_storage()
    root = "storage/startups/avientus/datasets/dealum"
    old_path = f"{root}/2025-01-06/application.md.txt"
    assert result.applications_imported == 2
    assert result.downloaded_files == 4
    assert result.dealum_id == 2
    assert result.step == "Jury"
    assert result.application_path == f"{root}/2026-06-30/application.md.txt"
    assert read_manifest("avientus")["dealum_id"] == 2
    assert dealum_url_for_startup("avientus").endswith("application=2")
    contact = _dealum_contact(result.application_path)
    assert contact.full_name == "Johannes Aicher"
    assert contact.email_addresses == ["johannes@avientus.ch"]
    storage.set_mtime(old_path, 1_000_000_000)
    old_text = storage.read_text(old_path)
    applications[1] = {**applications[1], "answers": {"oneliner": "New company evidence"}}
    updated = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter(applications=applications))
    assert updated.changed
    assert updated.stale_files == 2
    assert storage.read_text(old_path) == old_text
    assert storage.mtime(old_path) == 1_000_000_000
    assert storage.exists(f"{root}/2025-01-06/documents/financialplan.xlsx")
    assert not storage.exists(f"{root}/2026-06-30/documents/financialplan.xlsx")
    unchanged = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter(applications=applications))
    assert not unchanged.changed
    sources = snapshot_source_files(storage, root)
    assert len([source for source in sources if source.filename.endswith("application.md.txt")]) == 2
    assert not any(source.filename.endswith(".json") for source in sources)


def test_code_import_keeps_latest_url_and_does_not_satisfy_full_import(mock_env):
    from lib.startups.dealum.manifest import dealum_url_for_startup
    from lib.startups.dealum.session import dealum_session

    adapter = FakeDealumAdapter(applications=dated_applications())
    with dealum_session():
        old = import_startup_from_dealum("OLD", adapter=adapter)
        assert old.applications_imported == 1
        assert old.dealum_id == 1
        assert _dealum_sync_due("avientus")
        result = import_startup_from_dealum("Avientus", adapter=adapter)
        assert result.applications_imported == 2
        assert result.dealum_id == 2
        assert adapter.downloads == 4  # old application reused
        assert not _dealum_sync_due("avientus")
        assert import_startup_from_dealum("Avientus", adapter=adapter) is result
    import_startup_from_dealum("OLD", adapter=adapter)
    assert dealum_url_for_startup("avientus").endswith("application=2")
    assert _dealum_sync_due("avientus")


def test_missing_historical_application_in_response_is_retained(mock_env):
    applications = dated_applications()
    first = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter(applications=applications))
    old_path = first.application_path.replace("2026-06-30", "2025-01-06")
    old_text = get_storage().read_text(old_path)
    result = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter(applications=applications[1:]))
    assert not result.changed
    assert get_storage().read_text(old_path) == old_text


@pytest.mark.parametrize("bad_date", [None, "", "invalid", "99999999999999999999999999"])
def test_import_requires_create_date_without_fallback(mock_env, bad_date):
    from lib.startups.dealum.matching import DealumReconciliationError
    adapter = FakeDealumAdapter({**APPLICATION, "createDate": bad_date, "joinDate": "2026-01-01"})
    with pytest.raises(DealumReconciliationError, match="no valid createDate"):
        import_startup_from_dealum("Avientus", adapter=adapter)
    assert adapter.downloads == 0


@pytest.mark.parametrize("existing", [False, True])
def test_same_day_collision_preserves_existing_application(mock_env, existing):
    from lib.startups.dealum.matching import DealumReconciliationError
    applications = dated_applications()
    applications[1]["createDate"] = "2025-01-06T12:00:00Z"
    storage = get_storage()
    if existing:
        first = import_startup_from_dealum("OLD", adapter=FakeDealumAdapter(applications=applications))
        previous = storage.read_text(first.application_path)
    adapter = FakeDealumAdapter(applications=applications)
    with pytest.raises(DealumReconciliationError, match="share createDate day"):
        import_startup_from_dealum("NEW" if existing else "Avientus", adapter=adapter)
    assert adapter.downloads == 0
    if existing:
        assert storage.read_text(first.application_path) == previous


def test_changed_creation_date_does_not_duplicate_application(mock_env):
    from lib.startups.dealum.matching import DealumReconciliationError
    first = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter())
    adapter = FakeDealumAdapter({**APPLICATION, "createDate": "2026-08-01"})
    with pytest.raises(DealumReconciliationError, match="changed createDate"):
        import_startup_from_dealum("Avientus", adapter=adapter)
    assert get_storage().exists(first.application_path)
    assert adapter.downloads == 0


def test_partial_refresh_does_not_mark_collection_fresh(mock_env):
    from lib.startups.dealum.manifest import read_manifest
    applications = dated_applications()
    import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter(applications=applications))
    storage = get_storage()
    root = "storage/startups/avientus/datasets/dealum"
    latest_path = f"{root}/2026-06-30/application.md.txt"
    latest_text = storage.read_text(latest_path)
    assert not _dealum_sync_due("avientus")
    applications[0] = {**applications[0], "answers": {"oneliner": "Updated older evidence"}}
    applications[1] = {**applications[1], "answers": {"pitch_deck": "https://files.dealum.com/token/fail.pdf"}}

    class FailingAdapter(FakeDealumAdapter):
        def download_file(self, url):
            raise RuntimeError("download failed")

    with pytest.raises(RuntimeError, match="download failed"):
        import_startup_from_dealum("Avientus", adapter=FailingAdapter(applications=applications))
    assert "Updated older evidence" in storage.read_text(f"{root}/2025-01-06/application.md.txt")
    assert storage.read_text(latest_path) == latest_text
    assert read_manifest("avientus")["dealum_id"] == 2
    assert _dealum_sync_due("avientus")


def flatten_snapshot(result):
    """Model the previous supported layout, with its actual manifest and raw data."""
    from pathlib import Path
    storage = get_storage()
    folder = Path(result.manifest_path).parent
    root = str(folder.parent)
    manifest = json.loads(storage.read_text(result.manifest_path))
    for item in manifest["files"]:
        item["path"] = item["path"].replace(str(folder), root)
    storage.write_text(result.manifest_path, json.dumps(manifest))
    for path in Path(storage.local_path(str(folder))).iterdir():
        path.replace(Path(storage.local_path(root)) / path.name)
    Path(storage.local_path(str(folder))).rmdir()
    return root


def test_migrate_flat_snapshot_preserves_content_mtime_and_manifest_paths(mock_env):
    from pathlib import Path
    from lib.startups.dealum.manifest import read_manifest
    first = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter())
    root = flatten_snapshot(first)
    storage = get_storage()
    source = f"{root}/documents/financialplan.xlsx"
    storage.set_mtime(source, 1_000_000_001)
    inode = Path(storage.local_path(source)).stat().st_ino
    second = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter())
    assert second.changed  # source paths moved, so synchronize normally
    moved = f"{root}/2026-05-01/documents/financialplan.xlsx"
    assert storage.mtime(moved) == 1_000_000_001
    assert Path(storage.local_path(moved)).stat().st_ino == inode
    assert not storage.exists(source)
    assert all("/2026-05-01/" in item["path"] for item in read_manifest("avientus")["files"])
    assert not import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter()).changed


def test_migration_retains_legacy_application_missing_from_current_response(mock_env):
    applications = dated_applications()
    first = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter(applications=applications[:1]))
    root = flatten_snapshot(first)
    original = get_storage().read_text(f"{root}/application.md.txt")
    import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter(applications=applications[1:]))
    assert get_storage().read_text(f"{root}/2025-01-06/application.md.txt") == original
    assert get_storage().exists(f"{root}/2026-06-30/application.md.txt")


def test_failed_migration_publication_restores_flat_snapshot(mock_env, mocker):
    from lib.infrastructure.filesystem import os
    first = import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter())
    root = flatten_snapshot(first)
    storage = get_storage()
    original = storage.read_text(f"{root}/application.md.txt")
    replace = os.replace

    def fail_publish(source, target):
        if str(source).split("/")[-1].startswith(".dealum-migration-"):
            raise OSError("cannot publish migration")
        return replace(source, target)

    mocker.patch("lib.infrastructure.filesystem.os.replace", side_effect=fail_publish)
    with pytest.raises(OSError, match="cannot publish migration"):
        import_startup_from_dealum("Avientus", adapter=FakeDealumAdapter())
    assert storage.read_text(f"{root}/application.md.txt") == original
