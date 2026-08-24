from __future__ import annotations

from pathlib import Path

import pytest
from lib.datasets.models import Chunk

from spike.runtime import list_skills, run_demo, spike_status


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_spike_status_reads_backends_and_secret_presence(monkeypatch, tmp_path):
    skills = tmp_path / "skills"
    (skills / "alpha").mkdir(parents=True)
    (skills / "alpha" / "__main__.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("REPO_PATH", str(tmp_path))
    monkeypatch.setenv("DOCUMENT_PARSER", "llamaparse")  # pragma: allowlist secret
    monkeypatch.setenv("VECTOR_STORE", "firestore")  # pragma: allowlist secret
    monkeypatch.setenv("LLAMA_CLOUD_API_KEY", "llx-test")
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo-project")
    monkeypatch.setenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")

    status = spike_status()

    assert status.parser == "llamaparse"  # pragma: allowlist secret
    assert status.store == "firestore"  # pragma: allowlist secret
    assert status.llama_cloud_key is True
    assert status.firebase_credentials is True
    assert status.embedding_model == "openai/text-embedding-3-small"
    assert [skill.name for skill in status.skills] == ["alpha"]
    assert status.skills[0].module == "skills.alpha"


def test_spike_status_secret_flags_absent_and_empty_embedding_model(monkeypatch):
    monkeypatch.setenv("DOCUMENT_PARSER", "docling")  # pragma: allowlist secret
    monkeypatch.setenv("VECTOR_STORE", "qdrant")  # pragma: allowlist secret
    monkeypatch.delenv("LLAMA_CLOUD_API_KEY", raising=False)
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)

    status = spike_status()

    assert status.parser == "docling"  # pragma: allowlist secret
    assert status.store == "qdrant"  # pragma: allowlist secret
    assert status.llama_cloud_key is False
    assert status.firebase_credentials is False
    assert status.embedding_model == ""


def test_list_skills_sorted_and_requires_main(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    (skills / "zeta").mkdir(parents=True)
    (skills / "alpha").mkdir()
    (skills / "skipped").mkdir()
    (skills / "alpha" / "__main__.py").write_text("", encoding="utf-8")
    (skills / "zeta" / "__main__.py").write_text("", encoding="utf-8")
    (skills / "skipped" / "README.md").write_text("", encoding="utf-8")
    monkeypatch.setenv("REPO_PATH", str(tmp_path))

    infos = list_skills()

    assert [item.name for item in infos] == ["alpha", "zeta"]
    assert [item.module for item in infos] == ["skills.alpha", "skills.zeta"]


def test_list_skills_falls_back_to_parent_of_lib(monkeypatch):
    monkeypatch.delenv("REPO_PATH", raising=False)
    names = [item.name for item in list_skills()]
    assert "dataset_chat" in names
    assert names == sorted(names)


def test_run_demo_requires_query():
    import asyncio

    with pytest.raises(ValueError, match="query"):
        asyncio.run(run_demo(filename="note.md", payload=b"# hi\n", query="  "))


@pytest.mark.asyncio
async def test_run_demo_writes_payload_and_maps_chunks(mocker):
    captured: dict[str, object] = {}

    async def fake_prepare(files, temp_name="temp"):
        path = Path(files[0])
        captured["name"] = path.name
        captured["payload"] = path.read_bytes()
        return "temp"

    async def fake_search(dataset_name, query, max_chunks=25, raise_on_error=False):
        captured["dataset_name"] = dataset_name
        captured["query"] = query
        captured["raise_on_error"] = raise_on_error
        return [
            Chunk(
                chunk_id="1",
                document_name="note.md",
                page_number=2,
                last_modified=1.0,
                text="Acme builds arms",
            )
        ]

    mocker.patch("spike.runtime.prepare_ephemeral_dataset", side_effect=fake_prepare)
    mocker.patch("spike.runtime.dataset_search", side_effect=fake_search)

    result = await run_demo(
        filename="../evil.md",
        payload=b"# Acme\n",
        query="what does it do?",
    )

    assert captured["name"] == "evil.md"
    assert captured["payload"] == b"# Acme\n"
    assert captured["dataset_name"] == "temp"
    assert captured["query"] == "what does it do?"
    assert captured["raise_on_error"] is True
    assert result.dataset_name == "temp"
    assert result.hits[0].page_number == "2"
    assert "arms" in result.hits[0].text


def test_parse_json_demo_requires_object_query_and_markdown():
    from spike.web import parse_json_demo

    with pytest.raises(ValueError, match="JSON object"):
        parse_json_demo(["nope"])
    with pytest.raises(ValueError, match="Query and markdown"):
        parse_json_demo({"query": "what", "markdown": "  "})
    demo = parse_json_demo({"query": "what", "markdown": "# Acme\n"})
    assert demo.filename == "note.md"
    assert demo.query == "what"
    assert demo.payload == b"# Acme\n"


def test_emulator_config_skips_database_emulator():
    import json

    config = json.loads((REPO_ROOT / "firebase.json").read_text(encoding="utf-8"))
    emulators = config.get("emulators") or {}
    assert "hosting" in emulators
    assert "functions" in emulators
    assert set(emulators) <= {"hosting", "functions", "ui"}


def test_hosting_rewrites_api_to_function():
    import json

    config = json.loads((REPO_ROOT / "firebase.json").read_text(encoding="utf-8"))
    rewrites = config["hosting"]["rewrites"]
    api = next(rule for rule in rewrites if rule.get("source") == "/api/**")
    function = api.get("function")
    if isinstance(function, dict):
        assert function.get("functionId") == "spikeGateway"
    else:
        assert function == "spikeGateway"


def test_image_omits_heavy_local_stack():
    blob = (
        (REPO_ROOT / "spike" / "Dockerfile").read_text(encoding="utf-8")
        + (REPO_ROOT / "spike" / "requirements.txt").read_text(encoding="utf-8")
    ).lower()
    for banned in ("torch", "docling", "qdrant-client", "onnxruntime", "ocrmac"):
        assert banned not in blob
