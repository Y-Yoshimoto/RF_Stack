"""Keycloak Admin REST API の薄い HTTP クライアント。

責務:
    - 管理トークンの付与 (取得方法は :class:`~modules.keycloak_admin.token_provider.AdminTokenProvider` で差し替え可能)
    - 1 リクエストごとのタイムアウトと、操作全体の締め切り (deadline) の適用
    - 401 応答時のトークン再取得 (1 回だけ)
    - 期待しないステータスを秘匿値を含まない例外に変換

テストでは ``httpx.Client(transport=httpx.MockTransport(handler))`` を ``http_client`` に渡すことで、
トークンエンドポイントを含むすべての通信をモックできる。

使用例::

    from modules.keycloak_admin import KeycloakAdminClient

    with KeycloakAdminClient.from_env() as admin:
        ensure_realm(admin, "tenant-a")
"""
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import quote

import httpx

from .errors import KeycloakAdminConnectionError, KeycloakAdminError, KeycloakAdminTimeoutError, summarize_error_response
from .settings import KeycloakAdminSettings
from .token_provider import AdminTokenProvider, PasswordGrantTokenProvider

logger = logging.getLogger(__name__)


def path_segment(value: str) -> str:
    """URL パスの 1 セグメントとして安全にエンコードする。

    レルム名や ID を URL パスに連結する際、``/`` や ``..`` でパスを変えられないようにする。
    ``.`` / ``..`` は ``quote`` ではエンコードされず、httpx の URL 正規化で階層が変わる
    (``/admin/realms/../users`` → ``/admin/users``) ため、セグメント全体がこれらの場合は拒否する。
    名前を検証しない入口 (``get_realm`` / ``ensure_realm_role`` 等) もすべてここを通る。

    Args:
        value: エンコード対象の値。

    Returns:
        str: パーセントエンコード済みの文字列。

    Raises:
        ValueError: 空文字、または ``.`` / ``..`` の場合。
    """
    if not value:
        raise ValueError("path segment must not be empty")
    if value in (".", ".."):
        raise ValueError("path segment must not be '.' or '..'")
    return quote(value, safe="")


