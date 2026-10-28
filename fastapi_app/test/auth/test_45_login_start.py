# -*- coding: utf-8 -*-
"""ログイン開始(GET /api/auth/app/login・/cp/login)とコールバック(GET /api/auth/callback)のテスト。

``main_app.route.auth.apiapp`` のルーターだけをマウントした最小のアプリで確認する(app.py は使わない)。
Redis はインメモリの代替、テナントレジストリは ``dependency_overrides[get_tenant_registry]`` で差し替える。
AP のログイン時のユーザー同期 (``sync_app_user_on_login``) は差し替えて呼び出しだけを確認する (DB には接続しない)。
"""
import json
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_check as check
import redis.exceptions
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from main_app.route.auth import apiapp
from main_app.services.errors import UserDeactivatedError
from main_app.services.user_sync import TenantContextMismatchError, UserSyncResult
from modules.auth import session
from modules.auth.login import LOGIN_REJECTED_DETAIL
from modules.auth.plane import Plane
from modules.auth.redirects import LoginErrorCode
from modules.errors.catalog import PROBLEM_TEXTS
from modules.tenancy.providers import get_tenant_registry
from modules.tenancy.registry import TenantRecord, TenantStatus

ALPHA = TenantRecord(tenant_id=uuid.UUID("0194e6a0-0000-7000-8000-00000000a1fa"), tenant_code="alpha", realm_name="tenant-alpha", status="ACTIVE")
FRONTEND = "http://localhost:5173"
UNAVAILABLE_LOCATION = f"{FRONTEND}/?error=tenant_unavailable"


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


class SyncRecorder:
    """``sync_app_user_on_login`` の代替。呼び出しと、その時点のセッションの有無を記録する。"""

    def __init__(self, redis) -> None:
        self.redis = redis
        self.calls: list[dict] = []
        self.error: Exception | None = None

    def __call__(self, session_data, *, tenant_id, tenant_code):
        sessions = [key for key in self.redis.keys() if key.startswith("session:app:")]
        self.calls.append({"tenant_id": tenant_id, "tenant_code": tenant_code, "sub": session_data["user"]["sub"], "sessions_before": sessions})
        if self.error is not None:
            raise self.error
        return UserSyncResult(user_id=uuid.uuid4(), created=False, profile_updated=False, email_conflict=False, default_organization_id=None)


@pytest.fixture(autouse=True)
def user_sync(monkeypatch, fake_redis) -> SyncRecorder:
    """AP のログイン時のユーザー同期を差し替える (DB に接続しない)。"""
    recorder = SyncRecorder(fake_redis)
    monkeypatch.setattr(apiapp, "sync_app_user_on_login", recorder)
    return recorder


@pytest.fixture
def client(config, registry, monkeypatch) -> TestClient:
    """apiapp のルーターを /api/auth にマウントしたアプリ(リダイレクトは追わない。サーバー側の例外はそのまま送出しない)。"""
    monkeypatch.setattr(apiapp, "_config", config)
    app = FastAPI()
    app.include_router(apiapp.router, prefix="/api/auth")
    app.dependency_overrides[get_tenant_registry] = lambda: registry
    return TestClient(app, follow_redirects=False, raise_server_exceptions=False)


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


def _start_app(client) -> str:
    """AP (alpha) のログインを開始して state を返す。"""
    return _query(client.get("/api/auth/app/login", params={"tenant_code": "alpha"}))["state"]


def _start_cp(client) -> str:
    """CP のログインを開始して state を返す。"""
    return _query(client.get("/api/auth/cp/login"))["state"]


def _assert_redirect(response, location: str, label: str = "") -> None:
    """JSON を返さず、指定の場所へ 302 し、セッション Cookie を発行しないこと。"""
    check.equal(response.status_code, 302, label)
    check.equal(response.headers.get("location"), location, label)
    check.equal(response.text, "", label)
    check.is_not_in("rf_sid_", response.headers.get("set-cookie", ""), label)


