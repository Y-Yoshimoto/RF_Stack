"""BFF からフロントエンドへ遷移させる先 (パス) の唯一の定義 (01 §11.1、02 §5.2)。

ログイン開始・コールバック・ログアウト・開発用ログインが使う。フロントエンドのルーティング
(``/``、``/{tenant_code}/login``、``/{tenant_code}/*``、``/cp/login``、``/cp/*``) と合わせて変更すること。

=========================== ================================== ==============================
場面                        AP                                 CP
=========================== ================================== ==============================
ログイン成功                ``/{tenant_code}/``                ``/cp/``
ログイン開始で利用不可      ``/?error=tenant_unavailable``     (なし)
コールバックの失敗          ``/{tenant_code}/login?error=``    ``/cp/login?error=``
ログアウト後                ``/{tenant_code}/login``           ``/cp/login``
開発用ログインの ``next``   ``/{tenant_code}/``                ``/cp/``
=========================== ================================== ==============================

AP でテナントコードが分からない (state が無効などでプレーン・テナントを復元できない) 場合はランディング (``/``) とする。
ここで組み立てるのは **パスのみ** であり、ホスト部は常に ``FRONTEND_URL`` を使う (オープンリダイレクトにしない)。
テナントコードはサーバー側で決めた値 (レジストリ・state・セッション) だけを使い、形式に合わなければランディングにする。
"""
from enum import StrEnum
from urllib.parse import urlencode

from .plane import Plane, is_valid_tenant_code

LANDING_PATH = "/"
CP_HOME_PATH = "/cp/"
CP_LOGIN_PATH = "/cp/login"

# 遷移先のクエリでエラーを伝えるパラメータ名。
ERROR_QUERY_PARAM = "error"


class LoginErrorCode(StrEnum):
    """ログイン画面・ランディングへ ``?error=`` で渡すエラーコード。

    値は Problem Details の ``code`` (``modules.errors.catalog``) と同じ語彙を使う。
    フロントエンドはこの値で文言を出し分ける。詳細 (理由・外部サービスの応答) はサーバーのログにだけ残す。
    """

    # ログイン開始・コールバック: テナントが形式不正・未登録・ACTIVE でない、またはレルムとテナントが食い違う (理由を区別しない)
    TENANT_UNAVAILABLE = "tenant_unavailable"
    # コールバック: state が無い・期限切れ・使用済み・内容が不正
    INVALID_AUTH_STATE = "invalid_auth_state"
    # コールバック: 認証サーバーが認可コードを返さなかった (利用者のキャンセル・認証サーバー側のエラー)
    AUTHORIZATION_FAILED = "authorization_failed"
    # コールバック: 認可コードをトークンに交換できなかった
    TOKEN_EXCHANGE_FAILED = "token_exchange_failed"
    # コールバック: トークンが欠けている・署名やクレームの検証に失敗した
    INVALID_TOKEN = "invalid_token"
    # コールバック: テナント ID の不一致、CP のロール不足など、認証は成功したがログインを許可しない (理由を区別しない)
    LOGIN_REJECTED = "login_rejected"
    # コールバック: 認証サーバーに到達できない
    IDENTITY_PROVIDER_UNREACHABLE = "identity_provider_unreachable"
    # コールバック: セッションストア・DB に接続できない
    SERVICE_UNAVAILABLE = "service_unavailable"
    # コールバック: 想定外のエラー
    INTERNAL_ERROR = "internal_error"


def _tenant_path(tenant_code: str | None, suffix: str) -> str:
    """``/{tenant_code}/{suffix}`` を返す。テナントコードが形式に合わなければランディング。

    Args:
        tenant_code: テナントコード (サーバー側で決めた値)。
        suffix: テナントコードの後に続くパス (先頭の ``/`` なし)。

    Returns:
        str: パス。
    """
    if not is_valid_tenant_code(tenant_code):
        return LANDING_PATH
    return f"/{tenant_code}/{suffix}"


def post_login_path(plane: Plane, tenant_code: str | None = None) -> str:
    """ログイン成功後の遷移先パスを返す (AP: ``/{tenant_code}/``、CP: ``/cp/``)。

    Args:
        plane: プレーン。
        tenant_code: AP のテナントコード。

    Returns:
        str: パス。
    """
    if plane == Plane.CP:
        return CP_HOME_PATH
    return _tenant_path(tenant_code, "")


def login_page_path(plane: Plane, tenant_code: str | None = None) -> str:
    """プレーンのログイン画面のパスを返す (AP: ``/{tenant_code}/login``、CP: ``/cp/login``)。

    ログアウト後の遷移先にも使う。

    Args:
        plane: プレーン。
        tenant_code: AP のテナントコード。

    Returns:
        str: パス。
    """
    if plane == Plane.CP:
        return CP_LOGIN_PATH
    return _tenant_path(tenant_code, "login")


def with_error(path: str, code: LoginErrorCode) -> str:
    """パスに ``?error=<code>`` を付ける。

    Args:
        path: 遷移先のパス (クエリなし)。
        code: エラーコード。

    Returns:
        str: クエリ付きのパス。
    """
    return f"{path}?{urlencode({ERROR_QUERY_PARAM: code.value})}"


def login_error_path(code: LoginErrorCode, plane: Plane | None = None, tenant_code: str | None = None) -> str:
    """ログインの失敗時の遷移先パスを返す。

    - CP: ``/cp/login?error=<code>``
    - AP (テナントコードが分かる): ``/{tenant_code}/login?error=<code>``
    - プレーンまたはテナントコードが分からない: ``/?error=<code>``

    Args:
        code: エラーコード。
        plane: プレーン (不明なら ``None``)。
        tenant_code: AP のテナントコード。

    Returns:
        str: クエリ付きのパス。
    """
    path = LANDING_PATH if plane is None else login_page_path(plane, tenant_code)
    return with_error(path, code)
