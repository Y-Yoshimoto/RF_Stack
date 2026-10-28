# -*- coding: utf-8 -*-
"""AP のログイン完了(GET /api/auth/callback)のユーザー同期を、実際の DB まで通して確認するテスト。

``test/auth`` のテストは同期処理を差し替えて、呼び出しの順序と失敗時のリダイレクトを確認している。ここでは同期処理を差し替えず、
使い捨てのテナント(ランダムな UUID。レジストリはフェイク)の ``app_db`` に、ユーザー行・デフォルト組織が実際に作られること、
無効化されたユーザーにはセッションが作られないことを確認する。Keycloak へのトークン交換・検証だけを差し替える。alpha / beta には触れない。
"""
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_check as check
from auth.conftest import _auth_env, config, fake_redis  # noqa: F401
from fastapi import FastAPI
from fastapi.testclient import TestClient

from main_app.route.auth import apiapp
from modules.auth.plane import Plane
from modules.tenancy import providers
from modules.tenancy.providers import get_tenant_registry
from modules.tenancy.registry import TenantRecord

FRONTEND = "http://localhost:5173"


class SingleTenantRegistry:
    """1 つのテナントだけを返すレジストリ(``cp_registry_reader`` を使わない)。"""

    def __init__(self, record: TenantRecord) -> None:
        self.record = record

    def get_by_code(self, tenant_code):
        return self.record if tenant_code == self.record.tenant_code else None

    def get_by_realm(self, realm_name):
        return self.record if realm_name == self.record.realm_name else None

    def get_by_id(self, tenant_id):
        return self.record if tenant_id == self.record.tenant_id else None


class FakeTokenResponse:
    status_code = 200

    def json(self):
        return {"access_token": "a", "refresh_token": "r", "id_token": "i"}


@pytest.fixture(autouse=True)
def _dispose_providers():
    yield
    providers.dispose_providers()


@pytest.fixture
def login_flow(ap_db, config, monkeypatch, fake_redis):  # noqa: F811
    """使い捨てのテナントに対する AP のログインを実行するファクトリ。``flow(sub, email=..., name=..., claim_tenant_id=...)`` が (response, tenant) を返す。"""
    ctx = ap_db.tenant()
    record = TenantRecord(tenant_id=ctx.tenant_id, tenant_code=ctx.tenant_code, realm_name=f"tenant-{ctx.tenant_code}", status="ACTIVE")
    app = FastAPI()
    app.include_router(apiapp.router, prefix="/api/auth")
    app.dependency_overrides[get_tenant_registry] = lambda: SingleTenantRegistry(record)
    monkeypatch.setattr(apiapp, "_config", config)
    monkeypatch.setattr(apiapp.httpx, "post", lambda *a, **k: FakeTokenResponse())
    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    claims: dict = {}

    def fake_build(config_, plane, realm, token_data, *, expected_nonce, tenant_code=None, expected_tenant_id=None):
        user = {"sub": claims["sub"], "preferred_username": "taro", "email": claims.get("email"), "name": claims.get("name"), "plane": "app", "roles": ["member"], "realm": realm}
        if claims.get("claim_tenant_id"):
            user["tenant_id"] = claims["claim_tenant_id"]
        return {"plane": plane.value, "realm": realm, "tenant_code": tenant_code, "tokens": {"id_token": "i"}, "user": {k: v for k, v in user.items() if v is not None}}

    monkeypatch.setattr(apiapp, "build_login_session", fake_build)

    def flow(sub, *, email="taro@example.com", name="Taro Yamada", claim_tenant_id=None):
        claims.update(sub=sub, email=email, name=name, claim_tenant_id=claim_tenant_id)
        started = client.get("/api/auth/app/login", params={"tenant_code": ctx.tenant_code})
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        return client.get("/api/auth/callback", params={"state": state, "code": "c"})

    flow.ctx = ctx
    return flow


def app_sessions(redis) -> list[str]:
    return [key for key in redis.keys() if key.startswith(f"session:{Plane.APP.value}:")]


def test_first_login_creates_user_and_default_organization_then_session(login_flow, ap_db, fake_redis):  # noqa: F811
    """初回ログインのコールバックで、ユーザー行とデフォルト組織が実際に作られ、その後にセッションが作られてテナントのホームへ 302 する。"""
    sub = str(uuid.uuid4())
    response = login_flow(sub)
    check.equal((response.status_code, response.headers["location"]), (302, f"{FRONTEND}/{login_flow.ctx.tenant_code}/"))
    check.is_in("rf_sid_app=", response.headers["set-cookie"])
    check.equal(len(app_sessions(fake_redis)), 1)
    users = ap_db.users(login_flow.ctx)
    check.equal([(u["idp_subject"], u["email"], u["display_name"], u["version"]) for u in users], [(sub, "taro@example.com", "Taro Yamada", 1)])
    check.is_not_none(users[0]["last_login_at"])
    check.equal(len(ap_db.orgs(login_flow.ctx)), 1)


def test_second_login_updates_last_login_only(login_flow, ap_db):
    """同じユーザーの 2 回目のログインは last_login_at だけが進み、version は上がらず、組織も増えない。"""
    sub = str(uuid.uuid4())
    login_flow(sub)
    first = ap_db.users(login_flow.ctx)[0]
    login_flow(sub)
    second = ap_db.users(login_flow.ctx)[0]
    check.equal((second["id"], second["version"]), (first["id"], 1))
    check.greater(second["last_login_at"], first["last_login_at"])
    check.equal(len(ap_db.orgs(login_flow.ctx)), 1)


def test_deactivated_user_is_rejected_without_session(login_flow, ap_db, fake_redis):  # noqa: F811
    """無効化されたユーザーのコールバックは login_rejected でログイン画面へ戻り、セッションを作らない。行は変わらない。"""
    sub = str(uuid.uuid4())
    user = ap_db.add_user(login_flow.ctx, sub=sub, email="old@example.com", display_name="Old", is_active=False)
    response = login_flow(sub)
    check.equal((response.status_code, response.headers["location"]), (302, f"{FRONTEND}/{login_flow.ctx.tenant_code}/login?error=login_rejected"))
    check.is_not_in("rf_sid_app", response.headers.get("set-cookie", ""))
    check.equal(app_sessions(fake_redis), [])
    row = ap_db.user(login_flow.ctx, user.id)
    check.equal((row["email"], row["display_name"], row["version"], row["last_login_at"]), ("old@example.com", "Old", 1, None))
    check.equal(ap_db.orgs(login_flow.ctx), [])


def test_tenant_claim_in_token_does_not_choose_the_tenant(login_flow, ap_db):
    """トークンのユーザー情報に別テナントの tenant_id があっても、同期先はレジストリで確認したテナントだけ。別テナントには何も作られない。"""
    other = ap_db.tenant()
    login_flow(str(uuid.uuid4()), claim_tenant_id=str(other.tenant_id))
    check.equal(len(ap_db.users(login_flow.ctx)), 1)
    check.equal((ap_db.users(other), ap_db.orgs(other)), ([], []))
