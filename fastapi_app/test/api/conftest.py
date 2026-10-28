# -*- coding: utf-8 -*-
"""API(``app.py`` の ``app``)のテスト用フィクスチャ。

- Redis はインメモリの代替(``FakeRedis``)。セッション・レート制限・ヘルスチェックのすべてに使う。
- 認証は Cookie を作るヘルパー(``login_ap`` / ``login_cp``)で行う。実際の依存関数(署名の検証・Redis のセッション・ロール確認)を通す。
- DB は開発 DB の ``control_plane_db``(作った行は後片付けする。alpha / beta は変更しない)。
  テナントレジストリはキャッシュ無しの実装(``SqlTenantRegistry``)に差し替え、状態の変更が即座に AP に反映されるようにする。
- Keycloak は ``FakeKc``(templates の関数の差し替え)。払い出しサービスは ``get_provisioning_service`` を差し替えて作る。

``control_plane/conftest.py`` の ``cp_db`` / ``fake_kc`` / ``fake_app_data`` と一時パスワード ``SENTINEL_PASSWORD`` を共用する。
"""
import datetime as dt
import time
import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Annotated, Any

import pytest
from control_plane.conftest import SENTINEL_PASSWORD, CpDb, FakeAdmin, cp_db, cp_owner_engine, cp_runtime_engine, fake_app_data, fake_kc  # noqa: F401
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import app
from control_plane_app.api_tenants.deps import get_provisioning_service
from control_plane_app.services.tenant_provisioning import TenantProvisioningService
from main_app.route.public.api_health import router as health_router
from main_app.route.public.redis_client import get_public_redis
from main_app.route.v1.deps import ActiveAppUser, require_active_app_user
from modules.auth import csrf, dependency, session
from modules.auth.dependency import get_current_app_user
from modules.auth.environment import KeyCloakEnvironmentVariables
from modules.auth.plane import Plane
from modules.tenancy import providers
from modules.tenancy.providers import CpSessionDep, get_tenant_registry
from modules.tenancy.registry import SqlTenantRegistry

from .fake_redis import FakeRedis

FRONTEND_ORIGIN = "http://localhost:5173"
CSRF_HEADERS = {"X-Requested-With": "rf-stack", "Origin": FRONTEND_ORIGIN}
ADMIN_SUB = "cp-admin-sub-0001"
VIEWER_SUB = "cp-viewer-sub-0002"


@pytest.fixture(autouse=True)
def _api_env(monkeypatch) -> None:
    """認証・レート制限の環境変数を固定し、モジュールのグローバルな設定を差し替える。"""
    for name in ("CSRF_TRUSTED_ORIGINS", "KEYCLOAK_CLIENT_ID", "KEYCLOAK_CP_CLIENT_ID", "SESSION_TTL_SECONDS", "PUBLIC_TENANT_LOOKUP_RATE_WINDOW_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("FRONTEND_URL", FRONTEND_ORIGIN)
    monkeypatch.setenv("SESSION_SECRET_KEY", "api-test-session-secret")
    monkeypatch.setenv("KC_CLIENT_SECRET_SEED", "api-test-seed")
    monkeypatch.setenv("PUBLIC_TENANT_LOOKUP_RATE_LIMIT", "100000")  # 通常のテストが制限に掛からないようにする(制限のテストは個別に設定)
    config = KeyCloakEnvironmentVariables()
    monkeypatch.setattr(csrf, "_config", config)
    monkeypatch.setattr(dependency, "_config", config)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch) -> FakeRedis:
    """セッション・レート制限・ヘルスチェックの Redis をインメモリの代替にする。"""
    redis = FakeRedis()
    monkeypatch.setattr(session, "_redis_client", lambda: redis)
    monkeypatch.setattr(health_router, "get_public_redis", lambda: redis)
    app.dependency_overrides[get_public_redis] = lambda: redis
    return redis


@pytest.fixture(autouse=True)
def live_registry(cp_runtime_engine) -> Iterator[SqlTenantRegistry]:  # noqa: F811
    """キャッシュ無しのテナントレジストリ(cp_registry_reader)に差し替える。後始末でエンジンも破棄する。"""
    registry = SqlTenantRegistry(providers.get_cp_registry_reader_engine())
    app.dependency_overrides[get_tenant_registry] = lambda: registry
    yield registry
    app.dependency_overrides.clear()
    providers.dispose_providers()


def ap_user_id(sub: str) -> uuid.UUID:
    """セッションの ``sub`` に対応する、テスト用の AP のユーザー ID(``t_user.id`` の代わり。決定的に作る)。"""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"rf-stack-test-user:{sub}")


@pytest.fixture(autouse=True)
def active_app_user(live_registry) -> None:  # noqa: F811
    """AP の「セッションのユーザーが有効か」(``require_active_app_user``。DB の ``t_user`` を引く)を、認証済みなら通すフェイクに差し替える。

    シードのテナントにはセッションの ``sub`` に対応するユーザー行が無いため。認証(``get_current_app_user``)は実物のまま通す。
    有効/無効の判定そのものは、このフィクスチャを使わずに本物の依存関数を通すテスト(``test_80_ap_users.py`` 等)で確認する。
    """

    def fake(user: Annotated[dict[str, Any], Depends(get_current_app_user)]) -> ActiveAppUser:
        return ActiveAppUser(id=ap_user_id(user["sub"]), subject=user["sub"], claims=user)

    app.dependency_overrides[require_active_app_user] = fake


