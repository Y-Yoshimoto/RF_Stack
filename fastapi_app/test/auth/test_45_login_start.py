# -*- coding: utf-8 -*-
"""ログイン開始(GET /api/auth/app/login・/cp/login)とコールバックの入口のテスト。

``main_app.route.auth.apiapp`` のルーターだけをマウントした最小のアプリで確認する(app.py は使わない)。
Redis はインメモリの代替、テナントレジストリは ``dependency_overrides[get_tenant_registry]`` で差し替える。
"""
import json
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_check as check
from fastapi import FastAPI
from fastapi.testclient import TestClient

from main_app.route.auth import apiapp
from modules.auth import session
from modules.auth.login import LOGIN_REJECTED_DETAIL
from modules.auth.plane import Plane
from modules.tenancy.providers import get_tenant_registry
from modules.tenancy.registry import TenantRecord, TenantStatus

ALPHA = TenantRecord(tenant_id=uuid.UUID("0194e6a0-0000-7000-8000-00000000a1fa"), tenant_code="alpha", realm_name="tenant-alpha", status="ACTIVE")
UNAVAILABLE_LOCATION = "http://localhost:5173/login?error=tenant_unavailable"


class MutableRegistry:
    """code / realm で引くレジストリ。テスト中にレコードを差し替えられる。"""

    def __init__(self, *records: TenantRecord) -> None:
        self.records = list(records)

    def get_by_code(self, tenant_code: str) -> TenantRecord | None:
        return next((r for r in self.records if r.tenant_code == tenant_code), None)

    def get_by_realm(self, realm_name: str) -> TenantRecord | None:
        return next((r for r in self.records if r.realm_name == realm_name), None)

    def get_by_id(self, tenant_id: uuid.UUID) -> TenantRecord | None:
        return next((r for r in self.records if r.tenant_id == tenant_id), None)


@pytest.fixture
def registry() -> MutableRegistry:
    return MutableRegistry(ALPHA)


@pytest.fixture
def client(config, registry, monkeypatch) -> TestClient:
    """apiapp のルーターを /api/auth にマウントしたアプリ(リダイレクトは追わない)。"""
    monkeypatch.setattr(apiapp, "_config", config)
    app = FastAPI()
    app.include_router(apiapp.router, prefix="/api/auth")
    app.dependency_overrides[get_tenant_registry] = lambda: registry
    return TestClient(app, follow_redirects=False)


def _query(response) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(response.headers["location"]).query).items()}


class TestAppLoginStart:
    """AP のログイン開始。"""

    def test_active_tenant_redirects_to_keycloak_with_pkce(self, client, fake_redis):
        """ACTIVE なテナントは、そのレルムの Keycloak 認可画面へ 302 する(PKCE S256・state・nonce 付き)。"""
        response = client.get("/api/auth/app/login", params={"tenant_code": "alpha"})
        check.equal(response.status_code, 302)
        parts = urlsplit(response.headers["location"])
        check.equal(f"{parts.scheme}://{parts.netloc}{parts.path}", "http://localhost:8080/keycloak/realms/tenant-alpha/protocol/openid-connect/auth")
        query = _query(response)
        check.equal(query["client_id"], "fastapi-app")
        check.equal(query["response_type"], "code")
        check.equal(query["code_challenge_method"], "S256")
        check.is_in("code_challenge", query)

    def test_state_is_stored_server_side_without_exposing_verifier(self, client, fake_redis):
        """state と一緒に plane・レルム・tenant_code・code_verifier・nonce を Redis に保存し、code_verifier は URL に出さない。"""
        response = client.get("/api/auth/app/login", params={"tenant_code": "alpha"})
        query = _query(response)
        payload = json.loads(fake_redis.data[f"auth_state:{query['state']}"])
        check.equal((payload["plane"], payload["realm"], payload["tenant_code"]), ("app", "tenant-alpha", "alpha"))
        check.equal(payload["nonce"], query["nonce"])
        check.is_not_in(payload["code_verifier"], response.headers["location"])

    @pytest.mark.parametrize("raw", ["ALPHA", " alpha ", "Alpha", "alpha\n"])
    def test_tenant_code_is_normalized(self, client, raw):
        """大文字・前後の空白(改行を含む)は正規化してからレジストリを引く。"""
        response = client.get("/api/auth/app/login", params={"tenant_code": raw})
        check.equal(response.status_code, 302)
        check.is_in("/realms/tenant-alpha/", response.headers["location"])

    def test_client_cannot_choose_the_realm(self, client):
        """レルム名を指すパラメータを付けても無視され、レジストリ上のレルムが使われる。"""
        response = client.get("/api/auth/app/login", params={"tenant_code": "alpha", "realm": "master", "realm_name": "control-plane"})
        check.is_in("/realms/tenant-alpha/", response.headers["location"])

    def _unavailable_params(self):
        statuses = [s.value for s in TenantStatus if s is not TenantStatus.ACTIVE] + ["UNKNOWN_STATUS"]
        records = [TenantRecord(tenant_id=uuid.uuid4(), tenant_code=f"t-{index}", realm_name=f"tenant-t-{index}", status=status) for index, status in enumerate(statuses)]
        return statuses, records

    def test_unavailable_tenants_are_indistinguishable(self, client, registry, fake_redis):
        """形式不正・未登録・予約語・ACTIVE 以外の全状態は、ステータス・遷移先・本文が完全に同一(存在や状態を明かさない)で、state も保存しない。"""
        statuses, records = self._unavailable_params()
        registry.records.extend(records)
        cases = {
            "(未指定)": {},
            "(空)": {"tenant_code": ""},
            "短すぎる": {"tenant_code": "ab"},
            "不正な文字": {"tenant_code": "a_b!"},
            "ハイフン連続": {"tenant_code": "a--b"},
            "未登録": {"tenant_code": "ghost"},
            "予約語": {"tenant_code": "admin"},
        }
        for status, record in zip(statuses, records, strict=True):
            cases[f"状態 {status}"] = {"tenant_code": record.tenant_code}
        results = {}
        for label, params in cases.items():
            response = client.get("/api/auth/app/login", params=params)
            results[label] = (response.status_code, response.headers["location"], response.text)
        expected = (302, UNAVAILABLE_LOCATION, "")
        for label, result in results.items():
            check.equal(result, expected, label)
        check.equal(fake_redis.keys(), [], "認可リクエストの state を作らない")

    def test_registry_with_invalid_realm_name_is_unavailable(self, client, registry, fake_redis):
        """レジストリ上のレルム名が不正な形式でも、同じ「利用不可」の応答にする(URL へ連結しない)。"""
        registry.records.append(TenantRecord(tenant_id=uuid.uuid4(), tenant_code="evil", realm_name="../master", status="ACTIVE"))
        response = client.get("/api/auth/app/login", params={"tenant_code": "evil"})
        check.equal((response.status_code, response.headers["location"]), (302, UNAVAILABLE_LOCATION))
        check.equal(fake_redis.keys(), [])


