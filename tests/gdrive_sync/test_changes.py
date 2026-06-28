import logging

from skills.gdrive_sync.changes import _sleep_with_countdown


def test_sleep_with_countdown_logs_each_full_second(monkeypatch, caplog):
    sleeps = []
    monkeypatch.setattr("skills.gdrive_sync.changes.time.sleep", sleeps.append)
    caplog.set_level(logging.INFO, logger="skills.gdrive_sync.changes")

    _sleep_with_countdown(3.25)

    assert sleeps == [1.0, 1.0, 1.0, 0.25]
    assert [
        record.getMessage()
        for record in caplog.records
    ] == [
        "Drive quiet wait countdown: 3",
        "Drive quiet wait countdown: 2",
        "Drive quiet wait countdown: 1",
    ]
