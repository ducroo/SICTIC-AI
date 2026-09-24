import asyncio
from datetime import datetime, timezone

import pytest

from lib.datasets.paths import dataset_location_for_domain
from lib.datasets.state import (
    activate_dataset, archive_dataset, is_active_dataset, latest_dataset_edit,
    update_dataset_inactivity,
)
from lib.startups.dealum.session import dealum_session
from lib.startups.dealum.stages import ALWAYS_ACTIVE_STAGES, INACTIVITY_STAGES, PITCHED_STAGE
from lib.storage import get_storage
from skills.bulk_refresh import bulk_refresh as bulk
from skills.bulk_refresh.datasets import update_dataset_states
from skills.skill_registry import SkillSpec


NOW = datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp()
OLD = datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp()
RECENT = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()


def dossier(name, *, active=True, timestamp=OLD, domain="startups"):
    storage = get_storage()
    location = dataset_location_for_domain(name, domain)
    storage.mkdir(location.raw_rel)
    storage.write_text(f"{location.raw_rel}/document.md", "Source evidence")
    if active:
        activate_dataset(name)
    for path, _ in storage.list_with_mtime(location.raw_rel, recursive=True):
        storage.set_mtime(f"{location.raw_rel}/{path}", timestamp)
    return location


@pytest.fixture
def dealum(mocker):
    mocker.patch("skills.bulk_refresh.datasets.DealumAdapter.is_configured", return_value=True)
    applications = mocker.patch("skills.bulk_refresh.datasets.DealumAdapter.list_applications", return_value=[])
    mocker.patch("lib.datasets.state.time.time", return_value=NOW)
    return applications


def test_inactivity_uses_latest_source_and_ignores_housekeeping(mock_env):
    location = dossier("old")
    storage = get_storage()
    for file in ("dealum/manifest.json", "dealum/application.raw.json", ".DS_Store", ".stage/file.md"):
        storage.write_text(f"{location.raw_rel}/{file}", "new housekeeping")
        storage.set_mtime(f"{location.raw_rel}/{file}", NOW)
    storage.write_text(f"{location.parsed_rel}/document.md", "fresh parsing")
    assert latest_dataset_edit("old") == OLD
    update_dataset_inactivity("old", months=3, now=NOW)
    assert not is_active_dataset("old")


@pytest.mark.parametrize("file", ["document.md", "data-room/new.pdf", "data-room/image.png", "__active_dataset__.md"])
def test_real_dataset_edits_extend_activity(mock_env, file):
    location = dossier("recent")
    storage = get_storage()
    storage.write_text(f"{location.raw_rel}/{file}", "new evidence")
    storage.set_mtime(f"{location.raw_rel}/{file}", RECENT)
    update_dataset_inactivity("recent", months=3, now=NOW)
    assert is_active_dataset("recent")


def test_archived_requires_manual_reactivation_and_unmarked_defaults_archived(mock_env):
    location = dossier("manual", timestamp=RECENT)
    storage = get_storage()
    archive_dataset("manual")
    marker = f"{location.raw_rel}/__archived_dataset__.md"
    storage.set_mtime(marker, RECENT + 1)
    update_dataset_inactivity("manual", months=3, now=NOW)
    assert not is_active_dataset("manual")
    storage.set_mtime(f"{location.raw_rel}/document.md", NOW)
    update_dataset_inactivity("manual", months=3, now=NOW)
    assert not is_active_dataset("manual")
    activate_dataset("manual")
    update_dataset_inactivity("manual", months=3, now=NOW)
    assert is_active_dataset("manual")
    dossier("unmarked", active=False, timestamp=RECENT)
    update_dataset_inactivity("unmarked", months=3, now=NOW)
    assert not is_active_dataset("unmarked")


def test_manual_marker_rename_is_respected_despite_old_mtime(mock_env):
    from pathlib import Path
    location = dossier("manual", timestamp=OLD)
    storage = get_storage()
    storage.set_mtime(f"{location.raw_rel}/document.md", RECENT)
    active = Path(storage.local_path(f"{location.raw_rel}/__active_dataset__.md"))
    archived = active.with_name("__archived_dataset__.md")
    active.rename(archived)
    update_dataset_inactivity("manual", months=3, now=NOW)
    assert not is_active_dataset("manual")