class TestCallbackEntry:
    """コールバックの入口(トークン交換の前に拒否されるケース)。Keycloak へは通信しない。

    失敗は JSON を返さず、ログイン画面へ ``?error=<code>`` を付けて 302 する。
    """

    @pytest.fixture(autouse=True)
    def _no_network(self, monkeypatch):
        monkeypatch.setattr(apiapp.httpx, "post", lambda *a, **k: pytest.fail("トークン交換へ進んではならない"))

    @pytest.mark.parametrize("params", [{}, {"state": ""}, {"state": "unknown", "code": "c"}])
    def test_unknown_state_redirects_to_landing(self, client, params):
        """state が無い・未知のコールバックは、プレーンもテナントも分からないのでランディングへ(invalid_auth_state)。"""
        _assert_redirect(client.get("/api/auth/callback", params=params), f"{FRONTEND}/?error=invalid_auth_state")

    def test_state_is_single_use(self, client, fake_redis):
        """同じ state での 2 回目のコールバックは invalid_auth_state(リプレイ不可)。1 回目も認可コードが無ければ失敗し、state を消費する。"""
        state = _start_app(client)
        first = client.get("/api/auth/callback", params={"state": state, "error": "access_denied"})
        second = client.get("/api/auth/callback", params={"state": state, "code": "c"})
        _assert_redirect(first, f"{FRONTEND}/alpha/login?error=authorization_failed")
        _assert_redirect(second, f"{FRONTEND}/?error=invalid_auth_state")
        check.equal(fake_redis.keys(), [])

    def test_cp_without_code_returns_to_cp_login(self, client):
        """CP のコールバックで認可コードが無ければ /cp/login?error=authorization_failed。"""
        _assert_redirect(client.get("/api/auth/callback", params={"state": _start_cp(client)}), f"{FRONTEND}/cp/login?error=authorization_failed")

    def test_tenant_suspended_between_start_and_callback(self, client, registry):
        """ログイン開始後にテナントが停止されたら、そのテナントのログイン画面へ tenant_unavailable。トークン交換へ進まない。"""
        state = _start_app(client)
        registry.records[0] = TenantRecord(ALPHA.tenant_id, "alpha", "tenant-alpha", "SUSPENDED")
        _assert_redirect(client.get("/api/auth/callback", params={"state": state, "code": "c"}), f"{FRONTEND}/alpha/login?error=tenant_unavailable")

    def test_realm_reassigned_to_another_tenant_code_is_rejected(self, client, registry):
        """state の tenant_code とレジストリ上のレルムのテナントコードが食い違えば tenant_unavailable(state のテナントのログイン画面へ)。"""
        state = _start_app(client)
        registry.records[0] = TenantRecord(ALPHA.tenant_id, "other", "tenant-alpha", "ACTIVE")
        _assert_redirect(client.get("/api/auth/callback", params={"state": state, "code": "c"}), f"{FRONTEND}/alpha/login?error=tenant_unavailable")

    def test_state_with_invalid_realm(self, client, fake_redis):
        """保存された state のレルム名が不正なら invalid_auth_state。プレーンとテナントは分かるのでそのログイン画面へ。"""
        session.save_auth_state("forged", {"plane": "app", "realm": "../master", "tenant_code": "alpha"})
        _assert_redirect(client.get("/api/auth/callback", params={"state": "forged", "code": "c"}), f"{FRONTEND}/alpha/login?error=invalid_auth_state")

    def test_cp_state_with_tenant_realm_is_rejected(self, client):
        """CP の state に control-plane 以外のレルムが入っていたら login_rejected(テナントのレルムで CP のセッションを作らせない)。"""
        session.save_auth_state("forged-cp", {"plane": Plane.CP.value, "realm": "tenant-alpha"})
        _assert_redirect(client.get("/api/auth/callback", params={"state": "forged-cp", "code": "c"}), f"{FRONTEND}/cp/login?error=login_rejected")

    def test_unknown_plane_in_state_redirects_to_landing(self, client):
        """未知のプレーンを含む state は invalid_auth_state でランディングへ。"""
        session.save_auth_state("forged-plane", {"plane": "admin", "realm": "master"})
        _assert_redirect(client.get("/api/auth/callback", params={"state": "forged-plane", "code": "c"}), f"{FRONTEND}/?error=invalid_auth_state")

    @pytest.mark.parametrize("tenant_code", [None, "", "../evil", "//evil.example.com", "A", "evil.example.com/x", 123])
    def test_tenant_code_in_state_is_not_trusted_for_the_url(self, client, tenant_code):
        """state の tenant_code が形式に合わなければ URL に使わず、ランディングへ戻す(オープンリダイレクト・パス操作をしない)。"""
        session.save_auth_state("odd", {"plane": "app", "realm": "../bad", "tenant_code": tenant_code})
        _assert_redirect(client.get("/api/auth/callback", params={"state": "odd", "code": "c"}), f"{FRONTEND}/?error=invalid_auth_state")

    def test_oauth_error_from_idp_is_not_reflected(self, client):
        """認証サーバーの error / error_description は遷移先に反映しない(コードは固定の語彙のみ)。"""
        state = _start_app(client)
        response = client.get("/api/auth/callback", params={"state": state, "error": "evil<script>", "error_description": "x"})
        _assert_redirect(response, f"{FRONTEND}/alpha/login?error=authorization_failed")


