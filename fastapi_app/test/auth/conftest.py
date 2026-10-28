# -*- coding: utf-8 -*-
"""modules.auth(プレーン別セッション・CSRF・ロール・ログイン)のテスト用フィクスチャ。

実 Redis・実 Keycloak には接続しない。

- ``fake_redis``: ``modules.auth.session`` が使う Redis クライアントのインメモリ代替(autouse)
- ``_auth_env``: 認証関連の環境変数をテスト用の固定値にする(autouse。コンテナの実環境値に依存しない)
- ``config``: 上の環境変数から作った ``KeyCloakEnvironmentVariables``。モジュール内のグローバルな ``_config`` も差し替える
- ``login_session_for``: 署名済み Cookie 値とセッションを作る補助
"""
import time
from collections.abc import Callable
from typing import Any

import pytest

from modules.auth import csrf, dependency, session
from modules.auth.environment import KeyCloakEnvironmentVariables
from modules.auth.plane import Plane

SESSION_SECRET = "test-session-secret-not-a-real-key"
SEED = "test-client-secret-seed"


class FakePipeline:
    """``Redis.pipeline()`` の GET + DELETE だけを実装した代替。"""

    def __init__(self, redis: "FakeRedis") -> None:
        self._redis = redis
        self._ops: list[tuple[str, str]] = []

    def get(self, key: str) -> "FakePipeline":
        self._ops.append(("get", key))
        return self

    def delete(self, key: str) -> "FakePipeline":
        self._ops.append(("delete", key))
        return self

    def execute(self) -> list[Any]:
        results: list[Any] = []
        for op, key in self._ops:
            results.append(self._redis.get(key) if op == "get" else self._redis.delete(key))
        return results


class FakeRedis:
    """``modules.auth.session`` が使うコマンドだけを実装したインメモリの Redis 代替(TTL は値として保持する)。"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def setex(self, key: str, ttl: int, value: str) -> bool:
        self.data[key] = value
        self.ttls[key] = int(ttl)
        return True

    def set(self, key: str, value: str) -> bool:
        self.data[key] = value
        self.ttls[key] = -1
        return True

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def getdel(self, key: str) -> str | None:
        self.ttls.pop(key, None)
        return self.data.pop(key, None)

    def delete(self, key: str) -> int:
        self.ttls.pop(key, None)
        return 1 if self.data.pop(key, None) is not None else 0

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2) if key in self.data else -2

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    def keys(self) -> list[str]:
        return sorted(self.data)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch) -> FakeRedis:
    """session モジュールの Redis クライアントをインメモリの代替に差し替える。"""
    redis = FakeRedis()
    monkeypatch.setattr(session, "_redis_client", lambda: redis)
    return redis


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch) -> None:
    """認証関連の環境変数をテスト用の固定値にする(実環境の値・秘密鍵に依存しない)。"""
    for name in ("KEYCLOAK_CLIENT_ID", "KEYCLOAK_CP_CLIENT_ID", "APP_CALLBACK_URL", "CSRF_TRUSTED_ORIGINS", "AUTH_DEV_LOGIN_ENABLED", "SESSION_TTL_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("KEYCLOAK_URL", "http://keycloak.test:8080")
    monkeypatch.setenv("KEYCLOAK_EXTERNAL_URL", "http://localhost:8080")
    monkeypatch.setenv("KEYCLOAK_HTTP_RELATIVE_PATH", "keycloak")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")
    monkeypatch.setenv("SESSION_SECRET_KEY", SESSION_SECRET)
    monkeypatch.setenv("KC_CLIENT_SECRET_SEED", SEED)


@pytest.fixture
def config(monkeypatch, _auth_env) -> KeyCloakEnvironmentVariables:
    """テスト用の環境変数から作った設定。csrf / dependency モジュールのグローバルな設定もこれに差し替える。"""
    cfg = KeyCloakEnvironmentVariables()
    monkeypatch.setattr(csrf, "_config", cfg)
    monkeypatch.setattr(dependency, "_config", cfg)
    return cfg


def make_tokens(*, access_ttl: float = 3600, refresh_ttl: float = 7200) -> dict[str, Any]:
    """セッションに保存するトークン記録(絶対時刻)を作る。"""
    now = time.time()
    return {
        "access_token": "access-token-value",
        "refresh_token": "refresh-token-value",
        "id_token": "id-token-value",
        "access_token_expires_at": now + access_ttl,
        "refresh_token_expires_at": now + refresh_ttl,
    }


def make_session_data(plane: Plane, *, roles: list[str], realm: str | None = None, tokens: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """プレーンのセッションデータを作る(``modules.auth.login.build_login_session`` の戻り値と同じ形)。"""
    realm = realm or ("control-plane" if plane == Plane.CP else "tenant-alpha")
    user = {"sub": "user-sub-1", "preferred_username": "tester", "email": "tester@example.com", "realm": realm, "plane": plane.value, "roles": roles}
    data: dict[str, Any] = {"plane": plane.value, "realm": realm, "tokens": tokens or make_tokens(), "user": user}
    if plane == Plane.APP:
        data["tenant_code"] = "alpha"
        data["tenant_id"] = user["tenant_id"] = "11111111-1111-7111-8111-111111111111"
    data.update(extra)
    return data


@pytest.fixture
def login_as(config) -> Callable[..., tuple[str, str]]:
    """プレーンのセッションを Redis に作り、``(署名済み Cookie 値, セッション ID)`` を返すファクトリ。"""

    def create(plane: Plane, roles: list[str], **kwargs: Any) -> tuple[str, str]:
        session_id = session.create_session(plane, make_session_data(plane, roles=roles, **kwargs))
        return session.sign_session_id(plane, session_id), session_id

    return create
