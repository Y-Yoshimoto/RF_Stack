# -*- coding: utf-8 -*-
"""modules.keycloak_admin.admin_client / errors のテスト(MockTransport と注入した時計)。"""
import httpx
import pytest
import pytest_check as check

from modules.keycloak_admin import (
    KeycloakAdminAuthError,
    KeycloakAdminClient,
    KeycloakAdminConnectionError,
    KeycloakAdminError,
    KeycloakAdminSettings,
    KeycloakAdminTimeoutError,
    PasswordGrantTokenProvider,
)
from modules.keycloak_admin.admin_client import created_id_from_location, path_segment
from modules.keycloak_admin.errors import summarize_error_response

from .conftest import ADMIN_PASSWORD, BASE_URL, TOKEN_PATH, FakeKeycloak

PING = "/keycloak/admin/realms/r1/ping"
PING_URL = f"{BASE_URL}/admin/realms/r1/ping"


class TestAuthorization:
    """Authorization ヘッダとトークンの再利用。"""

    def test_bearer_token_is_attached(self, kc: FakeKeycloak):
        """管理トークンを Bearer で付ける。"""
        kc.on("GET", PING, json={"ok": True})
        kc.admin.request("GET", PING_URL, operation="ping")
        check.equal(kc.api_requests[0].headers["authorization"], "Bearer access-token-1")

    def test_token_is_reused_across_requests(self, kc: FakeKeycloak):
        """複数リクエストでトークンは 1 回だけ取得する。"""
        kc.on("GET", PING, json={})
        for _ in range(3):
            kc.admin.request("GET", PING_URL, operation="ping")
        check.equal(len(kc.tokens), 1)

    def test_token_is_refetched_after_expiry(self, kc: FakeKeycloak):
        """トークンの期限(expires_in - 10 秒)を過ぎると取り直す。"""
        kc.on("GET", PING, json={})
        kc.admin.request("GET", PING_URL, operation="ping")
        kc.clock.advance(50)
        kc.admin.request("GET", PING_URL, operation="ping")
        check.equal(len(kc.tokens), 2)
        check.equal(kc.api_requests[1].headers["authorization"], "Bearer access-token-2")

    def test_json_body_and_params_are_sent(self, kc: FakeKeycloak):
        """json と params をそのまま送る。"""
        kc.on("POST", PING, status=201)
        kc.admin.request("POST", PING_URL, operation="ping", expected=(201,), json={"a": 1}, params={"q": "x y"})
        request = kc.api_requests[0]
        check.equal(request.json, {"a": 1})
        check.equal(request.query, {"q": "x y"})

    def test_authenticate_fetches_token_only(self, kc: FakeKeycloak):
        """authenticate は管理トークンだけを取得し、他のリクエストは送らない。"""
        kc.admin.authenticate()
        check.equal(len(kc.tokens), 1)
        check.equal(kc.api_requests, [])

    def test_authentication_failure_propagates(self, kc: FakeKeycloak):
        """トークン取得に失敗したら KeycloakAdminAuthError で、API リクエストは送らない。"""
        kc.token_response = httpx.Response(401, json={"error": "invalid_grant"})
        with pytest.raises(KeycloakAdminAuthError):
            kc.admin.request("GET", PING_URL, operation="ping")
        check.equal(kc.api_requests, [])


class TestRetryOn401:
    """401 では管理トークンを取り直して 1 回だけ再試行する。"""

    def test_retries_once_with_new_token(self, kc: FakeKeycloak):
        """1 回目が 401、2 回目が 200 なら成功し、2 回目は新しいトークンを使う。"""
        kc.on("GET", PING, httpx.Response(401), httpx.Response(200, json={"ok": True}))
        response = kc.admin.request("GET", PING_URL, operation="ping")
        check.equal(response.json(), {"ok": True})
        check.equal(len(kc.api_requests), 2)
        check.equal(len(kc.tokens), 2)
        check.equal([r.headers["authorization"] for r in kc.api_requests], ["Bearer access-token-1", "Bearer access-token-2"])

    def test_second_401_is_not_retried_again(self, kc: FakeKeycloak):
        """再試行後も 401 なら例外にし、3 回目は送らない。"""
        kc.on("GET", PING, httpx.Response(401, json={"error": "unauthorized"}))
        with pytest.raises(KeycloakAdminError) as exc_info:
            kc.admin.request("GET", PING_URL, operation="ping")
        check.equal(exc_info.value.status_code, 401)
        check.equal(len(kc.api_requests), 2)

    def test_401_is_accepted_if_expected(self, kc: FakeKeycloak):
        """expected に 401 を含めても、まず 1 回は再試行する(その後の 401 は期待どおりとして返る)。"""
        kc.on("GET", PING, httpx.Response(401))
        response = kc.admin.request("GET", PING_URL, operation="ping", expected=(200, 401))
        check.equal(response.status_code, 401)
        check.equal(len(kc.api_requests), 2)

    @pytest.mark.parametrize("status", [400, 403, 404, 500])
    def test_other_errors_are_not_retried(self, kc: FakeKeycloak, status):
        """401 以外のエラーは再試行しない。"""
        kc.on("GET", PING, httpx.Response(status))
        with pytest.raises(KeycloakAdminError) as exc_info:
            kc.admin.request("GET", PING_URL, operation="ping")
        check.equal(exc_info.value.status_code, status)
        check.equal(len(kc.api_requests), 1)


