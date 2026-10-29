# -*- coding: utf-8 -*-
"""modules.keycloak_admin.token_provider のテスト(MockTransport と注入した時計。実機には接続しない)。"""
import logging

import httpx
import pytest
import pytest_check as check

from modules.keycloak_admin import ClientCredentialsTokenProvider, KeycloakAdminAuthError, KeycloakAdminConnectionError, KeycloakAdminTimeoutError, PasswordGrantTokenProvider
from modules.keycloak_admin.token_provider import TOKEN_EXPIRY_LEEWAY_SECONDS, AdminTokenProvider

TOKEN_URL = "http://kc.test/keycloak/realms/master/protocol/openid-connect/token"


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class TokenServer:
    """トークンエンドポイントのフェイク。リクエストと発行を記録する。"""

    def __init__(self, response=None, expires_in: int | None = 60) -> None:
        self.requests: list[httpx.Request] = []
        self.issued = 0
        self.response = response
        self.expires_in = expires_in
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        if self.response is not None:
            return self.response
        self.issued += 1
        body = {"access_token": f"tok-{self.issued}"}
        if self.expires_in is not None:
            body["expires_in"] = self.expires_in
        return httpx.Response(200, json=body)

    def form(self, index: int = -1) -> dict[str, str]:
        return dict(httpx.QueryParams(self.requests[index].content.decode()))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def server() -> TokenServer:
    return TokenServer()


def _password_provider(clock, **kwargs) -> PasswordGrantTokenProvider:
    return PasswordGrantTokenProvider(TOKEN_URL, "admin", "p@ss word&=", clock=clock, **kwargs)


