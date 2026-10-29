"""Keycloak Admin API の接続設定とアプリ用クライアントの既定値。

設定値はすべて環境変数から読む (``.env`` ファイルは読まない)。
コンテナ (``fastapi_app``) 内で実行することを前提に、既定値はコンテナ内部ネットワークの URL とする。

環境変数と旧シェルスクリプト (``setup_realm_client_user.sh``) の対応:

============================== ============================== ====================================
本モジュール                   旧シェル版                     既定値
============================== ============================== ====================================
``KEYCLOAK_URL``               ``KEYCLOAK_BASE_URL``          ``http://keycloak_c:8080``
``KEYCLOAK_HTTP_RELATIVE_PATH`` 同名                          ``keycloak``
``KEYCLOAK_ADMIN_USERNAME``    同名                           ``admin``
``KEYCLOAK_ADMIN_PASSWORD``    同名                           ``admin`` (development のみ)
``KEYCLOAK_ADMIN_REALM``       (``master`` 固定)              ``master``
``KEYCLOAK_ADMIN_CLIENT_ID``   (``admin-cli`` 固定)           ``admin-cli``
``KEYCLOAK_ADMIN_TIMEOUT_SECONDS`` (なし)                     ``10``
``KEYCLOAK_ADMIN_DEADLINE_SECONDS`` (なし)                    ``30``
``APP_CALLBACK_URL``           同名                           ``http://localhost:5173/api/auth/callback``
``APP_POST_LOGOUT_REDIRECT_URI`` 同名                         ``${FRONTEND_URL}/*``
``APP_WEB_ORIGIN``             同名                           ``${FRONTEND_URL}``
``FRONTEND_URL``               (なし)                         ``http://localhost:5173``
``KEYCLOAK_INIT_USER_PASSWORD`` 同名                          ``ChangeMe123!``
============================== ============================== ====================================

払い出し用の管理クライアント (:func:`~modules.keycloak_admin.templates.create_provisioner_admin_client`) は、
``APP_ENV=development`` 以外では上記の管理ユーザーではなく ``cp-provisioner`` のクライアントクレデンシャルを使う:

- ``KEYCLOAK_PROVISIONER_CLIENT_ID`` (既定 ``cp-provisioner``。``KEYCLOAK_ADMIN_REALM`` のクライアント)
- ``KEYCLOAK_PROVISIONER_CLIENT_SECRET`` (必須。既定値なし)

テンプレートのログイン用クライアントは BFF と同じ ``KEYCLOAK_CLIENT_ID`` / ``KEYCLOAK_CP_CLIENT_ID`` /
``FRONTEND_URL`` / ``APP_CALLBACK_URL`` / ``APP_ENV`` を読む (:class:`PlatformClientSettings`)。
"""
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_KEYCLOAK_URL = "http://keycloak_c:8080"
DEFAULT_HTTP_RELATIVE_PATH = "keycloak"
DEFAULT_ADMIN_REALM = "master"
DEFAULT_ADMIN_CLIENT_ID = "admin-cli"
DEFAULT_ADMIN_USERNAME = "admin"
# 開発用の既定パスワード。APP_ENV=development 以外では使用を拒否する。
INSECURE_DEFAULT_ADMIN_PASSWORD = "admin"

# 1 リクエストあたりのタイムアウト (秒)。
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
# 1 回の払い出し全体の締め切り (秒)。払い出しは同期実行で 30 秒以内を目標とする。
DEFAULT_DEADLINE_SECONDS = 30.0

DEFAULT_FRONTEND_URL = "http://localhost:5173"
DEFAULT_CALLBACK_URL = "http://localhost:5173/api/auth/callback"
DEFAULT_INIT_USER_PASSWORD = "ChangeMe123!"


def _read_float(name: str, default: float) -> float:
    """環境変数を正の浮動小数点数として読む。

    Args:
        name: 環境変数名。
        default: 未設定時の既定値。

    Returns:
        float: 読み取った値。

    Raises:
        ValueError: 数値として解釈できない、または 0 以下の場合。
    """
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


