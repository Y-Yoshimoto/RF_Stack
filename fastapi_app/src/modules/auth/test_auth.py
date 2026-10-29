#!/usr/bin/env python
# coding:utf-8
"""認証まわり (Realm 検証 / PKCE / id_token 検証 / 秘密鍵検証) のユニットテスト。"""
import hashlib
import time
from base64 import urlsafe_b64encode

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from modules.auth import environment, token

# ---------------------------------------------------------------- Realm 検証


@pytest.mark.parametrize("realm_name", ["master", "tenant-a", "tenant_b", "Realm123"])
def test_validate_realm_name_accepts_valid_names(realm_name):
    """許可された文字種の Realm 名はそのまま返ること。"""
    assert environment.validate_realm_name(realm_name) == realm_name


def test_validate_realm_name_strips_whitespace():
    """前後の空白は除去されること。"""
    assert environment.validate_realm_name("  master  ") == "master"


@pytest.mark.parametrize(
    "realm_name",
    ["", "   ", "../../evil", "a/b", "tenant a", "tenant.a", "x" * 65, "tenant-a\nx"],
)
def test_validate_realm_name_rejects_invalid_names(realm_name):
    """パス区切りや相対パス指定を含む Realm 名は拒否されること。"""
    with pytest.raises(ValueError):
        environment.validate_realm_name(realm_name)


def test_realm_name_pattern_rejects_trailing_newline():
    """パターン単体でも末尾の改行を許さないこと (``$`` は末尾の改行 1 つに一致するため fullmatch で判定する)。"""
    assert environment.REALM_NAME_PATTERN.fullmatch("tenant-a") is not None
    assert environment.REALM_NAME_PATTERN.fullmatch("tenant-a\n") is None


# ---------------------------------------------------------------------- PKCE


def test_generate_pkce_pair_uses_s256():
    """code_challenge が code_verifier の SHA-256 を Base64URL 化した値であること。"""
    code_verifier, code_challenge = token.generate_pkce_pair()

    expected = urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
    assert code_challenge == expected.decode("ascii").rstrip("=")
    # Base64URL のパディングが残っていないこと
    assert "=" not in code_verifier
    assert "=" not in code_challenge


def test_generate_pkce_pair_is_random():
    """呼び出しごとに異なる code_verifier が生成されること。"""
    assert token.generate_pkce_pair()[0] != token.generate_pkce_pair()[0]


# ------------------------------------------------------------ id_token 検証


class _StubSigningKey:
    """PyJWKClient が返す署名鍵オブジェクトのスタブ。"""

    def __init__(self, key):
        self.key = key


class _StubJwksClient:
    """JWKS 取得を行わずに固定の公開鍵を返すスタブ。"""

    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, _token):
        """署名鍵を返す (JWT の内容には依存しない)。"""
        return _StubSigningKey(self._key)


@pytest.fixture
def rsa_key_pair():
    """テスト用の RSA 鍵ペアを生成する。"""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def patch_jwks(monkeypatch, rsa_key_pair):
    """``token._jwks_client`` を公開鍵を返すスタブに差し替える。"""
    _, public_key = rsa_key_pair
    monkeypatch.setattr(token, "_jwks_client", lambda _uri: _StubJwksClient(public_key))
    return public_key


