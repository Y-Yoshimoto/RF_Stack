#!/usr/bin/env python
# coding:utf-8
"""開発用ログインバイパスのユニットテスト。

KeyCloak への通信を伴う部分は対象外とし、有効/無効の判定と
入力検証（プロファイル・遷移先）を検証する。
"""
import pytest

from main_app.route.auth import dev_login
from modules.auth.environment import KeyCloakEnvironmentVariables

# ------------------------------------------------ 有効/無効の判定


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", "on"])
def test_dev_login_enabled_in_development(monkeypatch, value):
    """development かつ明示的に有効化された場合のみ有効になること。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", value)

    assert KeyCloakEnvironmentVariables().is_dev_login_enabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no"])
def test_dev_login_disabled_without_opt_in(monkeypatch, value):
    """明示的に有効化しない限り無効であること。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", value)

    assert KeyCloakEnvironmentVariables().is_dev_login_enabled() is False


def test_dev_login_disabled_in_production(monkeypatch):
    """本番環境では有効化を要求されても無効であること。"""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", "true")

    assert KeyCloakEnvironmentVariables().is_dev_login_enabled() is False


def test_validate_dev_login_raises_in_production(monkeypatch):
    """本番環境で有効化を要求された場合は起動を止めること。"""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", "true")

    with pytest.raises(RuntimeError, match="AUTH_DEV_LOGIN_ENABLED"):
        KeyCloakEnvironmentVariables().validate_dev_login()


def test_validate_dev_login_passes_in_development(monkeypatch):
    """開発環境では有効化されていても起動を妨げないこと。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", "true")

    KeyCloakEnvironmentVariables().validate_dev_login()


# ------------------------------------------------------ 遷移先の検証


@pytest.mark.parametrize("path", ["/button", "/fetch", "/", "/a/b?c=d"])
def test_validate_next_path_accepts_paths(path):
    """同一オリジン内のパスは許可されること。"""
    assert dev_login._validate_next_path(path) == path


@pytest.mark.parametrize(
    "path",
    ["https://evil.example.com", "//evil.example.com", "http://localhost:5173/button", "button", ""],
)
def test_validate_next_path_rejects_external(path):
    """絶対 URL / プロトコル相対 URL は拒否すること(オープンリダイレクト防止)。"""
    if path == "":
        # 空文字は既定値にフォールバックする
        assert dev_login._validate_next_path(path) == dev_login.DEFAULT_NEXT_PATH
        return
    with pytest.raises(ValueError):
        dev_login._validate_next_path(path)


# -------------------------------------------------------- プロファイル


def test_default_profile_exists():
    """既定プロファイルが定義されていること。"""
    assert "default" in dev_login.DEV_LOGIN_PROFILES
    profile = dev_login.DEV_LOGIN_PROFILES["default"]
    assert {"realm", "username", "password"} <= set(profile)
