"""Opt-in, read-only benchmark against existing local data rooms.

Set SICTIC_DISCOVERY_BENCHMARK_STORAGE and SICTIC_DISCOVERY_BENCHMARK_RUNTIME
to the application and runtime storage roots. No services or generation run.
The roster is a partial reference, not exhaustive name-recognition ground truth.
"""

import json
import os
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from lib.datasets.paths import dataset_location
from lib.datasets.source import iter_parsed_chunks
from lib.people.discovery import manual_persons_in_dataset
from lib.people.extraction import PersonExtractor
from lib.people.linkedin.evidence import condense_profile
from lib.people.linkedin.store import LinkedInProfileStore
from lib.people.linkedin import LinkedInResolver
from lib.people.extraction import merge_person
from lib.people.model import Person
from lib.insights import InsightFile
from lib.storage import get_storage, reset_storage_singleton
from skills.persons_in_dataset.reconciliation import _prepare_prompts
from skills.persons_in_dataset.persons_in_dataset import _shortlist_ner_people


DATASETS = ["avientus", "ovomind", "proud-technology", "herosupport", "scanvio", "miraex"]


@pytest.mark.parametrize("dataset", DATASETS)
def test_local_discovery_recall_and_profile_size(dataset, monkeypatch):
    root = os.getenv("SICTIC_DISCOVERY_BENCHMARK_STORAGE")
    runtime = os.getenv("SICTIC_DISCOVERY_BENCHMARK_RUNTIME")
    if not root or not runtime:
        pytest.skip("opt-in local data-room benchmark")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", root)
    monkeypatch.setenv("LOCAL_DATA_PATH", runtime)
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "262144")
    reset_storage_singleton()
    try:
        started = time.monotonic()
        config = json.loads((Path(__file__).resolve().parents[2] / "config/persons_in_dataset/discovery.json").read_text())
        chunks = [chunk for chunk in iter_parsed_chunks(dataset) if not chunk.document_name.startswith("linkedin/")]
        people = PersonExtractor(**config["ner"]).extract(chunks)
        text = " ".join(chunk.text for chunk in chunks).casefold()
        reference = [person for person in manual_persons_in_dataset(dataset) or [] if person.full_name and person.full_name.casefold() in text]
        recovered = [person for person in reference if person.find_best_match(people) is not None]
        shortlisted = _shortlist_ner_people(people, config["ner_max_candidates"])
        for person in LinkedInResolver(dataset).get_cached_persons():
            merge_person(people, person)
            merge_person(shortlisted, person)
        profiles = LinkedInProfileStore(get_storage(), f"{dataset_location(dataset).raw_rel}/linkedin").load_all()
        raw_size = sum(len(json.dumps(profile)) for profile in profiles.values())
        compact_size = sum(len(json.dumps(condense_profile(Person(linkedin_id=identifier, linkedin_profile=profile), company_names=[dataset], description_chars=config["linkedin_description_chars"]))) for identifier, profile in profiles.items())
        print(f"\n{dataset}: {len(chunks)} chunks; {len(people)} candidates; roster names present in text recovered: {len(recovered)}/{len(reference)}; LinkedIn characters: {raw_size} -> {compact_size}")
        profile = InsightFile(dataset, "startup_profile", "manual").find(selection="any")
        # Independent of the reference roster: this is a local evidence test,
        # not a replacement for production semantic retrieval.
        team_chunks = sorted(chunks, key=lambda chunk: sum(term in chunk.text.casefold() for term in ("co-founder", "founders", "our team", "ceo", "cto", "team members")), reverse=True)[:config["max_chunks"]]
        context = profile.content() if profile else dataset
        error = None
        try:
            prompts = _prepare_prompts(shortlisted, team_chunks, startup_context=context, company_names=[dataset], config=config)
        except ValueError as exc:
            prompts = []
            error = str(exc)
        report = {
            "dataset": dataset, "chunks": len(chunks), "candidates": len(people),
            "shortlisted_candidates": len(shortlisted),
            "reference_names_in_text": [p.full_name for p in reference],
            "reference_names_recovered": [p.full_name for p in recovered],
            "reference_names_missed": [p.full_name for p in reference if p not in recovered],
            "raw_linkedin_chars": raw_size, "compact_linkedin_chars": compact_size,
            "prompt_batches": len(prompts), "prompt_chars": sum(map(len, prompts)),
            "preflight_error": error, "seconds": round(time.monotonic() - started, 2),
            "named_candidates_without_id": sum(bool(p.full_name) and not p.linkedin_id for p in people),
        }
        output = os.getenv("SICTIC_DISCOVERY_BENCHMARK_OUTPUT")
        if output:
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{dataset}-local.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
            (directory / f"{dataset}-evidence.json").write_text(json.dumps({
                "people": [{**asdict(p), "mentions": [c.model_dump(mode="json") for c in p.mentions], "dossier": [c.model_dump(mode="json") for c in p.dossier]} for p in people],
                "team_chunks": [c.model_dump(mode="json") for c in team_chunks],
                "startup_context": context,
            }, ensure_ascii=False))
        print(json.dumps(report, ensure_ascii=False))
        print(f"Reconciliation preflight: {len(prompts)} batches, {sum(map(len, prompts))} total characters")
        assert chunks and people
        if reference:
            assert recovered
        if raw_size:
            assert compact_size < raw_size
        assert error is None, error
    finally:
        reset_storage_singleton()
