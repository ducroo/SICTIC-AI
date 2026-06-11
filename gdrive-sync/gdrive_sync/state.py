from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .types import SnapshotEntry


def default_state_dir() -> Path:
    return Path(__file__).resolve().parents[1] / ".state"


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
            out[row["path"]] = SnapshotEntry(**data)
        return out

    def save_baseline(self, entries: dict[str, SnapshotEntry]) -> None:
        with self._connect() as con:
            con.execute("delete from baseline")
            con.executemany(
                "insert into baseline(path, entry_json) values(?, ?)",
                [(path, json.dumps(entry.__dict__, sort_keys=True)) for path, entry in entries.items()],
            )

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
            out[row["path"]] = SnapshotEntry(**data)
        return out

    def save_checkpoint_entry(self, operation_id: str, entry: SnapshotEntry) -> None:
        with self._connect() as con:
            con.execute(
                """
                insert into checkpoint(operation_id, path, entry_json)
                values(?, ?, ?)
                on conflict(operation_id, path) do update set
                    entry_json = excluded.entry_json,
                    completed_at = unixepoch('subsec')
                """,
                (operation_id, entry.path, json.dumps(entry.__dict__, sort_keys=True)),
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
