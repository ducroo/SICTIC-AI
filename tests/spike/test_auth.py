import pytest

from spike import auth


def test_auth_required_follows_explicit_flag(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")
    monkeypatch.setenv("SPIKE_REQUIRE_AUTH", "0")
    assert auth.auth_required() is False
    monkeypatch.setenv("SPIKE_REQUIRE_AUTH", "1")
    assert auth.auth_required() is True


def test_expected_issuer_uses_project_id():
    assert auth.expected_issuer("review-deck-a3c26") == (
        "https://securetoken.google.com/review-deck-a3c26"
    )


def test_id_token_from_headers_reads_bearer():
    assert auth.id_token_from_headers({"Authorization": "Bearer abc.def"}) == "abc.def"
    assert auth.id_token_from_headers({"authorization": "bearer xyz"}) == "xyz"
    assert auth.id_token_from_headers({}) == ""


def test_verify_id_token_checks_issuer(monkeypatch, mocker):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")

    class FakeKey:
        key = "secret"

    mocker.patch.object(
        auth,
        "_jwks",
        return_value=mocker.Mock(get_signing_key_from_jwt=lambda _token: FakeKey()),
    )
    decode = mocker.patch(
        "spike.auth.jwt.decode",
        return_value={
            "iss": "https://securetoken.google.com/review-deck-a3c26",
            "aud": "review-deck-a3c26",
            "sub": "user-123",
            "email": "founder@example.com",
            "email_verified": True,
            "exp": 9999999999,
            "iat": 1,
        },
    )
    claims = auth.verify_id_token("token")
    assert claims["sub"] == "user-123"
    assert decode.call_args.kwargs["audience"] == "review-deck-a3c26"


def test_verify_id_token_rejects_unverified_email(monkeypatch, mocker):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")

    class FakeKey:
        key = "secret"

    mocker.patch.object(
        auth,
        "_jwks",
        return_value=mocker.Mock(get_signing_key_from_jwt=lambda _token: FakeKey()),
    )
    mocker.patch(
        "spike.auth.jwt.decode",
        return_value={
            "iss": "https://securetoken.google.com/review-deck-a3c26",
            "aud": "review-deck-a3c26",
            "sub": "user-123",
            "email": "fake@example.com",
            "email_verified": False,
            "exp": 9999999999,
            "iat": 1,
        },
    )
    with pytest.raises(ValueError, match="Verify your email"):
        auth.verify_id_token("token")


def test_verify_id_token_rejects_empty(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")
    with pytest.raises(ValueError, match="required"):
        auth.verify_id_token("  ")
