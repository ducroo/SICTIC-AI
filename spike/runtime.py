from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from lib.adapters.document_parser import document_parser_backend
from lib.adapters.vector_store import vector_store_backend
from lib.datasets.search import dataset_search
from lib.ephemeral_dataset import prepare_ephemeral_dataset


@dataclass(frozen=True)
class SkillInfo:
    name: str
    module: str


@dataclass(frozen=True)
class SpikeStatus:
    parser: str
    store: str
    llama_cloud_key: bool
    firebase_credentials: bool
    embedding_model: str
    skills: tuple[SkillInfo, ...]


@dataclass(frozen=True)
class SearchHit:
    document_name: str
    page_number: str
    text: str


@dataclass(frozen=True)
class DemoResult:
    dataset_name: str
    hits: tuple[SearchHit, ...]


def _repo_root() -> Path:
    configured = (os.environ.get("REPO_PATH") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def list_skills() -> tuple[SkillInfo, ...]:
    skills_dir = _repo_root() / "skills"
    found: list[SkillInfo] = []
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            if child.is_dir() and (child / "__main__.py").is_file():
                found.append(SkillInfo(name=child.name, module=f"skills.{child.name}"))
    return tuple(found)


def spike_status() -> SpikeStatus:
    return SpikeStatus(
        parser=document_parser_backend(),
        store=vector_store_backend(),
        llama_cloud_key=bool((os.environ.get("LLAMA_CLOUD_API_KEY") or "").strip()),
        firebase_credentials=bool(
            (os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
            or (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
            or (os.environ.get("FIREBASE_PROJECT_ID") or "").strip()
        ),
        embedding_model=(os.environ.get("EMBEDDING_MODEL") or "").strip(),
        skills=list_skills(),
    )


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip() or "upload.md"
    if name in {".", ".."}:
        return "upload.md"
    return name


async def run_demo(*, filename: str, payload: bytes, query: str) -> DemoResult:
    cleaned_query = query.strip()
    if not cleaned_query:
        raise ValueError("query is required")
    if not payload:
        raise ValueError("file is empty")
    safe_name = _safe_filename(filename)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / safe_name
        path.write_bytes(payload)
        dataset_name = await prepare_ephemeral_dataset([str(path)])
        chunks = await dataset_search(
            dataset_name,
            cleaned_query,
            max_chunks=8,
            raise_on_error=True,
        )
    hits = tuple(
        SearchHit(
            document_name=chunk.document_name,
            page_number=str(chunk.page_number),
            text=chunk.text,
        )
        for chunk in chunks
    )
    return DemoResult(dataset_name=dataset_name, hits=hits)
