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
class HarnessCommandInfo:
    name: str
    usage: str
    description: str


@dataclass(frozen=True)
class SpikeStatus:
    parser: str
    store: str
    llama_cloud_key: bool
    firebase_credentials: bool
    firebase_project_id: str
    embedding_model: str
    skills: tuple[SkillInfo, ...]
    commands: tuple[HarnessCommandInfo, ...]


@dataclass(frozen=True)
class SkillCall:
    skill: str
    args: str
    command: str


@dataclass(frozen=True)
class SkillResult:
    skill: str
    args: str
    command: str
    output: str


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


def list_harness_commands() -> tuple[HarnessCommandInfo, ...]:
    from skills.harness.harness import build_registry

    found: list[HarnessCommandInfo] = []
    for command in build_registry().values():
        name = command.name.lstrip("/")
        found.append(
            HarnessCommandInfo(
                name=name,
                usage=command.usage,
                description=command.description,
            )
        )
    return tuple(found)


def allowed_skill_names() -> frozenset[str]:
    return frozenset(command.name for command in list_harness_commands())


def parse_skill_call(*, skill: str, args: str) -> SkillCall:
    cleaned_skill = skill.strip().lstrip("/")
    if not cleaned_skill.isidentifier() or not cleaned_skill.islower():
        raise ValueError("Skill name is invalid.")
    if cleaned_skill not in allowed_skill_names():
        raise ValueError(f"Unknown harness skill: {cleaned_skill}")
    cleaned_args = " ".join(args.split())
    if "\x00" in cleaned_args:
        raise ValueError("Arguments are invalid.")
    if len(cleaned_args) > 4000:
        raise ValueError("Arguments are too long.")
    command = f"/{cleaned_skill}"
    if cleaned_args:
        command = f"{command} {cleaned_args}"
    return SkillCall(skill=cleaned_skill, args=cleaned_args, command=command)


async def run_skill(call: SkillCall) -> SkillResult:
    from skills.harness.harness import dispatch_command

    output = await dispatch_command(call.command)
    if output == "__EXIT__":
        raise ValueError("That command is not runnable here.")
    return SkillResult(
        skill=call.skill,
        args=call.args,
        command=call.command,
        output=output or "",
    )


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
        firebase_project_id=(os.environ.get("FIREBASE_PROJECT_ID") or "").strip(),
        skills=list_skills(),
        commands=list_harness_commands(),
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
