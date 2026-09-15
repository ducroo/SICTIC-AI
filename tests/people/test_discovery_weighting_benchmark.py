"""Opt-in replay of saved local evidence; no NER, network or production writes."""

import json
import os
from pathlib import Path

import pytest

from lib.datasets.models import Chunk
from lib.infrastructure.configuration import load_repository_config
from lib.people.extraction import rank_people_by_document_weight
from lib.people.model import Person
from skills.persons_in_dataset.persons_in_dataset import _shortlist_ner_people
from skills.persons_in_dataset.reconciliation import _prepare_prompts


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
    shortlisted = _shortlist_ner_people(people, config["ner_max_candidates"])
    prompts = _prepare_prompts(shortlisted, [Chunk(**c) for c in evidence["team_chunks"]],
                               startup_context=evidence["startup_context"], company_names=[dataset], config=config)
    report = {"dataset": dataset, "original_candidates": len(people),
              "shortlisted_with_independent_contacts": len(shortlisted),
              "prompt_batches": len(prompts), "prompt_characters": sum(map(len, prompts)),
              "top_names": [{"name": p.full_name, "weight": score} for p, score in ranked[:config["ner_max_candidates"]]]}
    (directory / f"{dataset}-weighted.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != "top_names"}))
    assert len([p for p in shortlisted if p.full_name and not p.linkedin_id
                and not p.email_addresses and not any(c.document_name.startswith("website/") for c in p.mentions)]) <= config["ner_max_candidates"]
    assert len(prompts) <= config["max_reconciliation_calls"]