class KeycloakAdminClient:
    """Keycloak Admin REST API (``{base_url}/admin/realms``) のクライアント。

    ``deadline_seconds`` を指定すると、インスタンス生成時点から数えた締め切りを過ぎた
    リクエストは送信せずに :class:`KeycloakAdminTimeoutError` を送出する。各リクエストの
    タイムアウトも締め切りまでの残り時間で頭打ちにする。1 回の払い出しごとに
    インスタンスを作ることを想定している。

    Attributes:
        base_url: コンテキストパスを含む Keycloak のベース URL。
        token_provider: 管理トークンの供給元。
        request_timeout_seconds: 1 リクエストあたりのタイムアウト (秒)。
    """

    def __init__(
        self,
        base_url: str,
        token_provider: AdminTokenProvider,
        *,
        http_client: httpx.Client | None = None,
        request_timeout_seconds: float = 10.0,
        deadline_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        """クライアントを初期化する。

        Args:
            base_url: コンテキストパスを含む Keycloak のベース URL (例: ``http://keycloak_c:8080/keycloak``)。
            token_provider: 管理トークンの供給元。
            http_client: 使用する HTTP クライアント。省略時は内部で生成し、:meth:`close` で閉じる。
                         渡した場合のライフサイクルは呼び出し側が管理する。
            request_timeout_seconds: 1 リクエストあたりのタイムアウト (秒)。
            deadline_seconds: 操作全体の締め切り (秒)。``None`` なら締め切りなし。
            clock: 現在時刻 (秒) を返す関数。テストで差し替えられる。
        """
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider
        self.request_timeout_seconds = request_timeout_seconds
        self._clock = clock
        self._deadline = clock() + deadline_seconds if deadline_seconds is not None else None
        self._owns_http_client = http_client is None
        self._http = http_client if http_client is not None else httpx.Client(timeout=request_timeout_seconds)

    @classmethod
    def from_settings(cls, settings: KeycloakAdminSettings, *, token_provider: AdminTokenProvider | None = None, http_client: httpx.Client | None = None) -> "KeycloakAdminClient":
        """設定からクライアントを生成する。

        Args:
            settings: 接続設定。
            token_provider: 管理トークンの供給元。省略時は設定の管理ユーザーでパスワードグラントを使う。
            http_client: 使用する HTTP クライアント。

        Returns:
            KeycloakAdminClient: 生成したクライアント。
        """
        if token_provider is None:
            token_provider = PasswordGrantTokenProvider(
                settings.admin_token_url,
                settings.admin_username,
                settings.admin_password,
                client_id=settings.admin_client_id,
            )
        return cls(
            settings.base_url,
            token_provider,
            http_client=http_client,
            request_timeout_seconds=settings.request_timeout_seconds,
            deadline_seconds=settings.deadline_seconds,
        )

    @classmethod
    def from_env(cls, *, token_provider: AdminTokenProvider | None = None, http_client: httpx.Client | None = None) -> "KeycloakAdminClient":
        """環境変数の設定からクライアントを生成する。

        Args:
            token_provider: 管理トークンの供給元。省略時はパスワードグラント。
            http_client: 使用する HTTP クライアント。

        Returns:
            KeycloakAdminClient: 生成したクライアント。
        """
        return cls.from_settings(KeycloakAdminSettings.from_env(), token_provider=token_provider, http_client=http_client)

    def __enter__(self) -> "KeycloakAdminClient":
        """コンテキストマネージャとして使う。"""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """コンテキスト終了時に HTTP クライアントを閉じる。"""
        self.close()

    def close(self) -> None:
        """内部で生成した HTTP クライアントを閉じる。"""
        if self._owns_http_client:
            self._http.close()

    def realm_url(self, realm: str, *segments: str) -> str:
        """``/admin/realms/{realm}/...`` の URL を組み立てる。

        Args:
            realm: レルム名。
            *segments: 後続のパスセグメント (各セグメントはエンコードされる)。

        Returns:
            str: 組み立てた URL。
        """
        path = "/".join(path_segment(segment) for segment in (realm, *segments))
        return f"{self.base_url}/admin/realms/{path}"

    @property
    def realms_url(self) -> str:
        """レルム一覧/作成の URL (``/admin/realms``) を返す。"""
        return f"{self.base_url}/admin/realms"

    def _timeout(self, operation: str) -> float:
        """このリクエストに使うタイムアウトを締め切りから算出する。

        Args:
            operation: 操作の説明 (締め切り超過時の例外に使う)。

        Returns:
            float: タイムアウト (秒)。

        Raises:
            KeycloakAdminTimeoutError: 締め切りを過ぎている場合。
        """
        if self._deadline is None:
            return self.request_timeout_seconds
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise KeycloakAdminTimeoutError(operation, detail="deadline exceeded")
        return min(self.request_timeout_seconds, remaining)

    def authenticate(self) -> None:
        """管理トークンを取得する (疎通と資格情報の事前確認用)。

        Raises:
            KeycloakAdminError: トークンを取得できない場合。
        """
        self.token_provider.get_access_token(self._http, self._timeout("obtain admin token"))

    def request(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        expected: Iterable[int] = (200,),
        json: Any = None,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """管理トークンを付けてリクエストを送り、ステータスを検証する。

        401 が返った場合はトークンを破棄して 1 回だけ再試行する。

        Args:
            method: HTTP メソッド。
            url: リクエスト URL (:meth:`realm_url` などで組み立てたもの)。
            operation: 操作の説明 (ログと例外メッセージに使う。秘匿値を含めないこと)。
            expected: 成功とみなすステータスコード。
            json: JSON ボディ。
            params: クエリパラメータ。

        Returns:
            httpx.Response: 期待したステータスのレスポンス。

        Raises:
            KeycloakAdminError: 期待しないステータスが返った場合。
            KeycloakAdminTimeoutError: タイムアウト、または締め切りを過ぎた場合。
            KeycloakAdminConnectionError: 接続に失敗した場合。
        """
        expected_codes = set(expected)
        response = self._send(method, url, operation=operation, json=json, params=params)
        if response.status_code == 401:
            logger.info("Keycloak Admin API が 401 を返したため、管理トークンを再取得します (%s)", operation)
            self.token_provider.invalidate()
            response = self._send(method, url, operation=operation, json=json, params=params)

        if response.status_code not in expected_codes:
            raise KeycloakAdminError(operation, response.status_code, summarize_error_response(response))
        return response

    def _send(self, method: str, url: str, *, operation: str, json: Any, params: Mapping[str, str] | None) -> httpx.Response:
        """1 回分のリクエストを送る。

        Args:
            method: HTTP メソッド。
            url: リクエスト URL。
            operation: 操作の説明。
            json: JSON ボディ。
            params: クエリパラメータ。

        Returns:
            httpx.Response: レスポンス。

        Raises:
            KeycloakAdminTimeoutError: タイムアウト、または締め切りを過ぎた場合。
            KeycloakAdminConnectionError: 接続に失敗した場合。
        """
        token = self.token_provider.get_access_token(self._http, self._timeout("obtain admin token"))
        try:
            return self._http.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=json,
                params=params,
                timeout=self._timeout(operation),
            )
        except httpx.TimeoutException as exc:
            raise KeycloakAdminTimeoutError(operation, detail=type(exc).__name__) from None
        except httpx.HTTPError as exc:
            raise KeycloakAdminConnectionError(operation, detail=type(exc).__name__) from None

    def get_json(self, url: str, *, operation: str, params: Mapping[str, str] | None = None) -> Any:
        """GET して JSON を返す。

        Args:
            url: リクエスト URL。
            operation: 操作の説明。
            params: クエリパラメータ。

        Returns:
            Any: デコードした JSON。

        Raises:
            KeycloakAdminError: 200 以外が返った場合。
        """
        return self.request("GET", url, operation=operation, params=params).json()

    def get_json_or_none(self, url: str, *, operation: str) -> Any | None:
        """GET して JSON を返す。404 の場合は ``None`` を返す。

        Args:
            url: リクエスト URL。
            operation: 操作の説明。

        Returns:
            Any | None: デコードした JSON、存在しない場合は ``None``。

        Raises:
            KeycloakAdminError: 200 / 404 以外が返った場合。
        """
        response = self.request("GET", url, operation=operation, expected=(200, 404))
        if response.status_code == 404:
            return None
        return response.json()


def created_id_from_location(response: httpx.Response) -> str | None:
    """作成 (201) レスポンスの ``Location`` ヘッダから作成されたリソースの ID を取り出す。

    Keycloak は ``Location: .../clients/{id}`` のように末尾に ID を付けて返す。

    Args:
        response: 作成リクエストのレスポンス。

    Returns:
        str | None: リソース ID。ヘッダがない場合は ``None``。
    """
    location = response.headers.get("Location", "")
    if not location:
        return None
    last_segment = location.rstrip("/").rsplit("/", 1)[-1]
    return last_segment or None