class FakeTokenResponse:
    """httpx.post の戻り値の代替。"""

    def __init__(self, status_code: int = 200, body: object = None, *, invalid_json: bool = False) -> None:
        self.status_code = status_code
        self._body = {"access_token": "a", "refresh_token": "r", "id_token": "i"} if body is None else body
        self._invalid_json = invalid_json

    def json(self) -> object:
        if self._invalid_json:
            raise ValueError("not json")
        return self._body


def _session_for(plane: Plane, realm: str, tenant_code: str | None) -> dict:
    """build_login_session の代替が返すセッション。"""
    data = {"plane": plane.value, "realm": realm, "tokens": {"id_token": "i"}, "user": {"sub": "s", "plane": plane.value, "roles": []}}
    if plane == Plane.APP:
        data["tenant_code"] = tenant_code
    return data


class TestCallbackCompletion:
    """コールバックの完了(トークン交換以降)。Keycloak への通信とトークン検証は差し替える。"""

    @pytest.fixture
    def exchange(self, monkeypatch):
        """トークン交換の応答・トークン検証の結果を差し替える。呼び出し内容を記録する。"""
        calls: dict = {"post": [], "login": []}
        state = {"response": FakeTokenResponse(), "login_error": None}

        def fake_post(url, data=None, timeout=None):
            calls["post"].append({"url": url, **(data or {})})
            if isinstance(state["response"], Exception):
                raise state["response"]
            return state["response"]

        def fake_build(config, plane, realm, token_data, *, expected_nonce, tenant_code=None, expected_tenant_id=None):
            calls["login"].append({"plane": plane, "realm": realm, "tenant_code": tenant_code, "expected_tenant_id": expected_tenant_id, "nonce": expected_nonce})
            if state["login_error"] is not None:
                raise state["login_error"]
            return _session_for(plane, realm, tenant_code)

        monkeypatch.setattr(apiapp.httpx, "post", fake_post)
        monkeypatch.setattr(apiapp, "build_login_session", fake_build)
        return calls, state

    def test_app_success_redirects_to_tenant_home(self, client, exchange, fake_redis):
        """AP のログイン成功は /{tenant_code}/ へ 302 し、rf_sid_app を発行する。レジストリの tenant_id と state の nonce で検証する。"""
        calls, _ = exchange
        state = _start_app(client)
        nonce = json.loads(fake_redis.data[f"auth_state:{state}"])["nonce"]
        response = client.get("/api/auth/callback", params={"state": state, "code": "c"})
        check.equal((response.status_code, response.headers["location"]), (302, f"{FRONTEND}/alpha/"))
        check.is_true(response.headers["set-cookie"].startswith("rf_sid_app="))
        check.equal(calls["login"], [{"plane": Plane.APP, "realm": "tenant-alpha", "tenant_code": "alpha", "expected_tenant_id": str(ALPHA.tenant_id), "nonce": nonce}])
        check.equal([key for key in fake_redis.keys() if key.startswith("session:app:")].__len__(), 1)

    def test_cp_success_redirects_to_cp_home(self, client, exchange):
        """CP のログイン成功は /cp/ へ 302 し、rf_sid_cp を発行する。"""
        response = client.get("/api/auth/callback", params={"state": _start_cp(client), "code": "c"})
        check.equal((response.status_code, response.headers["location"]), (302, f"{FRONTEND}/cp/"))
        check.is_true(response.headers["set-cookie"].startswith("rf_sid_cp="))

    def test_success_replaces_existing_session_of_the_same_plane_only(self, client, exchange, login_as, fake_redis):
        """ログイン成功時は同じプレーンの既存セッションを破棄し、もう一方のプレーンのセッションは残す。"""
        old_app_cookie, old_app_sid = login_as(Plane.APP, ["member"])
        cp_cookie, cp_sid = login_as(Plane.CP, ["saas_admin"])
        state = _start_app(client)
        client.get("/api/auth/callback", params={"state": state, "code": "c"}, headers={"Cookie": f"rf_sid_app={old_app_cookie}; rf_sid_cp={cp_cookie}"})
        check.is_none(session.get_session(Plane.APP, old_app_sid))
        check.is_not_none(session.get_session(Plane.CP, cp_sid))

    @pytest.mark.parametrize(
        ("result", "error"),
        [
            (httpx.ConnectError("down"), "identity_provider_unreachable"),
            (FakeTokenResponse(400, {"error": "invalid_grant"}), "token_exchange_failed"),
            (FakeTokenResponse(invalid_json=True), "token_exchange_failed"),
            (FakeTokenResponse(body=["not", "an", "object"]), "token_exchange_failed"),
        ],
        ids=["unreachable", "rejected", "non-json", "non-object"],
    )
    def test_token_exchange_failures(self, client, exchange, result, error):
        """トークン交換の失敗は、AP はテナントのログイン画面、CP は /cp/login へ、理由に応じたコードで 302 する。"""
        _, state = exchange
        state["response"] = result
        _assert_redirect(client.get("/api/auth/callback", params={"state": _start_app(client), "code": "c"}), f"{FRONTEND}/alpha/login?error={error}", "app")
        _assert_redirect(client.get("/api/auth/callback", params={"state": _start_cp(client), "code": "c"}), f"{FRONTEND}/cp/login?error={error}", "cp")

    @pytest.mark.parametrize(
        ("exc", "error"),
        [
            (HTTPException(401, "Invalid token"), "invalid_token"),
            (HTTPException(401, "Invalid token response"), "invalid_token"),
            (HTTPException(403, LOGIN_REJECTED_DETAIL), "login_rejected"),
            (HTTPException(403, "something new"), "forbidden"),
            (HTTPException(418, "something new"), "bad_request"),
            (HTTPException(500, "boom"), "internal_error"),
        ],
    )
    def test_verification_failures_use_problem_codes(self, client, exchange, exc, error):
        """トークン検証の失敗(HTTPException)は Problem Details と同じ対応表でコードにする。表で login 用に無いものは寄せる。"""
        _, state = exchange
        state["login_error"] = exc
        expected = error if error in {c.value for c in LoginErrorCode} else ("internal_error" if exc.status_code >= 500 else "login_rejected")
        _assert_redirect(client.get("/api/auth/callback", params={"state": _start_app(client), "code": "c"}), f"{FRONTEND}/alpha/login?error={expected}")

    def test_session_store_failure_redirects(self, client, exchange, monkeypatch):
        """セッションストアに書けない場合も JSON を返さず service_unavailable で 302 する。"""

        def broken(*_a, **_k):
            raise redis.exceptions.ConnectionError("down")

        state = _start_cp(client)
        monkeypatch.setattr(apiapp, "create_session", broken)
        _assert_redirect(client.get("/api/auth/callback", params={"state": state, "code": "c"}), f"{FRONTEND}/cp/login?error=service_unavailable")

    def test_state_store_failure_redirects_to_landing(self, client, monkeypatch):
        """state を読めない(Redis 障害)場合はプレーンが分からないのでランディングへ service_unavailable。"""

        def broken(*_a, **_k):
            raise redis.exceptions.TimeoutError("slow")

        monkeypatch.setattr(apiapp, "pop_auth_state", broken)
        _assert_redirect(client.get("/api/auth/callback", params={"state": "s", "code": "c"}), f"{FRONTEND}/?error=service_unavailable")

    def test_unexpected_error_redirects(self, client, exchange, monkeypatch):
        """想定外の例外も JSON を返さず internal_error で 302 する。"""
        state = _start_app(client)
        monkeypatch.setattr(apiapp, "set_session_cookie", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bug")))
        _assert_redirect(client.get("/api/auth/callback", params={"state": state, "code": "c"}), f"{FRONTEND}/alpha/login?error=internal_error")

    def test_failure_details_are_not_reflected_or_leaked(self, client, exchange, caplog):
        """失敗の詳細(認証サーバーの応答など)は遷移先に含めず、トークン・シークレットはログにも出さない。"""
        _, state = exchange
        state["response"] = FakeTokenResponse(401, {"error": "unauthorized_client", "error_description": "secret detail"})
        response = client.get("/api/auth/callback", params={"state": _start_app(client), "code": "the-code"})
        server_logs = " ".join(record.getMessage() for record in caplog.records if record.name == apiapp.logger.name)
        check.is_not_in("secret detail", response.headers["location"])
        check.is_in("token_exchange_failed", server_logs, "理由はログに残す")
        for secret in ("the-code", "client_secret", config_secret(client)):
            check.is_not_in(secret, server_logs)


class TestCallbackUserSync:
    """AP のログイン完了時のユーザー同期 (01 PF-USR-04 / 05、05 #31)。トークン交換・検証は差し替える。"""

    @pytest.fixture(autouse=True)
    def _exchange(self, monkeypatch):
        monkeypatch.setattr(apiapp.httpx, "post", lambda *a, **k: FakeTokenResponse())
        monkeypatch.setattr(apiapp, "build_login_session", lambda config, plane, realm, token_data, **kw: _session_for(plane, realm, kw.get("tenant_code")))

    def test_app_login_syncs_with_registry_tenant_before_creating_the_session(self, client, user_sync, login_as):
        """AP のログイン成功時は、レジストリのテナント (state やクレームではない) で 1 回だけ同期し、その後にセッションを作る。"""
        old_cookie, _ = login_as(Plane.APP, ["member"])
        response = client.get("/api/auth/callback", params={"state": _start_app(client), "code": "c"}, headers={"Cookie": f"rf_sid_app={old_cookie}"})
        check.equal((response.status_code, response.headers["location"]), (302, f"{FRONTEND}/alpha/"))
        check.equal(len(user_sync.calls), 1)
        call = user_sync.calls[0]
        check.equal((call["tenant_id"], call["tenant_code"], call["sub"]), (ALPHA.tenant_id, "alpha", "s"))
        check.equal(len(call["sessions_before"]), 1, "同期の時点では新しいセッションを作っていない (既存のセッションだけ)")

    def test_deactivated_user_is_rejected_without_a_session(self, client, user_sync, fake_redis, caplog):
        """無効化されたユーザーはセッションを作らず login_rejected でテナントのログイン画面へ。ログに利用者 ID・トークンを出さない。"""
        user_sync.error = UserDeactivatedError(uuid.UUID("0194e6a0-0000-7000-8000-0000000000d1"))
        response = client.get("/api/auth/callback", params={"state": _start_app(client), "code": "the-code"})
        _assert_redirect(response, f"{FRONTEND}/alpha/login?error=login_rejected")
        check.equal([key for key in fake_redis.keys() if key.startswith("session:")], [])
        logs = " ".join(record.getMessage() for record in caplog.records if record.name == apiapp.logger.name)
        check.is_in("deactivated", logs)
        for secret in ("the-code", "id_token", config_secret(client)):
            check.is_not_in(secret, logs)

    def test_db_unavailable_is_service_unavailable(self, client, user_sync, fake_redis):
        """AP の DB に接続できなければ service_unavailable。セッションを作らない。"""
        user_sync.error = OperationalError("SELECT 1", {}, Exception("connection refused"))
        _assert_redirect(client.get("/api/auth/callback", params={"state": _start_app(client), "code": "c"}), f"{FRONTEND}/alpha/login?error=service_unavailable")
        check.equal([key for key in fake_redis.keys() if key.startswith("session:")], [])

    def test_unexpected_sync_error_is_internal_error(self, client, user_sync):
        """同期のそれ以外の失敗 (テナントコンテキストの不一致など) は internal_error。"""
        user_sync.error = TenantContextMismatchError("mismatch")
        _assert_redirect(client.get("/api/auth/callback", params={"state": _start_app(client), "code": "c"}), f"{FRONTEND}/alpha/login?error=internal_error")

    def test_cp_login_does_not_sync(self, client, user_sync):
        """CP のログインではユーザー同期を呼ばない。"""
        response = client.get("/api/auth/callback", params={"state": _start_cp(client), "code": "c"})
        check.equal(response.headers["location"], f"{FRONTEND}/cp/")
        check.equal(user_sync.calls, [])

    def test_failure_before_session_build_does_not_sync(self, client, user_sync, monkeypatch):
        """トークンの検証に失敗したら同期しない (検証済みのユーザーだけを同期する)。"""
        monkeypatch.setattr(apiapp, "build_login_session", lambda *a, **k: (_ for _ in ()).throw(HTTPException(401, "Invalid token")))
        _assert_redirect(client.get("/api/auth/callback", params={"state": _start_app(client), "code": "c"}), f"{FRONTEND}/alpha/login?error=invalid_token")
        check.equal(user_sync.calls, [])


def config_secret(_client) -> str:
    """テスト用設定で導出される AP のクライアントシークレット。"""
    return apiapp._config.client_secret_for(Plane.APP, "tenant-alpha")


class TestLoginErrorCodes:
    """遷移先へ渡すエラーコードの語彙。"""

    def test_codes_are_problem_details_codes(self):
        """すべてのコードが Problem Details の code(modules.errors.catalog)として定義済みで、文言を持つ。"""
        check.equal({code.value for code in LoginErrorCode} - set(PROBLEM_TEXTS), set())
