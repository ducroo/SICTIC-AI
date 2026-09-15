"""Opt-in provider evaluation using evidence from the local benchmark.

SICTIC_DISCOVERY_PROVIDER_EVALUATION=1 authorizes configured provider calls.
SICTIC_DISCOVERY_BENCHMARK_OUTPUT selects the evidence/report directory.
This tests reconciliation, not production indexing, acquisition or freshness.
"""

import json
import os
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values

from lib.datasets.models import Chunk
from lib.people.model import Person
from lib.people.discovery import _render_manual_persons_table
from skills.persons_in_dataset.reconciliation import reconcile_people


@pytest.mark.asyncio
@pytest.mark.parametrize("dataset", ["avientus", "ovomind", "proud-technology", "herosupport"])
async def test_cached_evidence_reconciliation(dataset, monkeypatch):
    if os.getenv("SICTIC_DISCOVERY_PROVIDER_EVALUATION") != "1":
        pytest.skip("opt-in paid provider evaluation")
    output = Path(os.environ["SICTIC_DISCOVERY_BENCHMARK_OUTPUT"])
    source = output / f"{dataset}-evidence.json"
    assert source.exists(), "Run the local benchmark first"
    root = Path(__file__).resolve().parents[2]
    settings = dotenv_values(root / ".env")
    for key in ("LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY", "OPENAI_API_KEY", "OLLAMA_CONTEXT_LENGTH", "OLLAMA_CONTEXT_LENGTH_MAX"):
        if settings.get(key) is not None:
            monkeypatch.setenv(key, settings[key])
    # Keep operational logs off; redirect only shared provider measurements.
    from lib.infrastructure.ai_text_generation import generation, measurements
    monkeypatch.setattr(generation, "measurements_enabled", lambda: True)
    monkeypatch.setattr(measurements, "measurements_enabled", lambda: True)
    monkeypatch.setattr(measurements, "MEASUREMENT_FILE", output / f"{dataset}-usage.jsonl")
    evidence = json.loads(source.read_text())
    people = []
    for row in evidence["people"]:
        row["mentions"] = [Chunk(**chunk) for chunk in row["mentions"]]
        row["dossier"] = [Chunk(**chunk) for chunk in row["dossier"]]
        people.append(Person(**row))
    config = json.loads((root / "config/persons_in_dataset/discovery.json").read_text())
    started = time.monotonic()
    accepted = await reconcile_people(people, [Chunk(**c) for c in evidence["team_chunks"]],
        startup_context=evidence["startup_context"], company_names=[dataset], config=config)
    rows = [{"full_name": p.full_name, "linkedin_id": p.linkedin_id,
             "email_addresses": p.email_addresses,
             "sources": list(dict.fromkeys(f"{c.document_name} (page {c.page_number})" for c in p.mentions))}
            for p in accepted]
    (output / f"{dataset}-reconciled.json").write_text(json.dumps({
        "dataset": dataset, "seconds": round(time.monotonic() - started, 2),
        "model": os.environ["LLM_MODEL"], "persons": rows,
    }, indent=2, ensure_ascii=False))
    rendered = _render_manual_persons_table(dataset, accepted)
    rendered = rendered.replace(
        "Deal leads, feel free to add or remove employees - SICTIC-AI will remember the edits; this file will never be overwritten.",
        "Evaluation output for review only. This is not the production roster. Affiliations and identity matches still need review.",
    )
    (output / f"{dataset}-roster.md").write_text(rendered)
    assert accepted, "Expected supported team members in these populated data rooms"