class TestErrors:
    """期待しないステータスの例外。detail は既知フィールドのみ。"""

    def test_message_and_attributes(self, kc: FakeKeycloak):
        """例外は operation / status_code / detail を持ち、メッセージに整形される。"""
        kc.on("POST", PING, httpx.Response(400, json={"errorMessage": "bad input"}))
        with pytest.raises(KeycloakAdminError) as exc_info:
            kc.admin.request("POST", PING_URL, operation="create thing", expected=(201,))
        error = exc_info.value
        check.equal((error.operation, error.status_code, error.detail), ("create thing", 400, "errorMessage=bad input"))
        check.equal(str(error), "Failed to create thing. HTTP 400 errorMessage=bad input")

    def test_only_known_fields_are_kept(self, kc: FakeKeycloak):
        """error / error_description / errorMessage / field だけを(この順で)detail に含め、他のフィールドは捨てる。"""
        body = {"field": "email", "errorMessage": "m", "error_description": "d", "error": "e", "access_token": "LEAK", "password": "LEAK", "nested": {"secret": "LEAK"}}
        kc.on("POST", PING, httpx.Response(400, json=body))
        with pytest.raises(KeycloakAdminError) as exc_info:
            kc.admin.request("POST", PING_URL, operation="op", expected=(201,))
        check.equal(exc_info.value.detail, "error=e, error_description=d, errorMessage=m, field=email")
        check.is_not_in("LEAK", str(exc_info.value))

    def test_empty_known_fields_are_skipped(self):
        """値が空の既知フィールドは含めない。"""
        check.equal(summarize_error_response(httpx.Response(400, json={"error": "", "errorMessage": None, "field": "x"})), "field=x")

    def test_json_list_and_empty_body_give_empty_detail(self):
        """JSON が辞書でない・本文が空の場合、detail は空。"""
        check.equal(summarize_error_response(httpx.Response(400, json=["a"])), "")
        check.equal(summarize_error_response(httpx.Response(400)), "")

    def test_text_body_is_truncated_and_stripped(self):
        """JSON でない本文は strip し、200 文字で切る。"""
        check.equal(summarize_error_response(httpx.Response(500, text="  down  ")), "down")
        check.equal(len(summarize_error_response(httpx.Response(500, text="y" * 500))), 200)

    def test_message_without_status_or_detail(self):
        """status_code も detail も無ければ operation だけのメッセージ。"""
        check.equal(str(KeycloakAdminError("do thing")), "Failed to do thing.")

    def test_subclass_hierarchy(self):
        """Auth / Timeout / Connection はすべて KeycloakAdminError のサブクラス。"""
        for cls in (KeycloakAdminAuthError, KeycloakAdminTimeoutError, KeycloakAdminConnectionError):
            check.is_true(issubclass(cls, KeycloakAdminError))