def test_three_calendar_month_boundary(mock_env):
    cutoff = datetime(2026, 6, 20, tzinfo=timezone.utc).timestamp()
    dossier("boundary", timestamp=cutoff)
    update_dataset_inactivity("boundary", months=3, now=NOW)
    assert not is_active_dataset("boundary")


@pytest.mark.parametrize("stage", sorted(ALWAYS_ACTIVE_STAGES | INACTIVITY_STAGES | {PITCHED_STAGE}))
def test_stage_table_overrides_age_only_for_fixed_stages(mock_env, dealum, mocker, stage):
    dossier("example")
    dealum.return_value = [{"id": 1, "name": "Example", "step": stage}]
    mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum")
    names, stages, errors = update_dataset_states(("example",), discover=False, excluded=set())
    assert not errors
    assert names == ("example",)
    assert stages == {"example": stage}
    assert is_active_dataset("example") == (stage in ALWAYS_ACTIVE_STAGES)


def test_pitched_does_not_reset_active_marker(mock_env, dealum, mocker):
    location = dossier("example", timestamp=RECENT)
    dealum.return_value = [{"id": 1, "name": "Example", "step": PITCHED_STAGE}]
    mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum")
    update_dataset_states(("example",), discover=False, excluded=set())
    assert get_storage().mtime(f"{location.raw_rel}/__active_dataset__.md") == RECENT


def test_unknown_or_failed_lookup_never_means_absent(mock_env, dealum, mocker):
    dossier("example")
    dealum.return_value = [{"id": 1, "name": "Example", "step": "Unexpected"}]
    imported = mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum")
    _, stages, errors = update_dataset_states(("example",), discover=False, excluded=set())
    assert "example" in errors and "example" not in stages
    assert is_active_dataset("example")
    imported.assert_not_called()
    dealum.side_effect = RuntimeError("API unavailable")
    _, stages, errors = update_dataset_states(("example",), discover=False, excluded=set())
    assert "API unavailable" in errors["example"]
    assert "example" not in stages
    assert is_active_dataset("example")


def test_named_scope_does_not_update_or_import_unrelated_dossiers(mock_env, dealum, mocker):
    dossier("target", timestamp=RECENT)
    dossier("unrelated")
    dealum.return_value = [
        {"name": "Target", "step": "Jury"},
        {"name": "Unrelated", "step": "Rejected by Jury"},
        {"name": "New Startup", "step": "Jury"},
    ]
    imported = mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum")
    scope, errors = bulk._resolve_targets("target", None)
    assert not errors
    assert scope.names == ("target",)
    assert is_active_dataset("unrelated")
    imported.assert_called_once()
    assert imported.call_args.args[0] == "target"


def test_named_missing_scope_creates_only_selected_active_startups(mock_env, dealum, mocker):
    from lib.datasets.paths import find_dataset_location

    selected = {
        "adularia": "Under Review", "cellkinetica": "Under Review",
        "openversum": "Jury", "badger": "Jury reserves (for pitching)",
        "firedrone": "Pitching",
    }
    dealum.return_value = [
        {"name": name, "step": stage} for name, stage in selected.items()
    ] + [{"name": "Unrelated", "step": "Jury"}]
    imported = mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum")
    scope, errors = bulk._resolve_targets(",".join(selected), None)
    assert not errors
    assert scope.names == tuple(selected)
    assert scope.stages == selected
    assert all(is_active_dataset(name) for name in selected)
    assert find_dataset_location("unrelated") is None
    assert [call.args[0] for call in imported.call_args_list] == list(selected)
    _, planned, _ = bulk._plan_jobs(scope, None)
    assert len(planned) == 15


