"""Opt-in company-search/profile integration; uses an isolated registry/store.

Deliberately excludes the potentially hundreds of per-candidate searches.
Not a full skill run: no website import, indexing or roster generation.
"""

import json
import os
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values

from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.apify import ApifyAdapter
from lib.people.extraction import merge_person
from lib.people.linkedin import LinkedInResolver
from lib.people.linkedin.registry import LinkedInRegistry
from lib.people.linkedin.search import search_people
from lib.people.model import Person
from lib.storage import get_storage, reset_storage_singleton


@pytest.mark.parametrize("dataset", ["avientus", "ovomind", "proud-technology", "miraex"])
def test_real_cached_profiles_never_call_apify(dataset, monkeypatch, tmp_path):
    directory = os.getenv("SICTIC_DISCOVERY_BENCHMARK_OUTPUT")
    if not directory:
        pytest.skip("opt-in local data-room cache verification")
    evidence = json.loads((Path(directory) / f"{dataset}-evidence.json").read_text())
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("LOCAL_DATA_PATH", str(tmp_path))
    reset_storage_singleton()
    try:
        location = dataset_location_for_domain(dataset, "startups")
        get_storage().mkdir(location.raw_rel)
        registry = LinkedInRegistry(path=tmp_path / "registry.json")
        resolver = LinkedInResolver(dataset, registry=registry)
        ids = []
        for row in evidence["people"]:
            if row["linkedin_id"] and row["linkedin_profile"]:
                resolver.profile_store.write(row["linkedin_id"], row["linkedin_profile"])
                ids.append(row["linkedin_id"])
        def forbidden_apify():
            pytest.fail("Cached profiles must not access Apify")
        resolver = LinkedInResolver(dataset, registry=registry, apify_factory=forbidden_apify)
        requested = [Person(linkedin_id=identifier) for identifier in ids]
        resolver.get_profiles(requested)
        assert ids and all(p.linkedin_profile for p in requested)
        assert not registry.load()
    finally:
        reset_storage_singleton()


@pytest.mark.parametrize("dataset,company", [("herosupport", "HeroSupport"), ("proud-technology", "Proud Technology")])
def test_live_company_search_and_profile_cache(dataset, company, monkeypatch):
    if os.getenv("SICTIC_DISCOVERY_ACQUISITION_EVALUATION") != "1":
        pytest.skip("opt-in paid Apify evaluation")
    root = Path(__file__).resolve().parents[2]
    output = Path(os.environ["SICTIC_DISCOVERY_BENCHMARK_OUTPUT"])
    isolated = output / "acquisition" / dataset
    isolated.mkdir(parents=True, exist_ok=True)
    settings = dotenv_values(root / ".env")
    monkeypatch.setenv("APIFY_KEY", settings["APIFY_KEY"])
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(isolated))
    monkeypatch.setenv("LOCAL_DATA_PATH", str(isolated))
    reset_storage_singleton()
    try:
        location = dataset_location_for_domain(dataset, "startups")
        get_storage().mkdir(location.raw_rel)
        registry = LinkedInRegistry(path=isolated / "registry.json")
        class RecordedApify(ApifyAdapter):
            def get_run(self, run_id):
                run = super().get_run(run_id)
                (isolated / f"run-{run_id}.json").write_text(json.dumps({key: run.get(key) for key in (
                    "id", "status", "statusMessage", "usageTotalUsd", "startedAt", "finishedAt")}, default=str, indent=2))
                return run
        resolver = LinkedInResolver(dataset, registry=registry, apify_factory=RecordedApify)
        evidence = json.loads((output / f"{dataset}-evidence.json").read_text())
        for row in evidence["people"]:
            if row["linkedin_id"] and row["linkedin_profile"]:
                resolver.profile_store.write(row["linkedin_id"], row["linkedin_profile"])
        resolver = LinkedInResolver(dataset, registry=registry, apify_factory=RecordedApify)
        config = json.loads((root / "config/persons_in_dataset/discovery.json").read_text())["search"]
        search_file = isolated / "search.json"
        started = time.monotonic()
        if search_file.exists():
            people = [Person(**row) for row in json.loads(search_file.read_text())]
        else:
            people = []
            for candidate in search_people(company, [], queries=config["linkedin_queries"], num_results=config["results_per_query"]):
                merge_person(people, candidate)
            search_file.write_text(json.dumps([{"linkedin_id": p.linkedin_id} for p in people]))
        before = set(resolver.profiles)
        error = None
        try:
            resolver.get_profiles(people)
        except Exception as exc:
            error = str(exc)
        report = {"dataset": dataset, "company_queries": 2, "per_name_queries": 0,
                  "search_ids": [p.linkedin_id for p in people], "previously_cached": sorted(before),
                  "cached_after": sorted(resolver.profile_store.load_all()),
                  "seconds": round(time.monotonic() - started, 2), "error": error}
        (output / f"{dataset}-acquisition.json").write_text(json.dumps(report, indent=2))
        assert error is None, error
        assert people
        # Once resolved, the same requests must be fulfilled without Apify.
        def forbidden_apify():
            pytest.fail("Already cached requests must not access Apify")
        cached_resolver = LinkedInResolver(dataset, registry=registry, apify_factory=forbidden_apify)
        cached_resolver.get_profiles([Person(linkedin_id=p.linkedin_id) for p in people])
    finally:
        reset_storage_singleton()
