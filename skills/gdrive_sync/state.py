from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import fields
from pathlib import Path

from .types import SnapshotEntry
from .util import clean_rel


_SNAPSHOT_ENTRY_FIELDS = {field.name for field in fields(SnapshotEntry)}


def _snapshot_entry(data: dict, *, path: str) -> SnapshotEntry:
    """Load current entries while ignoring fields from older state schemas."""
    normalized = {
        key: value
        for key, value in data.items()
        if key in _SNAPSHOT_ENTRY_FIELDS
    }
    normalized["path"] = clean_rel(normalized.get("path") or path)
    return SnapshotEntry(**normalized)


def default_state_dir() -> Path:
    repo_root = os.environ.get("REPO_PATH")
    if repo_root:
        return Path(repo_root).expanduser() / "gdrive_sync_state"
    return Path(__file__).resolve().parents[2] / "gdrive_sync_state"


class SyncState:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                create table if not exists metadata (
                    key text primary key,
                    value text not null
                )
                """
            )
            con.execute(
                """
                create table if not exists baseline (
                    path text primary key,
                    entry_json text not null
                )
                """
            )
            con.execute(
                """
                create table if not exists checkpoint (
                    operation_id text not null,
                    path text not null,
                    entry_json text not null,
                    completed_at real not null default (unixepoch('subsec')),
                    primary key (operation_id, path)
                )
                """
            )

    def get_metadata(self, key: str) -> str | None:
        with self._connect() as con:
            row = con.execute("select value from metadata where key = ?", (key,)).fetchone()
            return None if row is None else str(row["value"])

    def set_metadata(self, key: str, value: str) -> None:
        with self._connect() as con:
            con.execute(
                "insert into metadata(key, value) values(?, ?) on conflict(key) do update set value = excluded.value",
                (key, value),
            )

    def load_baseline(self) -> dict[str, SnapshotEntry]:
        with self._connect() as con:
            rows = con.execute("select path, entry_json from baseline").fetchall()
        out: dict[str, SnapshotEntry] = {}
        for row in rows:
            data = json.loads(row["entry_json"])
            path = clean_rel(row["path"])
            out[path] = _snapshot_entry(data, path=path)
        return out

    def save_baseline(self, entries: dict[str, SnapshotEntry]) -> None:
        with self._connect() as con:
            con.execute("delete from baseline")
            con.executemany(
                "insert into baseline(path, entry_json) values(?, ?)",
                [
                    (
                        clean_rel(path),
                        json.dumps({**entry.__dict__, "path": clean_rel(entry.path)}, sort_keys=True),
                    )
                    for path, entry in entries.items()
                ],
            )

    def baseline_by_drive_id(self) -> dict[str, SnapshotEntry]:
        out: dict[str, SnapshotEntry] = {}
        for entry in self.load_baseline().values():
            if entry.drive_id:
                out[entry.drive_id] = entry
        return out

    def upsert_baseline_entry(self, entry: SnapshotEntry) -> None:
        path = clean_rel(entry.path)
        with self._connect() as con:
            data = {**entry.__dict__, "path": path}
            con.execute(
                """
                insert into baseline(path, entry_json) values(?, ?)
                on conflict(path) do update set entry_json = excluded.entry_json
                """,
                (path, json.dumps(data, sort_keys=True)),
            )

    def delete_baseline_path(self, path: str, *, include_descendants: bool = False) -> None:
        path = clean_rel(path)
        with self._connect() as con:
            con.execute("delete from baseline where path = ?", (path,))
            if include_descendants:
                con.execute("delete from baseline where path like ?", (f"{path}/%",))

    def clear_checkpoint(self, operation_id: str) -> None:
        with self._connect() as con:
            con.execute("delete from checkpoint where operation_id = ?", (operation_id,))

    def load_checkpoint(self, operation_id: str) -> dict[str, SnapshotEntry]:
        with self._connect() as con:
            rows = con.execute(
                "select path, entry_json from checkpoint where operation_id = ?",
                (operation_id,),
            ).fetchall()
        out: dict[str, SnapshotEntry] = {}
        for row in rows:
            data = json.loads(row["entry_json"])
            path = clean_rel(row["path"])
            out[path] = _snapshot_entry(data, path=path)
        return out

    def save_checkpoint_entry(self, operation_id: str, entry: SnapshotEntry) -> None:
        path = clean_rel(entry.path)
        with self._connect() as con:
            con.execute(
                """
                insert into checkpoint(operation_id, path, entry_json)
                values(?, ?, ?)
                on conflict(operation_id, path) do update set
                    entry_json = excluded.entry_json,
                    completed_at = unixepoch('subsec')
                """,
                (operation_id, path, json.dumps({**entry.__dict__, "path": path}, sort_keys=True)),
            )

    def promote_checkpoint_to_baseline(self, operation_id: str) -> None:
        with self._connect() as con:
            con.execute("delete from baseline")
            con.execute(
                """
                insert into baseline(path, entry_json)
                select path, entry_json
                from checkpoint
                where operation_id = ?
                """,
                (operation_id,),
            )
            con.execute("delete from checkpoint where operation_id = ?", (operation_id,))
