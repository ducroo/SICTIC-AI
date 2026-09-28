"""Opt-in replay of saved local evidence; no NER, network or production writes."""

import json
import os
from pathlib import Path

import pytest

from lib.datasets.models import Chunk
from lib.infrastructure.configuration import load_repository_config
from lib.people.extraction import rank_people_by_document_weight
from lib.people.model import Person
from skills.persons_in_dataset.reconciliation import _prepare_prompt


@pytest.mark.parametrize("dataset", ["avientus", "ovomind", "proud-technology", "herosupport", "scanvio", "miraex"])
def test_weighted_evidence_fits_reconciliation_budget(dataset, monkeypatch):
    output = os.getenv("SICTIC_DISCOVERY_BENCHMARK_OUTPUT")
    if not output:
        pytest.skip("opt-in local evidence replay")
    directory = Path(output)
    evidence = json.loads((directory / f"{dataset}-evidence.json").read_text())
    people = [Person(**{**row, "mentions": [Chunk(**c) for c in row["mentions"]],
                        "dossier": [Chunk(**c) for c in row["dossier"]]}) for row in evidence["people"]]
    config = load_repository_config("persons_in_dataset", "discovery")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "262144")
    ranked = rank_people_by_document_weight(people)
    prompt, shortlisted = _prepare_prompt(people, [Chunk(**c) for c in evidence["team_chunks"]],
                               startup_context=evidence["startup_context"], company_names=[dataset], config=config)
    report = {"dataset": dataset, "original_candidates": len(people),
              "shortlisted_with_independent_contacts": len(shortlisted),
              "prompt_batches": 1, "prompt_characters": len(prompt),
              "top_names": [{"name": p.full_name, "weight": score} for p, score in ranked[:30]]}
    (directory / f"{dataset}-weighted.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != "top_names"}))
    assert isinstance(prompt, str)
    assert {p.linkedin_id for p in people if p.linkedin_id} <= {p.linkedin_id for p in shortlisted}
