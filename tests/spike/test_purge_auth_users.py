from spike.purge_auth_users import AuthUserRecord, purge_auth_users_older_than


def test_purge_auth_users_deletes_only_stale_profiles(mocker):
    now_ms = 1_700_000_000_000
    users = [
        AuthUserRecord("old", "old@example.com", created_at_ms=1_000, display_name="Old"),
        AuthUserRecord(
            "fresh",
            "fresh@example.com",
            created_at_ms=now_ms - 86_400_000,
            display_name="Fresh",
        ),
    ]
    mocker.patch("spike.purge_auth_users.list_auth_users", return_value=users)
    delete = mocker.patch("spike.purge_auth_users.delete_auth_user")

    result = purge_auth_users_older_than(
        days=60,
        dry_run=False,
        now_ms=now_ms,
    )

    assert result.scanned == 2
    assert result.deleted == 1
    assert result.deleted_emails == ("old@example.com",)
    delete.assert_called_once_with("old", project_id=None)


def test_purge_auth_users_dry_run_does_not_delete(mocker):
    users = [
        AuthUserRecord("old", "old@example.com", created_at_ms=1_000, display_name=""),
    ]
    mocker.patch("spike.purge_auth_users.list_auth_users", return_value=users)
    delete = mocker.patch("spike.purge_auth_users.delete_auth_user")

    result = purge_auth_users_older_than(
        days=60,
        dry_run=True,
        now_ms=1_700_000_000_000,
    )

    assert result.dry_run is True
    assert result.deleted == 1
    delete.assert_not_called()
