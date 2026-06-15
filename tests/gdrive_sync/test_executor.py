from types import SimpleNamespace

from skills.gdrive_sync.executor import SyncExecutor, TransferProgress
from skills.gdrive_sync.types import OperationResult, PlannedAction


def test_executor_logs_numbered_upload_progress(caplog):
    local = SimpleNamespace(read_bytes=lambda _path: b"content")
    writes = []
    drive = SimpleNamespace(
        mkdir=lambda _path: None,
        write_bytes=lambda path, content: writes.append((path, content)),
    )
    executor = SyncExecutor(local=local, drive=drive)
    result = OperationResult(operation="push")
    progress = TransferProgress(total=2)

    with caplog.at_level("INFO"):
        executor.apply(
            PlannedAction("copy", "one.md", source="local", target="cloud"),
            result,
            dry_run=False,
            progress=progress,
        )
        executor.apply(
            PlannedAction("copy", "two.md", source="local", target="cloud"),
            result,
            dry_run=False,
            progress=progress,
        )

    assert writes == [("one.md", b"content"), ("two.md", b"content")]
    assert "upload 1/2 one.md (7 bytes)" in caplog.text
    assert "upload 2/2 two.md (7 bytes)" in caplog.text