@pytest.mark.parametrize("stage", [None, "Application", "Pitched @ SICTIC", "Rejected by Jury", "Unexpected"])
def test_named_missing_ineligible_dossier_is_not_created(mock_env, dealum, mocker, stage):
    from lib.datasets.paths import find_dataset_location

    dealum.return_value = [] if stage is None else [{"name": "Missing", "step": stage}]
    imported = mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum")
    scope, errors = bulk._resolve_targets("missing", None)
    assert scope.names == ()
    assert "missing" in errors
    assert find_dataset_location("missing") is None
    imported.assert_not_called()


def test_named_missing_alias_creates_one_canonical_dossier(mock_env, dealum, mocker):
    from lib.datasets.paths import find_dataset_location

    dealum.return_value = [{"name": "Checksum AG", "step": "Jury"}]
    imported = mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum")
    scope, errors = bulk._resolve_targets("checksum-ag,checksum", None)
    assert not errors
    assert scope.names == ("checksum",)
    assert is_active_dataset("checksum")
    assert find_dataset_location("checksum-ag") is None
    imported.assert_called_once()


def test_default_filters_after_stage_updates_and_discovers_relevant_dossiers(mock_env, dealum):
    dossier("old")
    dossier("jury", active=False)
    dealum.return_value = [
        {"name": "Jury", "step": "Jury"},
        {"name": "New Startup", "step": "Under Review"},
        {"name": "New Rejected", "step": "Rejected by Jury"},
        {"name": "Historical Pitched", "step": PITCHED_STAGE},
    ]
    with dealum_session():
        scope, errors = bulk._resolve_targets(None, None)
    assert not errors
    assert set(scope.names) == {"jury", "new-startup"}
    assert not is_active_dataset("old")
    dealum.assert_called_once()


@pytest.mark.parametrize("selector", ["all", "old"])
def test_explicit_selection_processes_archived_without_activating(mock_env, dealum, selector):
    dossier("old")
    scope, errors = bulk._resolve_targets(selector, None)
    assert not errors
    assert "old" in scope.names
    assert not is_active_dataset("old")


def test_alias_uses_shared_matching_and_existing_dossier(mock_env, dealum):
    dossier("checksum")
    dealum.return_value = [{"name": "Checksum AG", "step": "Under Review"}]
    scope, errors = bulk._resolve_targets("checksum", None)
    assert not errors
    assert scope.stages == {"checksum": "Under Review"}


@pytest.mark.parametrize("names", [("Example", "EXAMPLE"), ("Checksum AG", "CHECKSUM AG")])
def test_normalized_variants_use_latest_application(mock_env, dealum, names):
    slug = "checksum" if names[0].startswith("Checksum") else "example"
    dossier(slug)
    dealum.return_value = [
        {"id": 1, "name": names[0], "step": "Rejected by Jury", "createDate": "2025-01-01"},
        {"id": 2, "name": names[1], "step": "Jury", "createDate": "2026-01-01"},
    ]
    scope, errors = bulk._resolve_targets(slug, None)
    assert not errors
    assert scope.stages[slug] == "Jury"


def test_alias_tied_dates_remain_ambiguous(mock_env, dealum):
    dossier("checksum")
    dealum.return_value = [
        {"id": 1, "name": "Checksum AG", "step": "Jury", "createDate": "2026-01-01"},
        {"id": 2, "name": "CHECKSUM AG", "step": "Jury", "createDate": "2026-01-01"},
    ]
    _, errors = bulk._resolve_targets("checksum", None)
    assert "tied latest date" in errors["checksum"]


def test_mandatory_skills_are_selected_per_dataset_with_domain_restrictions():
    scope = bulk._DatasetScope(
        ("review", "jury", "pitched", "local", "members"),
        {"review": "startups", "jury": "startups", "pitched": "startups", "local": "startups", "members": "community"},
        {"review": "Under Review", "jury": "Jury", "pitched": PITCHED_STAGE, "local": None, "members": None},
    )
    nodes = bulk._nodes(scope, set(bulk.SKILL_REGISTRY))
    selected = bulk._planned_nodes(scope, None, bulk._dependency_graph(scope, nodes))
    assert {skill for name, skill in selected if name == "review"} == {"startup-profile", "persons-in-dataset", "submission-ready"}
    assert {skill for name, skill in selected if name == "jury"} == {"startup-profile", "persons-in-dataset", "startup-website-import"}
    assert {skill for name, skill in selected if name == "pitched"} == {"startup-profile", "persons-in-dataset", "person-profile", "startup-traction", "startup-website-import"}
    assert {skill for name, skill in selected if name == "local"} == {"startup-profile", "persons-in-dataset", "person-profile", "startup-traction"}
    assert {skill for name, skill in selected if name == "members"} == {"persons-in-dataset"}