def _issue_id_token(private_key, **overrides):
    """テスト用の id_token を発行する。"""
    claims = {
        "iss": "http://keycloak_c:8080/keycloak/realms/master",
        "aud": "fastapi-app",
        "sub": "user-1",
        "preferred_username": "tester",
        "email": "tester@example.com",
        "nonce": "expected-nonce",
        "iat": 1_000_000_000,
        "exp": 4_000_000_000,
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


ALLOWED_ISSUERS = [
    "http://keycloak_c:8080/keycloak/realms/master",
    "http://localhost:8080/keycloak/realms/master",
]


def test_verify_id_token_accepts_valid_token(rsa_key_pair, patch_jwks):
    """署名・aud・iss・nonce がすべて正しい id_token を受理すること。"""
    private_key, _ = rsa_key_pair
    claims = token.verify_id_token(
        _issue_id_token(private_key),
        jwks_uri="http://keycloak_c:8080/jwks",
        audience="fastapi-app",
        allowed_issuers=ALLOWED_ISSUERS,
        expected_nonce="expected-nonce",
    )
    assert claims["sub"] == "user-1"
    assert claims["preferred_username"] == "tester"


def test_verify_id_token_rejects_wrong_signature(rsa_key_pair, patch_jwks):
    """別の鍵で署名された id_token を拒否すること。"""
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(jwt.PyJWTError):
        token.verify_id_token(
            _issue_id_token(other_key),
            jwks_uri="http://keycloak_c:8080/jwks",
            audience="fastapi-app",
            allowed_issuers=ALLOWED_ISSUERS,
            expected_nonce="expected-nonce",
        )


def test_verify_id_token_rejects_expired_token(rsa_key_pair, patch_jwks):
    """期限切れの id_token を拒否すること。"""
    private_key, _ = rsa_key_pair
    with pytest.raises(jwt.ExpiredSignatureError):
        token.verify_id_token(
            _issue_id_token(private_key, exp=1_000_000_100),
            jwks_uri="http://keycloak_c:8080/jwks",
            audience="fastapi-app",
            allowed_issuers=ALLOWED_ISSUERS,
            expected_nonce="expected-nonce",
        )


def test_verify_id_token_rejects_wrong_audience(rsa_key_pair, patch_jwks):
    """aud が一致しない id_token を拒否すること。"""
    private_key, _ = rsa_key_pair
    with pytest.raises(jwt.InvalidAudienceError):
        token.verify_id_token(
            _issue_id_token(private_key, aud="other-client"),
            jwks_uri="http://keycloak_c:8080/jwks",
            audience="fastapi-app",
            allowed_issuers=ALLOWED_ISSUERS,
            expected_nonce="expected-nonce",
        )


def test_verify_id_token_rejects_unknown_issuer(rsa_key_pair, patch_jwks):
    """許容していない issuer の id_token を拒否すること。"""
    private_key, _ = rsa_key_pair
    with pytest.raises(ValueError, match="Unexpected issuer"):
        token.verify_id_token(
            _issue_id_token(private_key, iss="http://evil.example.com/realms/master"),
            jwks_uri="http://keycloak_c:8080/jwks",
            audience="fastapi-app",
            allowed_issuers=ALLOWED_ISSUERS,
            expected_nonce="expected-nonce",
        )


def test_verify_id_token_rejects_nonce_mismatch(rsa_key_pair, patch_jwks):
    """nonce が一致しない id_token を拒否すること。"""
    private_key, _ = rsa_key_pair
    with pytest.raises(ValueError, match="Nonce mismatch"):
        token.verify_id_token(
            _issue_id_token(private_key, nonce="tampered"),
            jwks_uri="http://keycloak_c:8080/jwks",
            audience="fastapi-app",
            allowed_issuers=ALLOWED_ISSUERS,
            expected_nonce="expected-nonce",
        )


def test_verify_id_token_accepts_external_issuer(rsa_key_pair, patch_jwks):
    """内部 URL / 外部 URL のどちらの issuer でも受理すること。"""
    private_key, _ = rsa_key_pair
    claims = token.verify_id_token(
        _issue_id_token(private_key, iss="http://localhost:8080/keycloak/realms/master"),
        jwks_uri="http://keycloak_c:8080/jwks",
        audience="fastapi-app",
        allowed_issuers=ALLOWED_ISSUERS,
        expected_nonce="expected-nonce",
    )
    assert claims["sub"] == "user-1"


# ------------------------------------------------------------- 秘密鍵の検証


def test_validate_secrets_raises_in_production_with_defaults(monkeypatch):
    """本番環境で既定の秘密鍵のままなら起動を止めること。"""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("KC_CLIENT_SECRET_SEED", "change-me-client-secret-seed")
    monkeypatch.setenv("SESSION_SECRET_KEY", "change-me-session-secret")

    with pytest.raises(RuntimeError, match="既定値"):
        environment.KeyCloakEnvironmentVariables().validate_secrets()


def test_validate_secrets_passes_in_production_with_real_secrets(monkeypatch):
    """本番環境でも秘密鍵が設定済みなら通過すること。"""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("KC_CLIENT_SECRET_SEED", "real-client-secret-seed")
    monkeypatch.setenv("SESSION_SECRET_KEY", "real-session-secret")

    environment.KeyCloakEnvironmentVariables().validate_secrets()


def test_validate_secrets_only_warns_in_development(monkeypatch):
    """開発環境では既定値のままでも起動を妨げないこと。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("KC_CLIENT_SECRET_SEED", raising=False)
    monkeypatch.setenv("SESSION_SECRET_KEY", "change-me-session-secret")

    environment.KeyCloakEnvironmentVariables().validate_secrets()


def test_validate_secrets_raises_in_production_without_seed(monkeypatch):
    """本番環境でシークレット導出用のシードが未設定なら起動を止めること。"""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("KC_CLIENT_SECRET_SEED", raising=False)
    monkeypatch.setenv("SESSION_SECRET_KEY", "real-session-secret")

    with pytest.raises(RuntimeError, match="KC_CLIENT_SECRET_SEED"):
        environment.KeyCloakEnvironmentVariables().validate_secrets()


# ------------------------------------------------ トークンのライフサイクル


def test_build_token_record_converts_to_absolute_expiry():
    """expires_in が絶対時刻に変換されること。"""
    before = time.time()
    record = token.build_token_record(
        {"access_token": "a", "refresh_token": "r", "id_token": "i", "expires_in": 300, "refresh_expires_in": 1800}
    )
    assert record["access_token"] == "a"
    assert record["id_token"] == "i"
    assert before + 300 <= record["access_token_expires_at"] <= time.time() + 300
    assert before + 1800 <= record["refresh_token_expires_at"] <= time.time() + 1800


def test_is_access_token_expired_detects_expiry():
    """期限切れ・期限間近・有効を正しく判定すること。"""
    assert token.is_access_token_expired({"access_token_expires_at": time.time() - 1}) is True
    # 猶予(既定30秒)以内は更新対象とみなす
    assert token.is_access_token_expired({"access_token_expires_at": time.time() + 10}) is True
    assert token.is_access_token_expired({"access_token_expires_at": time.time() + 300}) is False


def test_is_access_token_expired_when_field_missing():
    """期限情報が無い場合は安全側に倒して更新対象とすること。"""
    assert token.is_access_token_expired({}) is True


def test_is_refresh_token_expired():
    """refresh token の期限判定。"""
    assert token.is_refresh_token_expired({"refresh_token_expires_at": time.time() - 1}) is True
    assert token.is_refresh_token_expired({"refresh_token_expires_at": time.time() + 60}) is False
    # 期限情報が無い場合は期限切れとみなさない(更新を試行させる)
    assert token.is_refresh_token_expired({}) is False


def test_refresh_access_token_returns_none_on_error(monkeypatch):
    """KeyCloak が 200 以外を返した場合は None を返すこと。"""

    class _Resp:
        status_code = 400

        def json(self):
            return {}

    monkeypatch.setattr(token.httpx, "post", lambda *a, **k: _Resp())
    assert token.refresh_access_token("http://kc/token", "cid", "secret", "rt") is None


def test_refresh_access_token_returns_none_on_network_error(monkeypatch):
    """通信エラー時も例外を送出せず None を返すこと。"""

    def _raise(*_a, **_k):
        raise token.httpx.ConnectError("boom")

    monkeypatch.setattr(token.httpx, "post", _raise)
    assert token.refresh_access_token("http://kc/token", "cid", "secret", "rt") is None


def test_refresh_access_token_normalizes_response(monkeypatch):
    """成功時は絶対時刻に正規化された記録を返すこと。"""

    class _Resp:
        status_code = 200

        def json(self):
            return {"access_token": "new-a", "refresh_token": "new-r", "expires_in": 300, "refresh_expires_in": 1800}

    monkeypatch.setattr(token.httpx, "post", lambda *a, **k: _Resp())
    record = token.refresh_access_token("http://kc/token", "cid", "secret", "rt")
    assert record["access_token"] == "new-a"
    assert record["refresh_token"] == "new-r"
    assert record["access_token_expires_at"] > time.time()
