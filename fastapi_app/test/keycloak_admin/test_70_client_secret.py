# -*- coding: utf-8 -*-
"""modules.keycloak_admin.client_secret(クライアントシークレットの導出。02 §3.3)のテスト。"""
import base64
import hashlib
import hmac
import logging

import pytest
import pytest_check as check

from modules.keycloak_admin.client_secret import (
    CLIENT_SECRET_SEED_ENV,
    INSECURE_DEFAULT_CLIENT_SECRET_SEED,
    client_secret_seed_from_env,
    derive_client_secret,
    is_insecure_client_secret_seed,
)

# 固定ベクトル: HMAC-SHA256(seed, "{realm}:{client_id}") を Base64URL(パディングなし)にした値。
# 実装とは別に ``openssl dgst -sha256 -hmac <seed>`` で求めた値(式が変わったら既存の払い出し済みクライアントのシークレットが無効になる)。
VECTORS = [
    ("seed-A", "tenant-alpha", "fastapi-app", "-thqvmZ32jtvbvSTflbpdOqnFcXBkDHqelHVzRgQmok"),
    ("seed-A", "tenant-alpha", "tenant-user-admin", "QoxrvM9Uy_HyIv6nD1D2Z5pdmDtv6sYUAbruKs9RID4"),
    ("seed-B", "tenant-alpha", "fastapi-app", "BmW9mvnFIhJnliOfZzoYwlNGflw64p7hVGhApC9eTPE"),
    ("test-seed", "control-plane", "fastapi-cp", "q7KWDhuiAGAuqz_YCR9AOs-oAmzLlw5-8EW4oShqlFc"),
]


class TestDerivation:
    """導出値。"""

    @pytest.mark.parametrize(("seed", "realm", "client_id", "expected"), VECTORS)
    def test_fixed_vectors(self, seed, realm, client_id, expected):
        """固定ベクトルと一致する(式・エンコードの変更を検知する)。"""
        check.equal(derive_client_secret(seed, realm, client_id), expected)

    def test_matches_documented_formula(self):
        """02 §3.3 の式(HMAC-SHA256 → Base64URL パディングなし)を別実装で計算した値と一致し、43 文字・URL セーフである。"""
        digest = hmac.new(b"some-seed", b"tenant-x:fastapi-app", hashlib.sha256).digest()
        expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        secret = derive_client_secret("some-seed", "tenant-x", "fastapi-app")
        check.equal(secret, expected)
        check.equal(len(secret), 43)
        check.is_true(all(c.isalnum() or c in "-_" for c in secret))

    def test_deterministic(self):
        """同じ入力なら何度呼んでも同じ値(保存せずに再導出できる)。"""
        check.equal(derive_client_secret("s", "r", "c"), derive_client_secret("s", "r", "c"))

    def test_each_input_changes_the_output(self):
        """シード・レルム・クライアント ID のどれが違っても別の値になる(テナント間・クライアント間で共有しない)。"""
        base = derive_client_secret("seed", "tenant-a", "client")
        others = [derive_client_secret("seed2", "tenant-a", "client"), derive_client_secret("seed", "tenant-b", "client"), derive_client_secret("seed", "tenant-a", "client2")]
        check.equal(len({base, *others}), 4)

    def test_separator_ambiguity_is_prevented(self):
        """('a:b','c') と ('a','b:c') のような区切り文字による衝突は、区切り文字を拒否して防ぐ。"""
        with pytest.raises(ValueError):
            derive_client_secret("seed", "a:b", "c")
        with pytest.raises(ValueError):
            derive_client_secret("seed", "a", "b:c")

    @pytest.mark.parametrize(("seed", "realm", "client_id"), [("", "r", "c"), ("s", "", "c"), ("s", "r", ""), ("", "", "")])
    def test_empty_arguments_are_rejected(self, seed, realm, client_id):
        """シード・レルム・クライアント ID が空なら ValueError。"""
        with pytest.raises(ValueError):
            derive_client_secret(seed, realm, client_id)

    def test_seed_is_not_in_the_error_message(self):
        """検証エラーのメッセージにシード値を含めない。"""
        with pytest.raises(ValueError) as exc_info:
            derive_client_secret("super-secret-seed", "a:b", "c")
        check.is_not_in("super-secret-seed", str(exc_info.value))


class TestInsecureSeed:
    """既定シードの扱い。"""

    @pytest.mark.parametrize(("seed", "expected"), [(None, True), ("", True), (INSECURE_DEFAULT_CLIENT_SECRET_SEED, True), ("real-seed", False), (" ", False)])
    def test_is_insecure(self, seed, expected):
        """未設定・空・開発用の既定値だけが『安全でない』と判定される。"""
        check.equal(is_insecure_client_secret_seed(seed), expected)

    def test_seed_from_env_returns_configured_value(self, monkeypatch):
        """設定済みのシードはそのまま返す(APP_ENV に関わらず)。"""
        monkeypatch.setenv(CLIENT_SECRET_SEED_ENV, "configured-seed")
        monkeypatch.setenv("APP_ENV", "production")
        check.equal(client_secret_seed_from_env(), "configured-seed")

    @pytest.mark.parametrize("value", [None, "", INSECURE_DEFAULT_CLIENT_SECRET_SEED])
    def test_development_falls_back_with_warning(self, monkeypatch, caplog, value):
        """開発環境では、未設定・既定値のシードに警告を出して既定値を使う。"""
        if value is None:
            monkeypatch.delenv(CLIENT_SECRET_SEED_ENV, raising=False)
        else:
            monkeypatch.setenv(CLIENT_SECRET_SEED_ENV, value)
        monkeypatch.setenv("APP_ENV", "development")
        with caplog.at_level(logging.WARNING):
            check.equal(client_secret_seed_from_env(), INSECURE_DEFAULT_CLIENT_SECRET_SEED)
        check.is_in(CLIENT_SECRET_SEED_ENV, caplog.text)

    @pytest.mark.parametrize("app_env", ["production", "staging", "Production", ""])
    @pytest.mark.parametrize("value", [None, "", INSECURE_DEFAULT_CLIENT_SECRET_SEED])
    def test_non_development_refuses_default_seed(self, monkeypatch, app_env, value):
        """開発環境以外では、未設定・既定値のシードをエラーにする(全テナントのシークレットが推測できてしまうため)。"""
        if value is None:
            monkeypatch.delenv(CLIENT_SECRET_SEED_ENV, raising=False)
        else:
            monkeypatch.setenv(CLIENT_SECRET_SEED_ENV, value)
        monkeypatch.setenv("APP_ENV", app_env)
        with pytest.raises(RuntimeError, match=CLIENT_SECRET_SEED_ENV):
            client_secret_seed_from_env()
