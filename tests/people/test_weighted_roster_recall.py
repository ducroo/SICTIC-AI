"""Paid, opt-in weighted reconciliation versus held-out manual rosters.

Uses saved local evidence, not live acquisition/indexing. Manual rosters are
read only after generation and are never supplied to the model.
"""

import json
import os
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values

from lib.datasets.models import Chunk
from lib.people.discovery import manual_persons_in_dataset
from lib.people.model import Person
from lib.storage import reset_storage_singleton
from skills.persons_in_dataset.persons_in_dataset import _shortlist_ner_people
from skills.persons_in_dataset.reconciliation import reconcile_people


@pytest.mark.asyncio
@pytest.mark.parametrize("dataset", ["avientus", "ovomind", "miraex"])
async def test_weighted_roster_covers_manual_reference(dataset, monkeypatch):
    if os.getenv("SICTIC_DISCOVERY_PROVIDER_EVALUATION") != "1":
        pytest.skip("opt-in paid weighted roster evaluation")
    root = Path(__file__).resolve().parents[2]
    source = Path(os.environ["SICTIC_DISCOVERY_BENCHMARK_OUTPUT"])
    output = source / os.getenv("SICTIC_DISCOVERY_RECALL_REPORT", "weighted-review")
    output.mkdir(parents=True, exist_ok=True)
    settings = dotenv_values(root / ".env")
    for key in ("LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "OPENAI_API_KEY", "OLLAMA_CONTEXT_LENGTH", "OLLAMA_CONTEXT_LENGTH_MAX"):
        if settings.get(key) is not None:
            monkeypatch.setenv(key, settings[key])
    from lib.infrastructure.ai_text_generation import generation, measurements
    monkeypatch.setattr(generation, "measurements_enabled", lambda: True)
    monkeypatch.setattr(measurements, "measurements_enabled", lambda: True)
    monkeypatch.setattr(measurements, "MEASUREMENT_FILE", output / f"{dataset}-usage.jsonl")
    evidence = json.loads((source / f"{dataset}-evidence.json").read_text())
    people = [Person(**{**row, "mentions": [Chunk(**c) for c in row["mentions"]],
                        "dossier": [Chunk(**c) for c in row["dossier"]]}) for row in evidence["people"]]
    config = json.loads((root / "config/persons_in_dataset/discovery.json").read_text())
    shortlisted = _shortlist_ner_people(people, config["ner_max_candidates"])
    started = time.monotonic()
    accepted = await reconcile_people(shortlisted, [Chunk(**c) for c in evidence["team_chunks"]],
        startup_context=evidence["startup_context"], company_names=[dataset], config=config)
    elapsed = time.monotonic() - started
    monkeypatch.setenv("LOCAL_STORAGE_PATH", os.environ["SICTIC_DISCOVERY_BENCHMARK_STORAGE"])
    monkeypatch.setenv("LOCAL_DATA_PATH", os.environ["SICTIC_DISCOVERY_BENCHMARK_RUNTIME"])
    reset_storage_singleton()
    try:
        reference = manual_persons_in_dataset(dataset)
        assert reference, "This evaluation needs a nonempty reference roster"
    finally:
        reset_storage_singleton()
    comparisons = []
    for person in reference:
        match = person.find_best_match(accepted)
        name_match = Person(full_name=person.full_name).find_best_match(accepted) if person.full_name else None
        comparisons.append({"reference_name": person.full_name, "reference_id": person.linkedin_id,
            "in_full_candidates": person.find_best_match(people) is not None,
            "in_shortlist": person.find_best_match(shortlisted) is not None,
            "matched_name": match.full_name if match else None,
            "matched_id": match.linkedin_id if match else None,
            "possible_name_match": name_match.full_name if name_match else None,
            "possible_name_match_id": name_match.linkedin_id if name_match else None})
    rows = [{"full_name": p.full_name, "linkedin_id": p.linkedin_id, "email_addresses": p.email_addresses} for p in accepted]
    missing = [r for r in comparisons if r["matched_name"] is None]
    report = {"dataset": dataset, "model": os.environ["LLM_MODEL"], "seconds": round(elapsed, 2),
              "input_candidates": len(shortlisted), "output_people": rows, "reference_comparison": comparisons,
              "matched": len(reference) - len(missing), "reference_total": len(reference)}
    (output / f"{dataset}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    lines = [f"# {dataset}: weighted roster recall", "", "Isolated local-evidence reconciliation; no live website/search/scraping or production indexing. Manual reference was not supplied to this generation.", "",
             f"Shared-identity matches: {report['matched']}/{len(reference)}. Generated people: {len(accepted)}.", "",
             "| Reference name / ID | In shortlist | Returned name / ID | Possible name-only match |", "|---|---|---|---|"]
    for row in comparisons:
        lines.append(f"| {row['reference_name']} / {row['reference_id']} | {row['in_shortlist']} | {row['matched_name'] or 'UNMATCHED'} / {row['matched_id'] or ''} | {row['possible_name_match'] or ''} / {row['possible_name_match_id'] or ''} |")
    lines += ["", "## Generated roster", "", "| Name | LinkedIn ID | Emails |", "|---|---|---|"]
    lines += [f"| {p.full_name} | {p.linkedin_id} | {', '.join(p.email_addresses)} |" for p in accepted]
    (output / f"{dataset}.md").write_text("\n".join(lines) + "\n")
    assert not missing, f"Unmatched reference people: {[r['reference_name'] or r['reference_id'] for r in missing]}"