@pytest.mark.asyncio
async def test_selected_acquisition_precedes_insights(mock_env, dealum, mocker):
    dossier("example", timestamp=RECENT)
    calls = []

    async def acquire(dataset):
        calls.append("acquire")
        await asyncio.sleep(0)
        calls.append("acquired")

    async def insight(dataset):
        assert calls[-1] == "acquired"
        calls.append("insight")

    mocker.patch.object(bulk, "sync_datasets", return_value=[])
    mocker.patch.dict(bulk.SKILL_REGISTRY, {
        "acquisition": SkillSpec(acquire, frozenset({"startups"}), mandatory_stages=frozenset({"*"}), prepares_sources=True),
        "insight": SkillSpec(insight, frozenset({"startups"}), mandatory_stages=frozenset({"*"})),
    }, clear=True)
    await bulk.bulk_refresh(datasets="example")
    assert calls == ["acquire", "acquired", "insight"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["acquisition", "post-acquisition-sync"])
async def test_failed_optional_website_does_not_skip_insights(mock_env, dealum, mocker, caplog, failure):
    dossier("example", timestamp=RECENT)
    calls = []

    async def acquire(dataset):
        calls.append("website-attempted")
        if failure == "acquisition":
            raise RuntimeError("website unavailable")

    async def sync(*args, **kwargs):
        if calls:
            raise RuntimeError("website indexing failed")

    async def startup(dataset):
        assert "website-attempted" in calls
        calls.append("startup-profile")

    async def persons(dataset):
        assert "website-attempted" in calls
        calls.append("persons-in-dataset")

    async def profile(dataset):
        assert "persons-in-dataset" in calls
        calls.append("person-profile")

    required_consumer = mocker.AsyncMock()
    mocker.patch.object(bulk, "sync_datasets", side_effect=sync)
    mocker.patch.dict(bulk.SKILL_REGISTRY, {
        "startup-website-import": SkillSpec(acquire, frozenset({"startups"}), prepares_sources=True),
        "startup-profile": SkillSpec(startup, frozenset({"startups"})),
        "persons-in-dataset": SkillSpec(persons, frozenset({"startups"})),
        "person-profile": SkillSpec(profile, frozenset({"startups"}), depends_on=("persons-in-dataset",)),
        "required-consumer": SkillSpec(required_consumer, frozenset({"startups"}), depends_on=("startup-website-import",)),
    }, clear=True)

    with pytest.raises(bulk.BulkRefreshError, match="2 failed or skipped rows"):
        await bulk.bulk_refresh(datasets="example", skills="all")

    assert calls[0] == "website-attempted"
    assert set(calls[1:]) == {"startup-profile", "persons-in-dataset", "person-profile"}
    required_consumer.assert_not_awaited()
    assert "Skill startup-website-import failed; bulk refresh will continue" in caplog.text
    for skill in ("startup-profile", "persons-in-dataset", "person-profile"):
        assert f"| example | {skill} | skipped:" not in caplog.text


def test_community_inactivity_does_not_query_dealum(mock_env, dealum):
    dossier("members", domain="community")
    _, stages, errors = update_dataset_states(("members",), discover=False, excluded=set())
    assert not errors and stages == {"members": None}
    assert not is_active_dataset("members")
    dealum.assert_not_called()


def test_expired_pitched_dossier_is_not_downloaded(mock_env, dealum, mocker):
    location = dossier("pitched")
    storage = get_storage()
    dealum.return_value = [{"name": "Pitched", "step": PITCHED_STAGE}]

    imported = mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum")
    scope, errors = bulk._resolve_targets(None, None)
    assert not errors
    assert "pitched" not in scope.names
    assert not is_active_dataset("pitched")
    imported.assert_not_called()


