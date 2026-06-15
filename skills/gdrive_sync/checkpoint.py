from __future__ import annotations

import logging
import uuid

from .types import SnapshotEntry

logger = logging.getLogger(__name__)


class CheckpointManager:
    def __init__(self, *, state, drive):
        self.state = state
        self.drive = drive

    def begin_or_resume_pull(self, *, dry_run: bool) -> str:
        active_operation_id = self.state.get_metadata("active_operation_id")
        if active_operation_id and active_operation_id.startswith("pull-"):
            operation_id = active_operation_id
            logger.info("pull resuming checkpoint %s", operation_id)
        else:
            operation_id = f"pull-{uuid.uuid4().hex}"
            logger.info("pull starting checkpoint %s", operation_id)
        if not dry_run:
            self.state.set_metadata("active_operation_id", operation_id)
        return operation_id

    def update_drive_token(self, token: str | None = None) -> None:
        token = token or self.drive.start_page_token()
        if token:
            self.state.set_metadata("drive_start_page_token", token)

    def commit_streaming_pull(self, operation_id: str) -> None:
        self.state.promote_checkpoint_to_baseline(operation_id)
        self.update_drive_token()
        self.state.set_metadata("active_operation_id", "")

    def commit_full_baseline(
        self,
        entries: dict[str, SnapshotEntry],
    ) -> None:
        self.state.save_baseline(entries)
        self.update_drive_token()


def merged_baseline(
    local_snapshot: dict[str, SnapshotEntry],
    cloud_snapshot: dict[str, SnapshotEntry],
) -> dict[str, SnapshotEntry]:
    merged = dict(local_snapshot)
    for path, entry in cloud_snapshot.items():
        merged.setdefault(path, entry)
    return merged
