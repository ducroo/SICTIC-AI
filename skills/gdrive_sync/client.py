from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from googleapiclient.errors import HttpError

import lib.env  # noqa: F401 - load repo .env regardless of cwd

from .bootstrap import run_bootstrap_pull
from .context import SyncContext
from .drive import DriveTree
from .incremental import run_incremental_pull, run_incremental_sync
from .local import LocalTree
from .lock import PairingLock
from .logging_config import configure_logging
from .state import SyncState, default_state_dir
from .types import (
    ConflictPolicy,
    OperationResult,
    SnapshotEntry,
    SyncOperationFailed,
)

logger = logging.getLogger(__name__)


class GDriveSync:
    """Configure a local/Drive pairing and dispatch synchronization workflows."""

    def __init__(
        self,
        *,
        local_root: str | None = None,
        gdrive_root: str | None = None,
        credentials_path: str | None = None,
        token_path: str | None = None,
        exclude: list[str] | None = None,
        lock_timeout: float = 1800,
        state_dir: str | None = None,
        log_dir: str | None = None,
        verbose: bool = False,
    ):
        configure_logging(log_dir, verbose=verbose)
        cloud_provider = os.environ.get("CLOUD_PROVIDER", "").strip().lower()
        if cloud_provider != "google":
            raise ValueError("skills.gdrive_sync requires CLOUD_PROVIDER=google")

        self.local_root = local_root or os.environ.get("LOCAL_STORAGE_PATH")
        self.gdrive_root = (
            gdrive_root
            or os.environ.get("CLOUD_STORAGE_PATH")
            or "root"
        )
        self.credentials_path = (
            credentials_path
            or os.environ.get("GDRIVE_CREDENTIALS")
            or os.path.expanduser(
                "~/.openclaw/gdrive-ops-credentials.json"
            )
        )
        self.token_path = (
            token_path
            or os.environ.get("GDRIVE_TOKEN")
            or os.path.expanduser("~/.openclaw/gdrive-ops-token.json")
        )
        if not self.local_root:
            raise ValueError(
                "local_root is required or LOCAL_STORAGE_PATH must be set"
            )
        if not os.path.isabs(self.local_root):
            raise ValueError(
                f"local_root must be absolute: {self.local_root}"
            )

        self.exclude = exclude or []
        self.lock_timeout = lock_timeout
        self.local = LocalTree(self.local_root, exclude=self.exclude)
        self.drive = DriveTree(
            root_folder_id=self.gdrive_root,
            credentials_path=self.credentials_path,
            token_path=self.token_path,
            exclude=self.exclude,
        )
        self.identity = self._pairing_identity()
        root_state_dir = (
            Path(state_dir).expanduser()
            if state_dir
            else default_state_dir()
        )
        self.pairing_dir = root_state_dir / self.identity
        self.state = SyncState(self.pairing_dir / "state.sqlite3")
        self.lock_path = self.pairing_dir / "pairing.lock"

    def pull(self, dry_run: bool = False) -> OperationResult:
        active_operation_id = self.state.get_metadata(
            "active_operation_id"
        )
        baseline = self.state.load_baseline()
        token = self.state.get_metadata("drive_start_page_token")
        if token and baseline and not active_operation_id:
            try:
                return self._run_pull_incremental(
                    token=token,
                    baseline=baseline,
                    dry_run=dry_run,
                )
            except HttpError as error:
                if getattr(error.resp, "status", None) == 410:
                    logger.warning(
                        "Drive changes token expired; "
                        "falling back to full pull"
                    )
                else:
                    raise
        return self._run_pull_streaming(dry_run=dry_run)

    def sync(
        self,
        *,
        conflict_policy: ConflictPolicy = "local-wins",
        dry_run: bool = False,
    ) -> OperationResult:
        return self._dispatch_incremental_sync(
            conflict_policy=conflict_policy,
            dry_run=dry_run,
        )

    def _pairing_identity(self) -> str:
        raw = (
            f"{Path(self.local_root).resolve()}|{self.gdrive_root}|"
            f"{Path(self.token_path).expanduser()}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _context(self) -> SyncContext:
        return SyncContext(
            local=self.local,
            drive=self.drive,
            state=self.state,
            lock_path=self.lock_path,
            lock_timeout=self.lock_timeout,
            lock_factory=PairingLock,
        )

    def _dispatch_incremental_sync(
        self,
        *,
        conflict_policy: ConflictPolicy,
        dry_run: bool,
    ) -> OperationResult:
        active_operation_id = self.state.get_metadata("active_operation_id")
        baseline = self.state.load_baseline()
        token = self.state.get_metadata("drive_start_page_token")
        if token and baseline and not active_operation_id:
            try:
                return self._run_sync_incremental(
                    token=token,
                    baseline=baseline,
                    conflict_policy=conflict_policy,
                    dry_run=dry_run,
                )
            except HttpError as error:
                if getattr(error.resp, "status", None) != 410:
                    raise
                result = OperationResult(
                    operation="sync",
                    dry_run=dry_run,
                )
                result.failures.append(
                    "Drive changes token expired; run "
                    "`python -m skills.gdrive_sync pull` to refresh the "
                    "baseline before incremental sync."
                )
                raise SyncOperationFailed(
                    "incremental sync cannot continue",
                    partial_result=result,
                ) from error

        result = OperationResult(operation="sync", dry_run=dry_run)
        if active_operation_id:
            result.failures.append(
                "cannot sync while operation checkpoint is active: "
                f"{active_operation_id}"
            )
        elif not baseline:
            result.failures.append(
                "cannot incremental sync without a successful baseline; "
                "run `python -m skills.gdrive_sync pull` first"
            )
        elif not token:
            result.failures.append(
                "cannot incremental sync without a Drive changes token; "
                "run `python -m skills.gdrive_sync pull` first"
            )
        else:
            result.failures.append(
                "cannot incremental sync; unknown prerequisite failure"
            )
        raise SyncOperationFailed(
            "incremental sync prerequisites missing",
            partial_result=result,
        )

    def _run_pull_streaming(self, *, dry_run: bool) -> OperationResult:
        return run_bootstrap_pull(self._context(), dry_run=dry_run)

    def _run_pull_incremental(
        self,
        *,
        token: str,
        baseline: dict[str, SnapshotEntry],
        dry_run: bool,
    ) -> OperationResult:
        return run_incremental_pull(
            self._context(),
            token=token,
            baseline=baseline,
            dry_run=dry_run,
        )

    def _run_sync_incremental(
        self,
        *,
        token: str,
        baseline: dict[str, SnapshotEntry],
        conflict_policy: ConflictPolicy,
        dry_run: bool,
    ) -> OperationResult:
        return run_incremental_sync(
            self._context(),
            token=token,
            baseline=baseline,
            conflict_policy=conflict_policy,
            dry_run=dry_run,
        )