def test_all_states_decided_before_missing_active_dossiers_are_downloaded(mock_env, dealum, mocker):
    dossier("expired")
    dealum.return_value = [{"name": "New Startup", "step": "Jury"}]

    def acquire(name, **kwargs):
        assert name == "new-startup"
        assert is_active_dataset(name)
        assert not is_active_dataset("expired")
        assert kwargs["activate"] is False

    imported = mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum", side_effect=acquire)
    scope, errors = bulk._resolve_targets(None, None)
    assert not errors and scope.names == ("new-startup",)
    imported.assert_called_once()


@pytest.mark.parametrize("stage", sorted(INACTIVITY_STAGES | {PITCHED_STAGE}))
def test_other_stages_keep_recent_existing_dossiers_active(mock_env, dealum, mocker, stage):
    dossier("example", timestamp=RECENT)
    dealum.return_value = [{"name": "Example", "step": stage}]
    imported = mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum")
    _, _, errors = update_dataset_states(("example",), discover=False, excluded=set())
    assert not errors and is_active_dataset("example")
    if stage == "Application":
        imported.assert_not_called()


@pytest.mark.parametrize("stage", sorted(ALWAYS_ACTIVE_STAGES | INACTIVITY_STAGES | {PITCHED_STAGE}))
def test_archive_is_terminal_even_after_stage_changes(mock_env, dealum, mocker, stage):
    location = dossier("example")
    archive_dataset("example")
    get_storage().write_text(f"{location.raw_rel}/new-document.md", "Recent material")
    dealum.return_value = [{"name": "Example", "step": stage}]
    imported = mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum")
    scope, errors = bulk._resolve_targets(None, None)
    assert not errors and "example" not in scope.names
    assert not is_active_dataset("example")
    imported.assert_not_called()


@pytest.mark.parametrize("stage,archived", [("Application", False), ("Jury", True)])
def test_composed_skills_cannot_bypass_disabled_imports(mock_env, dealum, mocker, stage, archived):
    from lib.startups.dealum import import_startup_from_dealum
    dossier("example", timestamp=RECENT)
    if archived:
        archive_dataset("example")
    dealum.return_value = [{"name": "Example", "step": stage}]
    download = mocker.patch("lib.infrastructure.dealum.DealumAdapter.download_file")
    with dealum_session():
        scope, errors = bulk._resolve_targets("example", None)
        assert not errors
        result = import_startup_from_dealum("example")
        assert not result.imported
    download.assert_not_called()
    assert is_active_dataset("example") == (not archived)


def test_expiring_during_run_blocks_later_import_activation(mock_env, dealum, mocker):
    from lib.startups.dealum import import_startup_from_dealum
    dossier("example")
    dealum.return_value = [{"name": "Example", "step": PITCHED_STAGE}]
    mocker.patch("skills.bulk_refresh.datasets.import_startup_from_dealum")
    with dealum_session():
        _, errors = bulk._resolve_targets("example", None)
        assert not errors and not is_active_dataset("example")
        result = import_startup_from_dealum("example", activate=True)
        assert not result.imported
        assert not is_active_dataset("example")


@pytest.mark.asyncio
async def test_plan_is_built_before_ingestion_and_scheduling(mock_env, mocker):
    dossier("members", domain="community", timestamp=RECENT)
    events = []
    original = bulk._plan_jobs

    def plan(*args):
        events.append("plan")
        return original(*args)

    async def sync(*args, **kwargs):
        events.append("ingest")

    def source(dataset):
        events.append("source")

    async def insight(dataset):
        events.append("insight")

    mocker.patch.object(bulk, "_plan_jobs", side_effect=plan)
    mocker.patch.object(bulk, "sync_datasets", side_effect=sync)
    mocker.patch.dict(bulk.SKILL_REGISTRY, {
        "source": SkillSpec(source, frozenset({"community"}), prepares_sources=True),
        "insight": SkillSpec(insight, frozenset({"community"})),
    }, clear=True)
    await bulk.bulk_refresh(datasets="members", skills="all")
    assert events == ["plan", "ingest", "source", "ingest", "insight"]