class TestTransportFailures:
    """タイムアウト・接続失敗の例外変換。"""

    @pytest.mark.parametrize("failure", [httpx.ConnectTimeout("t"), httpx.ReadTimeout("t"), httpx.WriteTimeout("t"), httpx.PoolTimeout("t")])
    def test_timeouts(self, kc: FakeKeycloak, failure):
        """各種タイムアウトは KeycloakAdminTimeoutError(詳細は型名だけで元の例外を連鎖させない)。"""
        kc.on("GET", PING, failure)
        with pytest.raises(KeycloakAdminTimeoutError) as exc_info:
            kc.admin.request("GET", PING_URL, operation="ping")
        check.equal(exc_info.value.detail, type(failure).__name__)
        check.is_none(exc_info.value.__cause__)
        check.is_none(exc_info.value.status_code)

    @pytest.mark.parametrize("failure", [httpx.ConnectError("refused"), httpx.ReadError("reset"), httpx.RemoteProtocolError("bad"), httpx.DecodingError("bad")])
    def test_connection_errors(self, kc: FakeKeycloak, failure):
        """接続失敗など通信系のエラーは KeycloakAdminConnectionError。"""
        kc.on("GET", PING, failure)
        with pytest.raises(KeycloakAdminConnectionError) as exc_info:
            kc.admin.request("GET", PING_URL, operation="ping")
        check.is_not_instance(exc_info.value, KeycloakAdminTimeoutError)
        check.equal(exc_info.value.detail, type(failure).__name__)

    def test_timeout_is_not_retried(self, kc: FakeKeycloak):
        """タイムアウトは再試行しない(401 のときだけ再試行)。"""
        kc.on("GET", PING, httpx.ReadTimeout("t"))
        with pytest.raises(KeycloakAdminTimeoutError):
            kc.admin.request("GET", PING_URL, operation="ping")
        check.equal(len(kc.api_requests), 1)


class TestDeadline:
    """全体の締め切り(deadline_seconds)と 1 リクエストのタイムアウト。"""

    def test_request_after_deadline_is_not_sent(self, kc: FakeKeycloak):
        """締め切りを過ぎたらリクエスト(トークン取得を含む)を一切送らず KeycloakAdminTimeoutError。"""
        admin = kc.make_admin(deadline_seconds=30)
        kc.clock.advance(30.5)
        with pytest.raises(KeycloakAdminTimeoutError) as exc_info:
            admin.request("GET", PING_URL, operation="ping")
        check.equal(exc_info.value.detail, "deadline exceeded")
        check.equal(kc.requests, [])

    def test_deadline_boundary_is_exceeded(self, kc: FakeKeycloak):
        """残り時間がちょうど 0 でも超過扱い。"""
        admin = kc.make_admin(deadline_seconds=30)
        kc.clock.advance(30)
        with pytest.raises(KeycloakAdminTimeoutError):
            admin.authenticate()
        check.equal(kc.requests, [])

    def test_deadline_counts_from_instantiation(self, kc: FakeKeycloak):
        """締め切りはインスタンス生成時点から数える(生成前の経過時間は含まない)。"""
        kc.clock.advance(500)
        admin = kc.make_admin(deadline_seconds=30)
        kc.on("GET", PING, json={})
        admin.request("GET", PING_URL, operation="ping")

    def test_deadline_exceeded_between_requests(self, kc: FakeKeycloak):
        """途中で締め切りを過ぎたら、以降のリクエストは送らない。"""
        admin = kc.make_admin(deadline_seconds=30)
        kc.on("GET", PING, json={})
        admin.request("GET", PING_URL, operation="ping")
        kc.clock.advance(31)
        with pytest.raises(KeycloakAdminTimeoutError):
            admin.request("GET", PING_URL, operation="ping")
        check.equal(len(kc.api_requests), 1)

    def test_deadline_exceeded_before_401_retry(self, kc: FakeKeycloak):
        """401 の応答を受けた時点で締め切りを過ぎていたら、再試行せずに TimeoutError。"""
        admin = kc.make_admin(deadline_seconds=30)

        def unauthorized_then_late(request: httpx.Request) -> httpx.Response:
            kc.clock.advance(31)
            return httpx.Response(401)

        kc.on("GET", PING, unauthorized_then_late)
        with pytest.raises(KeycloakAdminTimeoutError):
            admin.request("GET", PING_URL, operation="ping")
        check.equal(len(kc.api_requests), 1)

    def test_per_request_timeout_is_capped_by_remaining_time(self, kc: FakeKeycloak):
        """1 リクエストのタイムアウトは min(既定 10 秒, 締め切りまでの残り)。トークン取得にも同じ制限をかける。"""
        admin = kc.make_admin(deadline_seconds=30, request_timeout_seconds=10)
        kc.on("GET", PING, json={})
        kc.clock.advance(25)  # 残り 5 秒
        admin.request("GET", PING_URL, operation="ping")
        check.equal(kc.requests[0].path, TOKEN_PATH)
        check.equal(kc.requests[0].timeout["read"], 5)
        check.equal(kc.api_requests[0].timeout["read"], 5)

    def test_per_request_timeout_when_plenty_of_time(self, kc: FakeKeycloak):
        """残り時間が十分ならリクエストのタイムアウトは request_timeout_seconds。"""
        admin = kc.make_admin(deadline_seconds=30, request_timeout_seconds=7)
        kc.on("GET", PING, json={})
        admin.request("GET", PING_URL, operation="ping")
        check.equal(kc.api_requests[0].timeout["read"], 7)

    def test_without_deadline_never_expires(self, kc: FakeKeycloak):
        """deadline_seconds=None なら時間が経っても締め切りはなく、タイムアウトは request_timeout_seconds。"""
        admin = kc.make_admin(deadline_seconds=None, request_timeout_seconds=4)
        kc.on("GET", PING, json={})
        kc.clock.advance(10**6)
        admin.request("GET", PING_URL, operation="ping")
        check.equal(kc.api_requests[0].timeout["read"], 4)