@dataclass(frozen=True, kw_only=True)
class KeycloakAdminSettings:
    """Keycloak Admin API への接続設定。

    Attributes:
        server_url: Keycloak のベース URL (コンテキストパスを含まない)。
        http_relative_path: Keycloak の HTTP コンテキストパス (``KC_HTTP_RELATIVE_PATH``)。
        admin_realm: 管理トークンを取得するレルム。
        admin_client_id: 管理トークンを取得するクライアント ID。
        admin_username: パスワードグラントで使う管理ユーザー名。
        admin_password: パスワードグラントで使う管理パスワード。``repr`` には出さない。
        request_timeout_seconds: 1 リクエストあたりのタイムアウト。
        deadline_seconds: 1 つの :class:`~modules.keycloak_admin.admin_client.KeycloakAdminClient` で行う操作全体の締め切り。
    """

    server_url: str = DEFAULT_KEYCLOAK_URL
    http_relative_path: str = DEFAULT_HTTP_RELATIVE_PATH
    admin_realm: str = DEFAULT_ADMIN_REALM
    admin_client_id: str = DEFAULT_ADMIN_CLIENT_ID
    admin_username: str = DEFAULT_ADMIN_USERNAME
    admin_password: str = field(default=INSECURE_DEFAULT_ADMIN_PASSWORD, repr=False)
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    deadline_seconds: float | None = DEFAULT_DEADLINE_SECONDS

    @property
    def base_url(self) -> str:
        """コンテキストパスを含む Keycloak のベース URL を返す。

        Returns:
            str: ``{server_url}/{http_relative_path}`` (コンテキストパスが空なら ``server_url``)。
        """
        server = self.server_url.rstrip("/")
        path = self.http_relative_path.strip("/")
        return f"{server}/{path}" if path else server

    @property
    def admin_token_url(self) -> str:
        """管理トークンを取得するトークンエンドポイント URL を返す。

        Returns:
            str: ``{base_url}/realms/{admin_realm}/protocol/openid-connect/token``。
        """
        return f"{self.base_url}/realms/{self.admin_realm}/protocol/openid-connect/token"

    @classmethod
    def from_env(cls, *, require_admin_password: bool = True) -> "KeycloakAdminSettings":
        """環境変数から設定を読み込む。

        ``KEYCLOAK_ADMIN_PASSWORD`` が未設定の場合、``APP_ENV=development`` では
        警告を出して開発用既定値 (``admin``) を使う。それ以外の環境ではエラーにする。

        Args:
            require_admin_password: 管理パスワードを必要とするか。クライアントクレデンシャル
                (``cp-provisioner``) で管理トークンを取得する場合は ``False`` とし、
                パスワードは空のままにする (開発用既定値も使わない)。

        Returns:
            KeycloakAdminSettings: 読み込んだ設定。

        Raises:
            RuntimeError: 本番相当の環境で管理パスワードが未設定の場合 (``require_admin_password`` が真のとき)。
            ValueError: タイムアウト値が不正な場合。
        """
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        admin_password = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "")
        if not require_admin_password:
            admin_password = ""
        elif not admin_password:
            if app_env != "development":
                raise RuntimeError(f"KEYCLOAK_ADMIN_PASSWORD が未設定です。APP_ENV={app_env} では開発用既定値を使用できません。")
            logger.warning("KEYCLOAK_ADMIN_PASSWORD が未設定のため、開発用既定値を使用します。")
            admin_password = INSECURE_DEFAULT_ADMIN_PASSWORD

        return cls(
            server_url=os.getenv("KEYCLOAK_URL", DEFAULT_KEYCLOAK_URL).strip() or DEFAULT_KEYCLOAK_URL,
            http_relative_path=os.getenv("KEYCLOAK_HTTP_RELATIVE_PATH", DEFAULT_HTTP_RELATIVE_PATH).strip(),
            admin_realm=os.getenv("KEYCLOAK_ADMIN_REALM", DEFAULT_ADMIN_REALM).strip() or DEFAULT_ADMIN_REALM,
            admin_client_id=os.getenv("KEYCLOAK_ADMIN_CLIENT_ID", DEFAULT_ADMIN_CLIENT_ID).strip() or DEFAULT_ADMIN_CLIENT_ID,
            admin_username=os.getenv("KEYCLOAK_ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME).strip() or DEFAULT_ADMIN_USERNAME,
            admin_password=admin_password,
            request_timeout_seconds=_read_float("KEYCLOAK_ADMIN_TIMEOUT_SECONDS", DEFAULT_REQUEST_TIMEOUT_SECONDS),
            deadline_seconds=_read_float("KEYCLOAK_ADMIN_DEADLINE_SECONDS", DEFAULT_DEADLINE_SECONDS),
        )


@dataclass(frozen=True, kw_only=True)
class AppClientSettings:
    """テナントレルムに作成するアプリ用 OIDC クライアントの URL 設定。

    Attributes:
        callback_url: 認可コードフローのリダイレクト先 (Valid redirect URIs)。
        post_logout_redirect_uri: ログアウト後のリダイレクト先 (Valid post logout redirect URIs)。
        web_origin: Web origins。
    """

    callback_url: str = DEFAULT_CALLBACK_URL
    post_logout_redirect_uri: str = f"{DEFAULT_FRONTEND_URL}/*"
    web_origin: str = DEFAULT_FRONTEND_URL

    @classmethod
    def from_env(cls) -> "AppClientSettings":
        """環境変数から設定を読み込む。

        ``APP_POST_LOGOUT_REDIRECT_URI`` / ``APP_WEB_ORIGIN`` が未設定の場合は
        ``FRONTEND_URL`` から導出する。

        Returns:
            AppClientSettings: 読み込んだ設定。
        """
        frontend_url = (os.getenv("FRONTEND_URL", "").strip() or DEFAULT_FRONTEND_URL).rstrip("/")
        return cls(
            callback_url=os.getenv("APP_CALLBACK_URL", "").strip() or DEFAULT_CALLBACK_URL,
            post_logout_redirect_uri=os.getenv("APP_POST_LOGOUT_REDIRECT_URI", "").strip() or f"{frontend_url}/*",
            web_origin=os.getenv("APP_WEB_ORIGIN", "").strip() or frontend_url,
        )


def default_init_user_password() -> str:
    """初期ユーザーパスワードの既定値を返す。

    Returns:
        str: ``KEYCLOAK_INIT_USER_PASSWORD``、未設定なら ``ChangeMe123!``。
    """
    return os.getenv("KEYCLOAK_INIT_USER_PASSWORD", "") or DEFAULT_INIT_USER_PASSWORD


@dataclass(frozen=True, kw_only=True)
class PlatformClientSettings:
    """テンプレート (``modules.keycloak_admin.templates``) が作るログイン用クライアントの設定 (02 §3.1)。

    BFF (``modules.auth.environment``) と同じ環境変数を読む。値が食い違うと、BFF の導出する
    シークレットやリダイレクト URI がクライアントの設定と合わなくなるため。

    Attributes:
        app_client_id: AP のログイン用クライアント ID (``KEYCLOAK_CLIENT_ID``、既定 ``fastapi-app``)。
        cp_client_id: CP のログイン用クライアント ID (``KEYCLOAK_CP_CLIENT_ID``、既定 ``fastapi-cp``)。
        frontend_url: フロントエンドのベース URL (``FRONTEND_URL``)。Web origins とログアウト後の遷移先に使う。
        callback_url: 認可コードフローのリダイレクト先 (``APP_CALLBACK_URL``。未設定なら ``{FRONTEND_URL}/api/auth/callback``)。
        direct_access_grants_enabled: パスワードグラントを有効にするか。``APP_ENV=development`` のときだけ真 (02 §3.1)。
    """

    app_client_id: str = "fastapi-app"
    cp_client_id: str = "fastapi-cp"
    frontend_url: str = DEFAULT_FRONTEND_URL
    callback_url: str = DEFAULT_CALLBACK_URL
    direct_access_grants_enabled: bool = False

    @classmethod
    def from_env(cls) -> "PlatformClientSettings":
        """環境変数から設定を読み込む。

        Returns:
            PlatformClientSettings: 読み込んだ設定。
        """
        frontend_url = (os.getenv("FRONTEND_URL", "").strip() or DEFAULT_FRONTEND_URL).rstrip("/")
        return cls(
            app_client_id=os.getenv("KEYCLOAK_CLIENT_ID", "").strip() or "fastapi-app",
            cp_client_id=os.getenv("KEYCLOAK_CP_CLIENT_ID", "").strip() or "fastapi-cp",
            frontend_url=frontend_url,
            callback_url=os.getenv("APP_CALLBACK_URL", "").strip() or f"{frontend_url}/api/auth/callback",
            direct_access_grants_enabled=os.getenv("APP_ENV", "development").strip().lower() == "development",
        )