@pytest.fixture(autouse=True)
def provisioning_service(fake_kc, fake_app_data) -> None:  # noqa: F811
    """払い出しサービスをフェイクの Keycloak・固定の一時パスワードで組み立てる(``get_provisioning_service`` の差し替え)。"""

    def build(cp_session: CpSessionDep) -> Iterator[TenantProvisioningService]:
        yield TenantProvisioningService(cp_session, FakeAdmin(), app_data=fake_app_data, password_generator=lambda: SENTINEL_PASSWORD)

    app.dependency_overrides[get_provisioning_service] = build


@pytest.fixture
def client() -> TestClient:
    """アプリの TestClient(サーバー内の例外は 500 の応答として受け取る。リダイレクトは追わない)。"""
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


# ---------------------------------------------------------------------------
# 認証(Cookie)
# ---------------------------------------------------------------------------
def make_tokens() -> dict[str, Any]:
    now = time.time()
    return {"access_token": "a", "refresh_token": "r", "id_token": "i", "access_token_expires_at": now + 3600, "refresh_token_expires_at": now + 7200}


def cookie_header(**cookies: str) -> dict[str, str]:
    """リクエストヘッダーとして Cookie を渡す(TestClient の per-request cookies は非推奨のため)。"""
    return {"Cookie": "; ".join(f"{name}={value}" for name, value in cookies.items())}


@pytest.fixture
def login_ap() -> Callable[..., dict[str, str]]:
    """AP のセッションを作り、Cookie ヘッダーを返す。``tenant_id`` を省略すればレジストリ上の ID を使う想定で呼び出し側が渡す。"""

    def create(tenant_code: str, tenant_id: uuid.UUID, roles: list[str] | None = None, *, claim_tenant_id: uuid.UUID | None = None, sub: str | None = None) -> dict[str, str]:
        realm = f"tenant-{tenant_code}"
        sub = sub or f"{tenant_code}-user-sub"
        claim = str(claim_tenant_id or tenant_id)
        user = {"sub": sub, "preferred_username": f"{tenant_code}-member", "email": f"{tenant_code}-member@example.com", "realm": realm, "plane": "app", "roles": roles if roles is not None else ["member"], "tenant_id": claim}
        data = {"plane": "app", "realm": realm, "tenant_id": claim, "tenant_code": tenant_code, "tokens": make_tokens(), "user": user}
        session_id = session.create_session(Plane.APP, data)
        return cookie_header(rf_sid_app=session.sign_session_id(Plane.APP, session_id))

    return create


@pytest.fixture
def login_cp() -> Callable[..., dict[str, str]]:
    """CP のセッションを作り、Cookie ヘッダーを返す(既定は ``saas_admin``)。"""

    def create(roles: list[str] | None = None, *, sub: str = ADMIN_SUB) -> dict[str, str]:
        user = {"sub": sub, "preferred_username": "cp-user", "email": "cp-user@example.com", "realm": "control-plane", "plane": "cp", "roles": roles if roles is not None else ["saas_admin"]}
        data = {"plane": "cp", "realm": "control-plane", "tokens": make_tokens(), "user": user}
        session_id = session.create_session(Plane.CP, data)
        return cookie_header(rf_sid_cp=session.sign_session_id(Plane.CP, session_id))

    return create


@pytest.fixture
def admin(login_cp) -> dict[str, str]:
    """``saas_admin`` の Cookie。"""
    return login_cp(["saas_admin"], sub=ADMIN_SUB)


@pytest.fixture
def viewer(login_cp) -> dict[str, str]:
    """``saas_viewer`` の Cookie。"""
    return login_cp(["saas_viewer"], sub=VIEWER_SUB)


def with_csrf(headers: dict[str, str], **extra: str) -> dict[str, str]:
    """Cookie などのヘッダーに CSRF 対策のヘッダー(許可オリジン)を足す。"""
    return {**headers, **CSRF_HEADERS, **extra}


# ---------------------------------------------------------------------------
# 既存テナント・使い捨てテナント
# ---------------------------------------------------------------------------
@pytest.fixture
def seeded(live_registry) -> Callable[[str], Any]:
    """シードのテナント(alpha / beta)のレジストリ上のレコードを返す関数。無ければ skip する。読み取り専用(変更しない)。"""

    def get(code: str) -> Any:
        record = live_registry.get_by_code(code)
        if record is None:
            pytest.skip(f"開発 DB にシードのテナント {code} が無いためスキップ")
        return record

    return get


@pytest.fixture
def make_tenant(client, cp_db, admin) -> Callable[..., dict[str, Any]]:  # noqa: F811
    """API(POST /api/v1/cp/tenants)で使い捨てのテナントを払い出し、レスポンスの本文を返す。後始末は ``cp_db`` が行う。"""

    def create(**overrides: Any) -> dict[str, Any]:
        code = overrides.pop("tenant_code", None) or cp_db.new_code()
        body = {"tenant_code": code, "name": "Api Test Tenant", "initial_admin": {"email": f"admin@{code}.example.com"}}
        body.update(overrides)
        response = client.post("/api/v1/cp/tenants", json=body, headers=with_csrf(admin))
        assert response.status_code == 201, response.text
        payload = response.json()
        cp_db.tenant_ids.append(uuid.UUID(payload["tenant"]["id"]))
        return payload

    return create


def insert_metric(db: CpDb, tenant_id: uuid.UUID, date: dt.date, key: str, value: int | Decimal) -> None:
    """日次メトリクスを 1 行入れる(後片付けは ``cp_db`` フィクスチャ)。"""
    with db.runtime.begin() as connection:
        connection.execute(text("INSERT INTO t_tenant_daily_metric (tenant_id, date, metric_key, value) VALUES (:t, :d, :k, :v)"), {"t": tenant_id, "d": date, "k": key, "v": value})
