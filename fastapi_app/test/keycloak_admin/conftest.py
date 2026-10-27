# -*- coding: utf-8 -*-
"""modules.keycloak_admin のテスト用フィクスチャ。実機の Keycloak には接続しない。

``kc`` フィクスチャが中心:

    def test_x(kc):
        kc.on("GET", "/keycloak/admin/realms/r1", json={"realm": "r1"})   # 応答を登録(リストを渡すと順に返し、最後を繰り返す)
        result = ensure_realm(kc.admin, "r1")
        assert kc.requests_to("PUT") == []                                 # 送信したリクエストの記録

- トークンエンドポイント(``.../protocol/openid-connect/token``)には既定で応答する(``kc.tokens`` に発行履歴)。
- 登録の無いリクエストは ``AssertionError`` にする(想定外の通信に気づくため)。
- 時計は ``kc.clock``(``advance()`` で進める)。トークンのキャッシュと締め切りが同じ時計を使う。
- パスは URL エンコードされたまま(``raw_path``)で照合する。
"""
import json as jsonlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from modules.keycloak_admin import KeycloakAdminClient
from modules.keycloak_admin.token_provider import PasswordGrantTokenProvider

BASE_URL = "http://keycloak.test/keycloak"
TOKEN_PATH = "/keycloak/realms/master/protocol/openid-connect/token"
ADMIN_PASSWORD = "S3cret-admin-pw"

# テスト対象が読む環境変数。コンテナの実環境値に依存しないよう、毎回消す。
KEYCLOAK_ENV_NAMES = (
    "APP_ENV",
    "KEYCLOAK_URL",
    "KEYCLOAK_HTTP_RELATIVE_PATH",
    "KEYCLOAK_ADMIN_USERNAME",
    "KEYCLOAK_ADMIN_PASSWORD",
    "KEYCLOAK_ADMIN_REALM",
    "KEYCLOAK_ADMIN_CLIENT_ID",
    "KEYCLOAK_ADMIN_TIMEOUT_SECONDS",
    "KEYCLOAK_ADMIN_DEADLINE_SECONDS",
    "APP_CALLBACK_URL",
    "APP_POST_LOGOUT_REDIRECT_URI",
    "APP_WEB_ORIGIN",
    "FRONTEND_URL",
    "KEYCLOAK_INIT_USER_PASSWORD",
)


@pytest.fixture(autouse=True)
def _clean_keycloak_env(monkeypatch):
    """Keycloak 関連の環境変数を消して、テストを実環境から切り離す。"""
    for name in KEYCLOAK_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


class FakeClock:
    """進められる時計(``time.monotonic`` の代わり)。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class RecordedRequest:
    """記録したリクエスト。"""

    method: str
    path: str
    query: dict[str, str]
    headers: httpx.Headers
    body: bytes
    timeout: dict[str, float | None]

    @property
    def json(self) -> Any:
        return jsonlib.loads(self.body) if self.body else None

    @property
    def form(self) -> dict[str, str]:
        return dict(httpx.QueryParams(self.body.decode()))


@dataclass
class _Route:
    responses: list[httpx.Response | Callable[[httpx.Request], httpx.Response] | Exception]
    used: int = 0


@dataclass
class FakeKeycloak:
    """MockTransport のハンドラとルーティング、記録、ClientAdmin の組み立てをまとめたもの。"""

    clock: FakeClock = field(default_factory=FakeClock)
    requests: list[RecordedRequest] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    expires_in: int | None = 60
    token_response: httpx.Response | Exception | None = None
    routes: dict[tuple[str, str], _Route] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.http = httpx.Client(transport=httpx.MockTransport(self._handle), timeout=10.0)
        self.token_provider = PasswordGrantTokenProvider(f"http://keycloak.test{TOKEN_PATH}", "admin", ADMIN_PASSWORD, clock=self.clock)
        self.admin = self.make_admin()

    def make_admin(self, **kwargs: Any) -> KeycloakAdminClient:
        """このフェイクに接続したクライアントを作る(``deadline_seconds`` などを上書きできる)。"""
        kwargs.setdefault("token_provider", self.token_provider)
        return KeycloakAdminClient(BASE_URL, http_client=self.http, clock=self.clock, **kwargs)

    # -- 応答の登録 --------------------------------------------------------
    def on(self, method: str, path: str, *responses: httpx.Response | Callable[[httpx.Request], httpx.Response] | Exception, status: int = 200, json: Any = None, headers: dict[str, str] | None = None) -> None:
        """``method path`` への応答を登録する。複数渡すと順に返し、最後のものを繰り返す。

        引数なしの場合は ``status`` / ``json`` / ``headers`` から 1 つ作る。
        """
        if not responses:
            responses = (httpx.Response(status, json=json, headers=headers),)
        self.routes[(method.upper(), path)] = _Route(list(responses))

    # -- 記録の参照 --------------------------------------------------------
    def requests_to(self, method: str, path: str | None = None) -> list[RecordedRequest]:
        """トークン取得を除く、条件に合う記録を返す。"""
        return [r for r in self.requests if r.method == method and r.path != TOKEN_PATH and (path is None or r.path == path)]

    @property
    def api_requests(self) -> list[RecordedRequest]:
        """トークン取得を除くリクエストの記録。"""
        return [r for r in self.requests if r.path != TOKEN_PATH]

    @property
    def writes(self) -> list[RecordedRequest]:
        """POST / PUT / DELETE の記録(トークン取得を除く)。"""
        return [r for r in self.api_requests if r.method in ("POST", "PUT", "DELETE")]

    # -- ハンドラ ----------------------------------------------------------
    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.split(b"?", 1)[0].decode()
        self.requests.append(RecordedRequest(request.method, path, dict(request.url.params), request.headers, request.content, dict(request.extensions.get("timeout", {}))))
        if path == TOKEN_PATH:
            return self._token(request)
        route = self.routes.get((request.method, path))
        if route is None:
            raise AssertionError(f"想定外のリクエスト: {request.method} {path}(登録済み: {sorted(self.routes)})")
        item = route.responses[min(route.used, len(route.responses) - 1)]
        route.used += 1
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(request)
        return item

    def _token(self, request: httpx.Request) -> httpx.Response:
        if isinstance(self.token_response, Exception):
            raise self.token_response
        if self.token_response is not None:
            return self.token_response
        token = f"access-token-{len(self.tokens) + 1}"
        self.tokens.append(token)
        body: dict[str, Any] = {"access_token": token, "token_type": "Bearer"}
        if self.expires_in is not None:
            body["expires_in"] = self.expires_in
        return httpx.Response(200, json=body)


@pytest.fixture
def kc() -> FakeKeycloak:
    """フェイクの Keycloak と、それに接続した ``kc.admin``(KeycloakAdminClient)。"""
    return FakeKeycloak()