class TestCpLoginStart:
    """CP のログイン開始。"""

    def test_redirects_to_control_plane_realm_with_cp_client(self, client, fake_redis):
        """CP は control-plane レルム固定・CP のクライアント ID で認可画面へ 302 する。tenant_code は受け取らない。"""
        response = client.get("/api/auth/cp/login", params={"tenant_code": "alpha", "realm": "tenant-alpha"})
        check.equal(response.status_code, 302)
        check.is_in("/realms/control-plane/protocol/openid-connect/auth", response.headers["location"])
        query = _query(response)
        check.equal(query["client_id"], "fastapi-cp")
        payload = json.loads(fake_redis.data[f"auth_state:{query['state']}"])
        check.equal((payload["plane"], payload["realm"]), ("cp", "control-plane"))
        check.is_not_in("tenant_code", payload)


class TestCallbackEntry:
    """コールバックの入口(トークン交換の前に拒否されるケース)。Keycloak へは通信しない。"""

    @pytest.fixture(autouse=True)
    def _no_network(self, monkeypatch):
        monkeypatch.setattr(apiapp.httpx, "post", lambda *a, **k: pytest.fail("トークン交換へ進んではならない"))

    @pytest.mark.parametrize("params", [{}, {"state": ""}, {"state": "unknown", "code": "c"}])
    def test_unknown_state_is_400(self, client, params):
        """state が無い・未知のコールバックは 400(Invalid state)。"""
        response = client.get("/api/auth/callback", params=params)
        check.equal((response.status_code, response.json()), (400, {"detail": "Invalid state"}))

    def test_state_is_single_use(self, client, fake_redis):
        """同じ state での 2 回目のコールバックは 400(リプレイ不可)。1 回目も認可コードが無ければ 400 で state を消費する。"""
        state = _query(client.get("/api/auth/app/login", params={"tenant_code": "alpha"}))["state"]
        first = client.get("/api/auth/callback", params={"state": state})
        second = client.get("/api/auth/callback", params={"state": state, "code": "c"})
        check.equal((first.status_code, first.json()["detail"]), (400, "Authorization failed"))
        check.equal((second.status_code, second.json()["detail"]), (400, "Invalid state"))

    def test_tenant_suspended_between_start_and_callback_is_rejected(self, client, registry):
        """ログイン開始後にテナントが停止されたら、コールバックで 403(Login rejected)。トークン交換へ進まない。"""
        state = _query(client.get("/api/auth/app/login", params={"tenant_code": "alpha"}))["state"]
        registry.records[0] = TenantRecord(ALPHA.tenant_id, "alpha", "tenant-alpha", "SUSPENDED")
        response = client.get("/api/auth/callback", params={"state": state, "code": "c"})
        check.equal((response.status_code, response.json()), (403, {"detail": LOGIN_REJECTED_DETAIL}))

    def test_realm_reassigned_to_another_tenant_code_is_rejected(self, client, registry):
        """state の tenant_code とレジストリ上のレルムのテナントコードが食い違えば 403。"""
        state = _query(client.get("/api/auth/app/login", params={"tenant_code": "alpha"}))["state"]
        registry.records[0] = TenantRecord(ALPHA.tenant_id, "other", "tenant-alpha", "ACTIVE")
        response = client.get("/api/auth/callback", params={"state": state, "code": "c"})
        check.equal(response.status_code, 403)

    def test_state_with_invalid_realm_is_400(self, client, fake_redis):
        """保存された state のレルム名が不正なら 400(Invalid state)。"""
        session.save_auth_state("forged", {"plane": "app", "realm": "../master", "tenant_code": "alpha"})
        check.equal(client.get("/api/auth/callback", params={"state": "forged", "code": "c"}).status_code, 400)

    def test_cp_state_with_tenant_realm_is_rejected(self, client):
        """CP の state に control-plane 以外のレルムが入っていたら 403(テナントのレルムで CP のセッションを作らせない)。"""
        session.save_auth_state("forged-cp", {"plane": Plane.CP.value, "realm": "tenant-alpha"})
        check.equal(client.get("/api/auth/callback", params={"state": "forged-cp", "code": "c"}).status_code, 403)

    def test_unknown_plane_in_state_is_400(self, client):
        """未知のプレーンを含む state は 400。"""
        session.save_auth_state("forged-plane", {"plane": "admin", "realm": "master"})
        check.equal(client.get("/api/auth/callback", params={"state": "forged-plane", "code": "c"}).status_code, 400)