class TestUrls:
    """URL の組み立てとエンコード。"""

    def test_base_url_trailing_slash_is_stripped(self, kc: FakeKeycloak):
        """base_url の末尾スラッシュは除く。"""
        admin = KeycloakAdminClient(BASE_URL + "//", kc.token_provider, http_client=kc.http)
        check.equal(admin.base_url, BASE_URL)
        check.equal(admin.realms_url, f"{BASE_URL}/admin/realms")

    def test_realm_url_plain(self, kc: FakeKeycloak):
        """realm_url は /admin/realms/{realm}/... を返す。"""
        check.equal(kc.admin.realm_url("r1"), f"{BASE_URL}/admin/realms/r1")
        check.equal(kc.admin.realm_url("r1", "clients", "abc", "client-secret"), f"{BASE_URL}/admin/realms/r1/clients/abc/client-secret")

    def test_segments_are_percent_encoded(self, kc: FakeKeycloak):
        """各セグメントはエンコードされ、/ ? # 空白でパスを変えられない。"""
        url = kc.admin.realm_url("a/b", "users", "x y?z#w", "../etc")
        check.equal(url, f"{BASE_URL}/admin/realms/a%2Fb/users/x%20y%3Fz%23w/..%2Fetc")

    def test_encoded_url_reaches_server_unchanged(self, kc: FakeKeycloak):
        """エンコードした URL は httpx に正規化されず、そのままのパスでサーバーに届く。"""
        kc.on("GET", "/keycloak/admin/realms/a%2Fb/roles/x%20y", json={})
        kc.admin.request("GET", kc.admin.realm_url("a/b", "roles", "x y"), operation="op")
        check.equal(kc.api_requests[0].path, "/keycloak/admin/realms/a%2Fb/roles/x%20y")

    def test_empty_segment_is_rejected(self, kc: FakeKeycloak):
        """空のセグメントは ValueError。"""
        with pytest.raises(ValueError):
            kc.admin.realm_url("")
        with pytest.raises(ValueError):
            kc.admin.realm_url("r1", "users", "")
        with pytest.raises(ValueError):
            path_segment("")

    def test_non_ascii_segment_is_utf8_encoded(self):
        """非 ASCII は UTF-8 でパーセントエンコードされる。"""
        check.equal(path_segment("日本"), "%E6%97%A5%E6%9C%AC")

    @pytest.mark.parametrize("segment", ["..", "."])
    def test_dot_segments_are_rejected(self, kc: FakeKeycloak, segment):
        """'.' / '..' のセグメントは httpx のパス正規化で階層を変えるため ValueError で拒否する。"""
        with pytest.raises(ValueError):
            path_segment(segment)
        with pytest.raises(ValueError):
            kc.admin.realm_url(segment, "users")
        with pytest.raises(ValueError):
            kc.admin.realm_url("r1", "roles", segment)

    def test_dots_inside_segment_are_allowed(self, kc: FakeKeycloak):
        """セグメント全体が '.' / '..' でなければ許可する(ロール名 'a.b' や '...' など)。"""
        check.equal(kc.admin.realm_url("r1", "roles", "a.b"), f"{BASE_URL}/admin/realms/r1/roles/a.b")
        check.equal(path_segment("..."), "...")