class TestRequestContent:
    """トークンエンドポイントへ送るフォーム。"""

    def test_password_grant_form(self, clock, server):
        """パスワードグラントは grant_type / client_id / username / password をフォームで POST する(特殊文字はエンコードされる)。"""
        token = _password_provider(clock).get_access_token(server.client, 5.0)
        request = server.requests[0]
        check.equal(token, "tok-1")
        check.equal(request.method, "POST")
        check.equal(str(request.url), TOKEN_URL)
        check.equal(request.headers["content-type"], "application/x-www-form-urlencoded")
        check.equal(server.form(), {"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "p@ss word&="})

    def test_password_grant_custom_client_id(self, clock, server):
        """client_id を指定できる。"""
        _password_provider(clock, client_id="custom-cli").get_access_token(server.client, 5.0)
        check.equal(server.form()["client_id"], "custom-cli")

    def test_client_credentials_form(self, clock, server):
        """クライアントクレデンシャルは grant_type / client_id / client_secret を送り、username/password は送らない。"""
        ClientCredentialsTokenProvider(TOKEN_URL, "cp-provisioner", "s3cr3t", clock=clock).get_access_token(server.client, 5.0)
        check.equal(server.form(), {"grant_type": "client_credentials", "client_id": "cp-provisioner", "client_secret": "s3cr3t"})

    def test_timeout_is_passed_to_request(self, clock, server):
        """呼び出し側から渡されたタイムアウトをリクエストに適用する。"""
        _password_provider(clock).get_access_token(server.client, 3.5)
        check.equal(server.requests[0].extensions["timeout"]["read"], 3.5)

    def test_satisfies_protocol(self, clock):
        """AdminTokenProvider プロトコルを満たす。"""
        check.is_instance(_password_provider(clock), AdminTokenProvider)
        check.is_instance(ClientCredentialsTokenProvider(TOKEN_URL, "c", "s", clock=clock), AdminTokenProvider)


class TestCache:
    """expires_in に基づくキャッシュ。"""

    def test_cached_until_expiry_with_leeway(self, clock, server):
        """有効期限(expires_in - 10 秒)の直前まではキャッシュ、その時点で再取得する。"""
        provider = _password_provider(clock)
        provider.get_access_token(server.client, 5.0)
        clock.now += 60 - TOKEN_EXPIRY_LEEWAY_SECONDS - 0.1
        check.equal(provider.get_access_token(server.client, 5.0), "tok-1")
        check.equal(len(server.requests), 1)
        clock.now += 0.1
        check.equal(provider.get_access_token(server.client, 5.0), "tok-2")
        check.equal(len(server.requests), 2)

    def test_invalidate_forces_refetch(self, clock, server):
        """invalidate 後は有効期限内でも再取得する。"""
        provider = _password_provider(clock)
        provider.get_access_token(server.client, 5.0)
        provider.invalidate()
        check.equal(provider.get_access_token(server.client, 5.0), "tok-2")

    def test_invalidate_without_token_is_noop(self, clock):
        """トークン取得前の invalidate は何も起こさない。"""
        _password_provider(clock).invalidate()

    def test_missing_expires_in_defaults_to_60_seconds(self, clock):
        """expires_in が無ければ 60 秒として扱う。"""
        server = TokenServer(expires_in=None)
        provider = _password_provider(clock)
        provider.get_access_token(server.client, 5.0)
        clock.now += 49
        provider.get_access_token(server.client, 5.0)
        check.equal(len(server.requests), 1)
        clock.now += 1
        provider.get_access_token(server.client, 5.0)
        check.equal(len(server.requests), 2)

    def test_short_lived_token_is_not_cached(self, clock):
        """有効期限が余裕(10 秒)以下のトークンは毎回取り直す。"""
        server = TokenServer(expires_in=5)
        provider = _password_provider(clock)
        provider.get_access_token(server.client, 5.0)
        provider.get_access_token(server.client, 5.0)
        check.equal(len(server.requests), 2)

    def test_failed_fetch_does_not_poison_cache(self, clock):
        """失敗した取得はキャッシュされず、次の呼び出しで再試行する。"""
        server = TokenServer(response=httpx.Response(401, json={"error": "invalid_grant"}))
        provider = _password_provider(clock)
        with pytest.raises(KeycloakAdminAuthError):
            provider.get_access_token(server.client, 5.0)
        server.response = None
        check.equal(provider.get_access_token(server.client, 5.0), "tok-1")


class TestAbnormalResponses:
    """異常応答は KeycloakAdminAuthError(または通信系の例外)に変換される。"""

    def test_non_200_includes_status_and_known_fields(self, clock):
        """200 以外は AuthError。ステータスと error / error_description だけを detail に含める。"""
        server = TokenServer(response=httpx.Response(401, json={"error": "invalid_grant", "error_description": "Invalid user credentials", "access_token": "LEAK", "password": "LEAK"}))
        with pytest.raises(KeycloakAdminAuthError) as exc_info:
            _password_provider(clock).get_access_token(server.client, 5.0)
        error = exc_info.value
        check.equal(error.status_code, 401)
        check.equal(error.operation, "obtain admin token")
        check.equal(error.detail, "error=invalid_grant, error_description=Invalid user credentials")
        check.is_not_in("LEAK", str(error))

    def test_non_json_body_is_truncated(self, clock):
        """JSON でない本文は先頭 200 文字までしか detail に入れない。"""
        server = TokenServer(response=httpx.Response(502, text="x" * 1000))
        with pytest.raises(KeycloakAdminAuthError) as exc_info:
            _password_provider(clock).get_access_token(server.client, 5.0)
        check.equal(exc_info.value.status_code, 502)
        check.equal(len(exc_info.value.detail), 200)

    @pytest.mark.parametrize(
        ("response", "fragment"),
        [
            (httpx.Response(200, text="<html>"), "not JSON"),
            (httpx.Response(200, json=["a"]), "access_token is missing"),
            (httpx.Response(200, json={}), "access_token is missing"),
            (httpx.Response(200, json={"access_token": ""}), "access_token is missing"),
            (httpx.Response(200, json={"access_token": None, "expires_in": 60}), "access_token is missing"),
        ],
    )
    def test_200_without_token_is_auth_error(self, clock, response, fragment):
        """200 でも JSON でない・トークンが無い場合は AuthError。"""
        server = TokenServer(response=response)
        with pytest.raises(KeycloakAdminAuthError, match=fragment):
            _password_provider(clock).get_access_token(server.client, 5.0)

    def test_timeout_is_converted(self, clock):
        """タイムアウトは KeycloakAdminTimeoutError(原因の詳細は型名のみ)。"""
        server = TokenServer(response=httpx.ReadTimeout("secret-url http://x?password=p"))
        with pytest.raises(KeycloakAdminTimeoutError) as exc_info:
            _password_provider(clock).get_access_token(server.client, 5.0)
        check.equal(exc_info.value.detail, "ReadTimeout")
        check.is_not_in("password", str(exc_info.value))

    @pytest.mark.parametrize("failure", [httpx.ConnectError("refused"), httpx.RemoteProtocolError("bad"), httpx.ReadError("reset")])
    def test_connection_failures_are_converted(self, clock, failure):
        """接続失敗・プロトコルエラーは KeycloakAdminConnectionError(タイムアウトとは別)。"""
        server = TokenServer(response=failure)
        with pytest.raises(KeycloakAdminConnectionError) as exc_info:
            _password_provider(clock).get_access_token(server.client, 5.0)
        check.is_not_instance(exc_info.value, KeycloakAdminTimeoutError)
        check.equal(exc_info.value.detail, type(failure).__name__)

    def test_exception_does_not_chain_original(self, clock):
        """元の例外(URL やヘッダを含みうる)を連鎖させない。"""
        server = TokenServer(response=httpx.ConnectError("boom"))
        with pytest.raises(KeycloakAdminConnectionError) as exc_info:
            _password_provider(clock).get_access_token(server.client, 5.0)
        check.is_none(exc_info.value.__cause__)
        check.is_true(exc_info.value.__suppress_context__)


class TestSecretsAreNotExposed:
    """パスワード・シークレット・トークンを repr / 例外 / ログに出さない。"""

    def test_repr_hides_password(self, clock):
        """PasswordGrantTokenProvider の repr / str にパスワードが出ない(ユーザー名は出る)。"""
        provider = _password_provider(clock)
        for text in (repr(provider), str(provider)):
            check.is_not_in("p@ss word&=", text)
            check.is_in("username='admin'", text)

    def test_repr_hides_client_secret(self, clock):
        """ClientCredentialsTokenProvider の repr にシークレットが出ない。"""
        provider = ClientCredentialsTokenProvider(TOKEN_URL, "cp-provisioner", "s3cr3t-value", clock=clock)
        check.is_not_in("s3cr3t-value", repr(provider))
        check.is_in("cp-provisioner", repr(provider))

    def test_repr_hides_cached_token(self, clock, server):
        """取得後も repr にトークンが出ない。"""
        provider = _password_provider(clock)
        provider.get_access_token(server.client, 5.0)
        check.is_not_in("tok-1", repr(provider))

    def test_logs_do_not_contain_token_or_password(self, clock, server, caplog):
        """INFO ログにトークン・パスワードが出ない。"""
        with caplog.at_level(logging.DEBUG, logger="modules.keycloak_admin"):
            _password_provider(clock).get_access_token(server.client, 5.0)
        check.greater(len(caplog.records), 0)
        check.is_not_in("tok-1", caplog.text)
        check.is_not_in("p@ss word&=", caplog.text)

    def test_failure_message_does_not_contain_credentials(self, clock):
        """認証失敗の例外メッセージに、送信したパスワードが出ない。"""
        server = TokenServer(response=httpx.Response(401, json={"error": "invalid_grant"}))
        with pytest.raises(KeycloakAdminAuthError) as exc_info:
            _password_provider(clock).get_access_token(server.client, 5.0)
        check.is_not_in("p@ss word&=", str(exc_info.value))
        check.is_not_in("p@ss", repr(exc_info.value))
