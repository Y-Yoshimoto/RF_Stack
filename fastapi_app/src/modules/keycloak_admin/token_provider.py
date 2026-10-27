"""Keycloak Admin API 用の管理トークン取得 (差し替え可能)。

:class:`AdminTokenProvider` プロトコルを満たすオブジェクトであれば、
:class:`~modules.keycloak_admin.admin_client.KeycloakAdminClient` に注入できる。

- :class:`PasswordGrantTokenProvider` — master レルムの ``admin-cli`` に対するパスワードグラント
  (旧シェルスクリプトと同じ方式。開発環境向け)。
- :class:`ClientCredentialsTokenProvider` — サービスアカウント (例: ``cp-provisioner``) に対する
  クライアントクレデンシャルグラント。コントロールプレーンからの払い出しではこちらに差し替える。

いずれも取得したトークンを ``expires_in`` に基づいてキャッシュする。
トークン・パスワード・シークレットはログ・例外メッセージ・``repr`` に出さない。
"""
import logging
import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import httpx

from .errors import KeycloakAdminAuthError, KeycloakAdminConnectionError, KeycloakAdminTimeoutError, summarize_error_response

logger = logging.getLogger(__name__)

# 有効期限がこの秒数以内に迫ったトークンは再取得する。
TOKEN_EXPIRY_LEEWAY_SECONDS = 10.0


@runtime_checkable
class AdminTokenProvider(Protocol):
    """管理トークンを供給するオブジェクトのプロトコル。"""

    def get_access_token(self, http_client: httpx.Client, timeout: float) -> str:
        """有効な管理アクセストークンを返す。

        Args:
            http_client: トークンエンドポイントへのリクエストに使う HTTP クライアント。
            timeout: このリクエストに許容するタイムアウト (秒)。

        Returns:
            str: アクセストークン。

        Raises:
            KeycloakAdminAuthError: トークンを取得できない場合。
        """
        ...

    def invalidate(self) -> None:
        """キャッシュ済みのトークンを破棄する (401 応答時に呼ばれる)。"""
        ...


class _CachingTokenProvider:
    """トークンエンドポイントへの POST とキャッシュを共通化した基底クラス。

    サブクラスは :meth:`_grant_form` でグラント固有のフォームパラメータを返す。
    """

    def __init__(self, token_url: str, client_id: str, *, clock: Callable[[], float] = time.monotonic):
        """プロバイダを初期化する。

        Args:
            token_url: トークンエンドポイント URL。
            client_id: トークンを要求するクライアント ID。
            clock: 現在時刻 (秒) を返す関数。テストで差し替えられる。
        """
        self.token_url = token_url
        self.client_id = client_id
        self._clock = clock
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    def _grant_form(self) -> dict[str, str]:
        """グラント固有のフォームパラメータを返す。

        Returns:
            dict[str, str]: ``application/x-www-form-urlencoded`` で送るパラメータ。
        """
        raise NotImplementedError

    def get_access_token(self, http_client: httpx.Client, timeout: float) -> str:
        """有効な管理アクセストークンを返す。キャッシュが有効ならそれを返す。

        Args:
            http_client: トークンエンドポイントへのリクエストに使う HTTP クライアント。
            timeout: このリクエストに許容するタイムアウト (秒)。

        Returns:
            str: アクセストークン。

        Raises:
            KeycloakAdminAuthError: 認証に失敗した、またはレスポンスにトークンが含まれない場合。
            KeycloakAdminTimeoutError: タイムアウトした場合。
            KeycloakAdminConnectionError: 接続に失敗した場合。
        """
        if self._access_token and self._clock() < self._expires_at:
            return self._access_token

        try:
            response = http_client.post(self.token_url, data=self._grant_form(), timeout=timeout)
        except httpx.TimeoutException as exc:
            raise KeycloakAdminTimeoutError("obtain admin token", detail=type(exc).__name__) from None
        except httpx.HTTPError as exc:
            raise KeycloakAdminConnectionError("obtain admin token", detail=type(exc).__name__) from None

        if response.status_code != 200:
            raise KeycloakAdminAuthError("obtain admin token", response.status_code, summarize_error_response(response))

        try:
            body = response.json()
        except ValueError:
            raise KeycloakAdminAuthError("obtain admin token", response.status_code, "response is not JSON") from None
        access_token = body.get("access_token") if isinstance(body, dict) else None
        if not access_token:
            raise KeycloakAdminAuthError("obtain admin token", response.status_code, "access_token is missing")

        expires_in = float(body.get("expires_in") or 60)
        self._access_token = access_token
        self._expires_at = self._clock() + max(expires_in - TOKEN_EXPIRY_LEEWAY_SECONDS, 0.0)
        logger.info("Keycloak 管理トークンを取得しました (client_id=%s, expires_in=%ss)", self.client_id, int(expires_in))
        return access_token

    def invalidate(self) -> None:
        """キャッシュ済みのトークンを破棄する。"""
        self._access_token = None
        self._expires_at = 0.0


class PasswordGrantTokenProvider(_CachingTokenProvider):
    """パスワードグラントで管理トークンを取得するプロバイダ。

    旧シェルスクリプトと同じく、master レルムの ``admin-cli`` に管理ユーザーの
    資格情報を送る。管理者パスワードを扱うため、開発環境での利用を想定する。
    """

    def __init__(self, token_url: str, username: str, password: str, *, client_id: str = "admin-cli", clock: Callable[[], float] = time.monotonic):
        """プロバイダを初期化する。

        Args:
            token_url: トークンエンドポイント URL。
            username: 管理ユーザー名。
            password: 管理パスワード。
            client_id: トークンを要求するクライアント ID。既定は ``admin-cli``。
            clock: 現在時刻 (秒) を返す関数。
        """
        super().__init__(token_url, client_id, clock=clock)
        self.username = username
        self._password = password

    def __repr__(self) -> str:
        """パスワードを含まない文字列表現を返す。"""
        return f"PasswordGrantTokenProvider(token_url={self.token_url!r}, client_id={self.client_id!r}, username={self.username!r})"

    def _grant_form(self) -> dict[str, str]:
        """パスワードグラントのフォームパラメータを返す。

        Returns:
            dict[str, str]: フォームパラメータ。
        """
        return {"grant_type": "password", "client_id": self.client_id, "username": self.username, "password": self._password}


class ClientCredentialsTokenProvider(_CachingTokenProvider):
    """クライアントクレデンシャルグラントで管理トークンを取得するプロバイダ。

    コントロールプレーン用のサービスアカウント (例: ``cp-provisioner``) に差し替えるためのもの。
    サービスアカウントには払い出しに必要な ``realm-management`` ロールだけを付与すること。
    """

    def __init__(self, token_url: str, client_id: str, client_secret: str, *, clock: Callable[[], float] = time.monotonic):
        """プロバイダを初期化する。

        Args:
            token_url: トークンエンドポイント URL。
            client_id: サービスアカウントのクライアント ID。
            client_secret: クライアントシークレット。
            clock: 現在時刻 (秒) を返す関数。
        """
        super().__init__(token_url, client_id, clock=clock)
        self._client_secret = client_secret

    def __repr__(self) -> str:
        """シークレットを含まない文字列表現を返す。"""
        return f"ClientCredentialsTokenProvider(token_url={self.token_url!r}, client_id={self.client_id!r})"

    def _grant_form(self) -> dict[str, str]:
        """クライアントクレデンシャルグラントのフォームパラメータを返す。

        Returns:
            dict[str, str]: フォームパラメータ。
        """
        return {"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self._client_secret}
