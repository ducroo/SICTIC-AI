import pytest

from spike import app_check


def test_firebase_project_id_reads_service_account_json(monkeypatch):
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    monkeypatch.setenv(
        "FIREBASE_SERVICE_ACCOUNT_JSON",
        '{"project_id":"review-deck-a3c26","type":"service_account"}',
    )
    assert app_check.firebase_project_id() == "review-deck-a3c26"


def test_app_check_required_follows_explicit_flag(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")
    monkeypatch.setenv("SPIKE_REQUIRE_APP_CHECK", "0")
    assert app_check.app_check_required() is False
    monkeypatch.setenv("SPIKE_REQUIRE_APP_CHECK", "1")
    assert app_check.app_check_required() is True


def test_verify_app_check_token_checks_issuer_and_audience(monkeypatch, mocker):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")
    class FakeKey:
        key = "secret"

    mocker.patch.object(
        app_check,
        "_jwks",
        return_value=mocker.Mock(get_signing_key_from_jwt=lambda _token: FakeKey()),
    )
    mocker.patch(
        "spike.app_check.jwt.decode",
        return_value={
            "iss": app_check.APP_CHECK_ISSUER,
            "sub": "1:224218759787:web:84cf6f9973748262dda72e",
            "exp": 9999999999,
            "iat": 1,
        },
    )
    claims = app_check.verify_app_check_token("token")
    assert claims["sub"].endswith(":web:84cf6f9973748262dda72e")


def test_verify_app_check_token_rejects_empty(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")
    with pytest.raises(ValueError, match="missing"):
        app_check.verify_app_check_token("  ")