class TestGetJson:
    """get_json / get_json_or_none。"""

    def test_get_json_returns_body(self, kc: FakeKeycloak):
        """200 の JSON を返す。"""
        kc.on("GET", PING, json={"a": [1, 2]})
        check.equal(kc.admin.get_json(PING_URL, operation="op"), {"a": [1, 2]})

    def test_get_json_404_raises(self, kc: FakeKeycloak):
        """get_json は 404 を例外にする。"""
        kc.on("GET", PING, httpx.Response(404, json={"error": "Not found"}))
        with pytest.raises(KeycloakAdminError) as exc_info:
            kc.admin.get_json(PING_URL, operation="op")
        check.equal(exc_info.value.status_code, 404)

    def test_get_json_or_none(self, kc: FakeKeycloak):
        """get_json_or_none は 404 で None、200 で JSON、それ以外は例外。"""
        kc.on("GET", PING, httpx.Response(404), httpx.Response(200, json={"x": 1}), httpx.Response(500))
        check.is_none(kc.admin.get_json_or_none(PING_URL, operation="op"))
        check.equal(kc.admin.get_json_or_none(PING_URL, operation="op"), {"x": 1})
        with pytest.raises(KeycloakAdminError):
            kc.admin.get_json_or_none(PING_URL, operation="op")


class TestLocationHeader:
    """created_id_from_location。"""

    @pytest.mark.parametrize(
        ("location", "expected"),
        [
            ("http://kc/admin/realms/r/clients/abc-123", "abc-123"),
            ("http://kc/admin/realms/r/clients/abc-123/", "abc-123"),
            ("abc", "abc"),
            ("", None),
            ("/", None),
        ],
    )
    def test_last_segment(self, location, expected):
        """Location の末尾セグメントを ID として返す。無ければ None。"""
        headers = {"Location": location} if location else {}
        check.equal(created_id_from_location(httpx.Response(201, headers=headers)), expected)


class TestLifecycle:
    """生成・クローズ。"""

    def test_context_manager_does_not_close_injected_client(self, kc: FakeKeycloak):
        """外部から渡した HTTP クライアントは閉じない(呼び出し側の管理)。"""
        with kc.make_admin() as admin:
            check.is_(admin.token_provider, kc.token_provider)
        check.is_false(kc.http.is_closed)

    def test_owned_client_is_closed(self):
        """http_client を省略すると内部で生成し、close で閉じる。"""
        admin = KeycloakAdminClient(BASE_URL, PasswordGrantTokenProvider("http://x/t", "u", "p"))
        http = admin._http
        check.is_false(http.is_closed)
        with admin:
            pass
        check.is_true(http.is_closed)

    def test_from_settings_builds_password_grant(self, kc: FakeKeycloak):
        """from_settings は設定の管理ユーザーでパスワードグラントのプロバイダを組み立て、設定値を引き継ぐ。"""
        settings = KeycloakAdminSettings(
            server_url="http://keycloak.test/", http_relative_path="/keycloak/", admin_username="root", admin_password="pw!", admin_client_id="my-cli", request_timeout_seconds=3.0, deadline_seconds=12.0
        )
        admin = KeycloakAdminClient.from_settings(settings, http_client=kc.http)
        check.equal(admin.base_url, BASE_URL)
        check.equal(admin.request_timeout_seconds, 3.0)
        check.is_instance(admin.token_provider, PasswordGrantTokenProvider)
        admin.authenticate()
        token_request = kc.requests[0]
        check.equal(token_request.path, TOKEN_PATH)
        check.equal(token_request.form, {"grant_type": "password", "client_id": "my-cli", "username": "root", "password": "pw!"})
        check.is_not_in("pw!", repr(admin.token_provider))

    def test_from_settings_uses_given_token_provider(self, kc: FakeKeycloak):
        """token_provider を渡せば、それを使う。"""
        admin = KeycloakAdminClient.from_settings(KeycloakAdminSettings(), token_provider=kc.token_provider, http_client=kc.http)
        check.is_(admin.token_provider, kc.token_provider)

    def test_from_env(self, kc: FakeKeycloak, monkeypatch):
        """from_env は環境変数の設定でクライアントを作る。"""
        monkeypatch.setenv("KEYCLOAK_URL", "http://keycloak.test")
        monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", ADMIN_PASSWORD)
        monkeypatch.setenv("KEYCLOAK_ADMIN_TIMEOUT_SECONDS", "2.5")
        admin = KeycloakAdminClient.from_env(http_client=kc.http)
        check.equal(admin.base_url, BASE_URL)
        check.equal(admin.request_timeout_seconds, 2.5)
