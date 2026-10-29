#!/usr/bin/env python
# coding:utf-8
"""KeyCloak と連携する OIDC Authorization Code Flow (PKCE) の認証エンドポイント群 (BFF、プレーン別)。

実装前提:
    - FastAPI が BFF (Backend-for-Frontend) として動作する。ブラウザはトークンを持たず、
      HttpOnly のセッション Cookie (AP: ``rf_sid_app``、CP: ``rf_sid_cp``) だけを持つ。
    - React は Vite proxy 経由で ``/api/**`` を FastAPI に転送するため、
      ブラウザから見ると全ての通信は同一オリジン (localhost:5173) となる。
    - トークン交換や JWKS 取得は Docker 内部ネットワーク経由の内部 URL を使用する。
    - ブラウザへのリダイレクトは KeyCloak 外部公開 URL を使用する。
    - レルム名は外部から受け取らない。AP は ``tenant_code`` をテナントレジストリで ACTIVE なテナントの
      レルムに解決し、CP は ``control-plane`` 固定とする (01 §7.2)。
    - クライアントシークレットは ``KC_CLIENT_SECRET_SEED`` から導出する (02 §3.3)。

エンドポイント一覧 (01 §10.2):
    GET  /api/auth/app/login?tenant_code=  AP の認可リクエストを開始する。
    GET  /api/auth/cp/login                CP の認可リクエストを開始する。
    GET  /api/auth/callback                コードをトークンに交換し、セッションを作成する (state からプレーン・レルムを復元)。
    GET  /api/auth/app/status              AP セッションの状態。
    GET  /api/auth/cp/status               CP セッションの状態。
    POST /api/auth/app/logout              AP セッションを削除し、KeyCloak のログアウト URL を返す (CSRF 対策必須)。
    POST /api/auth/cp/logout               CP セッションを削除し、KeyCloak のログアウト URL を返す (CSRF 対策必須)。

    status / logout は OpenAPI に載せる (応答の型と 401 / 403 の Problem Details)。login / callback は
    ブラウザをトップレベル遷移させるリダイレクトのため載せない。

フロントエンドへの遷移先 (:mod:`modules.auth.redirects`。01 §11.1):
    - ログイン成功: AP は ``/{tenant_code}/``、CP は ``/cp/``。
    - ログイン開始で利用できないテナント: ``/?error=tenant_unavailable`` (形式不正・未登録・ACTIVE でないを区別しない)。
    - コールバックの失敗: JSON を返さず、AP は ``/{tenant_code}/login?error=<code>``、CP は ``/cp/login?error=<code>``、
      state からプレーン・テナントが分からなければ ``/?error=<code>`` へ 302。``code`` は
      :class:`~modules.auth.redirects.LoginErrorCode`。理由の詳細はログにだけ残す。
    - ログアウト後: AP は ``/{tenant_code}/login``、CP は ``/cp/login`` (応答本文の ``logout_url`` の行き先)。

関連環境変数:
    KEYCLOAK_URL: コンテナ内部からアクセスする KeyCloak URL。デフォルト ``http://keycloak_c:8080``。
    KEYCLOAK_EXTERNAL_URL: ブラウザからアクセスする KeyCloak 公開 URL。デフォルト ``http://localhost:8080``。
    KEYCLOAK_HTTP_RELATIVE_PATH: KeyCloak のコンテキストパス。デフォルト ``keycloak``。
    KEYCLOAK_CLIENT_ID: AP の OIDC クライアント ID。デフォルト ``fastapi-app``。
    KEYCLOAK_CP_CLIENT_ID: CP の OIDC クライアント ID。デフォルト ``fastapi-cp``。
    KC_CLIENT_SECRET_SEED: クライアントシークレット導出用のシード。
    APP_CALLBACK_URL: KeyCloak からのリダイレクト先 URL。デフォルト ``http://localhost:5173/api/auth/callback``。
    FRONTEND_URL: ログイン/ログアウト後のリダイレクト先ベース URL。デフォルト ``http://localhost:5173``。
    CSRF_TRUSTED_ORIGINS: ``FRONTEND_URL`` 以外に変更系リクエストを許可するオリジン (カンマ区切り)。
"""
import logging
import re
import secrets
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
import redis.exceptions
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import OperationalError

from main_app.route.auth.login_sync import sync_app_user_on_login
from main_app.route.auth.schemas import AppAuthStatus, AuthUser, CpAuthStatus, LogoutResult
from main_app.services.errors import UserDeactivatedError
from modules.auth.csrf import require_csrf_protection
from modules.auth.dependency import get_current_app_session, get_current_cp_session
from modules.auth.environment import KeyCloakEnvironmentVariables, validate_realm_name
from modules.auth.login import build_login_session
from modules.auth.plane import CP_REALM_NAME, SESSION_COOKIE_NAMES, Plane, is_valid_tenant_code
from modules.auth.redirects import LoginErrorCode, login_error_path
from modules.auth.session import (
    clear_session_cookie,
    create_session,
    delete_session,
    get_session,
    pop_auth_state,
    save_auth_state,
    set_session_cookie,
    unsign_session_id,
)
from modules.auth.token import CODE_CHALLENGE_METHOD, generate_nonce, generate_pkce_pair
from modules.errors.catalog import resolve_http_exception_code
from modules.errors.openapi import problem_responses
from modules.tenancy.providers import get_tenant_registry
from modules.tenancy.registry import TenantRecord, TenantRegistry, is_active

logger = logging.getLogger(__name__)

router = APIRouter()

# KeyCloak 設定のグローバルインスタンス
_config = KeyCloakEnvironmentVariables()

# ログインを開始できないテナント (形式不正・未登録・ACTIVE でない) の遷移先のエラーコード。
# 理由を区別せず同じ応答にし、テナントの存在を明かさない。
TENANT_UNAVAILABLE_ERROR = LoginErrorCode.TENANT_UNAVAILABLE.value

# 認証サーバーがコールバックに付ける ``error`` (RFC 6749 §4.1.2.1) をログに残すときに許す形式。
# 外部から自由に付けられる値のため、形式に合わないものはログにも出さない (ログの改ざん防止)。
_OAUTH_ERROR_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")


class LoginFailedError(Exception):
    """コールバックの失敗。フロントエンドのログイン画面へ ``?error=<code>`` を付けて戻す。

    Args:
        code: フロントエンドへ渡すエラーコード。
        reason: ログにだけ残す理由 (トークン・シークレットを含めない)。
    """

    def __init__(self, code: LoginErrorCode, reason: str) -> None:
        """エラーコードと理由を保持する。"""
        super().__init__(reason)
        self.code = code
        self.reason = reason


# ------------------------------------------------------------------ 共通処理


def _start_authorization(plane: Plane, realm: str, extra_state: dict[str, Any] | None = None) -> RedirectResponse:
    """認可リクエストを開始し、KeyCloak の認可エンドポイントへリダイレクトする。

    CSRF 対策のためにランダムな state を生成し、プレーン・レルム・PKCE の ``code_verifier``・
    ``nonce`` とともに Redis に一時保存する (TTL 300 秒)。``code_verifier`` と ``nonce`` は
    ブラウザに渡さない (``nonce`` は認可リクエストに含まれるが、照合はサーバー側で行う)。

    Args:
        plane: ログイン先のプレーン。
        realm: ログイン先のレルム (サーバー側で決めた値)。
        extra_state: state に追加で保存する値 (AP の ``tenant_code`` など)。

    Returns:
        RedirectResponse(302): KeyCloak 認可エンドポイントへのリダイレクト。
    """
    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = generate_pkce_pair()
    nonce = generate_nonce()
    save_auth_state(state, {**(extra_state or {}), "plane": plane.value, "realm": realm, "code_verifier": code_verifier, "nonce": nonce})

    auth_url = _config.build_realm_endpoint(_config.kc_external_base, realm, "auth")
    query = urlencode(
        {
            "client_id": _config.client_id_for(plane),
            "response_type": "code",
            "scope": "openid profile email",
            "redirect_uri": _config.callback_url,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": CODE_CHALLENGE_METHOD,
        }
    )
    return RedirectResponse(url=f"{auth_url}?{query}", status_code=302)


def _tenant_unavailable_response() -> RedirectResponse:
    """ログインを開始できないテナントの応答 (理由を区別しない)。

    Returns:
        RedirectResponse(302): ランディング (``/?error=tenant_unavailable``) へのリダイレクト。
    """
    return RedirectResponse(url=_config.frontend_redirect_url(login_error_path(LoginErrorCode.TENANT_UNAVAILABLE)), status_code=302)


def _login_failure_response(code: LoginErrorCode, plane: Plane | None, tenant_code: str | None) -> RedirectResponse:
    """コールバックの失敗時に、フロントエンドのログイン画面へ戻す応答。

    Args:
        code: エラーコード。
        plane: state から復元したプレーン (不明なら ``None``)。
        tenant_code: state から復元した AP のテナントコード。

    Returns:
        RedirectResponse(302): ``/{tenant_code}/login?error=`` / ``/cp/login?error=`` / ``/?error=`` へのリダイレクト。
    """
    return RedirectResponse(url=_config.frontend_redirect_url(login_error_path(code, plane, tenant_code)), status_code=302)


def _code_for_http_exception(exc: HTTPException) -> LoginErrorCode:
    """ログイン処理が送出した ``HTTPException`` を、遷移先へ渡すエラーコードにする。

    ``detail`` は Problem Details と同じ対応表 (``modules.errors.catalog``) でコードにする。
    ログイン画面で扱わないコードになった場合は、5xx は ``internal_error``、それ以外は ``login_rejected`` に寄せる。

    Args:
        exc: 例外。

    Returns:
        LoginErrorCode: エラーコード。
    """
    try:
        return LoginErrorCode(resolve_http_exception_code(exc.status_code, exc.detail))
    except ValueError:
        return LoginErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else LoginErrorCode.LOGIN_REJECTED


def _safe_oauth_error(error: str | None) -> str | None:
    """コールバックの ``error`` を、ログに残せる形式なら返す。"""
    if error and _OAUTH_ERROR_PATTERN.fullmatch(error):
        return error
    return None if not error else "(invalid)"


def _discard_session(plane: Plane, signed_session_id: str | None) -> dict[str, Any]:
    """Cookie が指すセッションを Redis から削除し、削除前の内容を返す。

    Args:
        plane: プレーン。
        signed_session_id: Cookie の値。

    Returns:
        dict: 削除前のセッションデータ。無い場合は空の dict。
    """
    if not signed_session_id:
        return {}
    session_id = unsign_session_id(plane, signed_session_id)
    if not session_id:
        return {}
    session_data = get_session(plane, session_id) or {}
    delete_session(plane, session_id)
    return session_data


def _session_cookie(request: Request, plane: Plane) -> str | None:
    """リクエストからプレーンのセッション Cookie の値を読む。"""
    return request.cookies.get(SESSION_COOKIE_NAMES[plane])


def _auth_user(session_data: dict[str, Any]) -> AuthUser:
    """セッションのユーザー情報から、フロントに返す項目だけを取り出す。

    レルム名・クライアント ID・tenant_id はフロントに返さない (01 §10.2)。

    Args:
        session_data: セッションデータ。

    Returns:
        AuthUser: ユーザー。
    """
    user = session_data.get("user") or {}
    return AuthUser(sub=user.get("sub"), preferred_username=user.get("preferred_username"), email=user.get("email"), roles=list(user.get("roles") or []))


def _build_end_session_url(plane: Plane, session_data: dict[str, Any]) -> str:
    """KeyCloak の RP-Initiated Logout (end session) URL を構築する。

    **外部公開 URL** を使う点が重要である。KeyCloak はトークンの ``iss`` と
    アクセスされた URL の一致を検証するため、内部 URL (``keycloak_c:8080``) に
    ログアウトを要求すると ``invalid_grant: Invalid token issuer`` で拒否される。
    ブラウザは外部 URL に到達できるので、フロントチャネルで遷移させる。

    セッションが無い (またはレルムが分からない) 場合は、フロントエンドの遷移先をそのまま返す。

    Args:
        plane: プレーン。
        session_data: 削除前のセッションデータ。

    Returns:
        str: ブラウザを遷移させるべき URL。
    """
    post_logout_url = _config.post_logout_url(plane, session_data.get("tenant_code"))
    realm = session_data.get("realm")
    if not realm:
        return post_logout_url

    logout_url = _config.build_realm_endpoint(_config.kc_external_base, realm, "logout")
    params = {"client_id": _config.client_id_for(plane), "post_logout_redirect_uri": post_logout_url}
    id_token = (session_data.get("tokens") or {}).get("id_token")
    if id_token:
        # id_token_hint を渡すとログアウト確認画面を省略できる
        params["id_token_hint"] = id_token
    return f"{logout_url}?{urlencode(params)}"


def _logout(plane: Plane, request: Request, response: Response) -> LogoutResult:
    """プレーンのローカルセッションを破棄し、KeyCloak のログアウト URL を返す。

    Args:
        plane: プレーン。
        request: リクエスト (プレーンのセッション Cookie を読む)。
        response: レスポンス (プレーンのセッション Cookie を削除する)。

    Returns:
        LogoutResult: ``{"logout_url": "<遷移先URL>"}``。
    """
    session_data = _discard_session(plane, _session_cookie(request, plane))
    clear_session_cookie(response, plane, secure=_config.cookie_secure())
    return LogoutResult(logout_url=_build_end_session_url(plane, session_data))


# ------------------------------------------------------------- ログイン開始


@router.get("/app/login", include_in_schema=False)
def app_login(tenant_code: str = Query(default=""), registry: TenantRegistry = Depends(get_tenant_registry)):
    """AP (テナント) の KeyCloak 認可画面にリダイレクトする。

    ``tenant_code`` をテナントレジストリで **ACTIVE なテナントのレルム** に解決してからリダイレクトする。
    レルム名は受け取らない (管理レルムや CP のレルムへのログイン開始を防ぐ)。

    形式不正・未登録・ACTIVE でないテナントは区別せず、ランディング
    (``/?error=tenant_unavailable``) へリダイレクトする (テナントの存在を明かさない)。

    Args:
        tenant_code: テナントコード (大文字は小文字に正規化する)。
        registry: テナントレジストリ。

    Returns:
        RedirectResponse(302): KeyCloak 認可エンドポイント、またはランディングへのリダイレクト。
    """
    code = (tenant_code or "").strip().lower()
    if not is_valid_tenant_code(code):
        return _tenant_unavailable_response()

    record = registry.get_by_code(code)
    if not is_active(record):
        return _tenant_unavailable_response()

    try:
        realm = validate_realm_name(record.realm_name)
    except ValueError:
        logger.error("tenant registry has an invalid realm name (tenant_code=%s)", code)
        return _tenant_unavailable_response()

    return _start_authorization(Plane.APP, realm, {"tenant_code": record.tenant_code})


@router.get("/cp/login", include_in_schema=False)
def cp_login():
    """CP (SaaS 管理者) の KeyCloak 認可画面 (レルム ``control-plane``) にリダイレクトする。

    Returns:
        RedirectResponse(302): KeyCloak 認可エンドポイントへのリダイレクト。
    """
    return _start_authorization(Plane.CP, CP_REALM_NAME)


# ------------------------------------------------------------ コールバック


def _plane_of(state_payload: dict[str, Any]) -> Plane:
    """state のプレーンを取り出す。

    Raises:
        LoginFailedError: 未知のプレーンの場合 (``invalid_auth_state``)。
    """
    try:
        return Plane(state_payload.get("plane"))
    except ValueError as exc:
        raise LoginFailedError(LoginErrorCode.INVALID_AUTH_STATE, "unknown plane in state") from exc


def _exchange_code(plane: Plane, realm: str, code: str, code_verifier: str) -> dict[str, Any]:
    """認可コードをトークンに交換する (コンテナ内部 URL 経由)。

    Args:
        plane: プレーン。
        realm: レルム。
        code: 認可コード。
        code_verifier: PKCE の ``code_verifier``。

    Returns:
        dict: トークンエンドポイントのレスポンス。

    Raises:
        LoginFailedError: 認証サーバーに到達できない (``identity_provider_unreachable``)、
            または交換に失敗した (``token_exchange_failed``) 場合。
    """
    token_url = _config.build_realm_endpoint(_config.kc_internal_base, realm, "token")
    token_payload = {
        "grant_type": "authorization_code",
        "client_id": _config.client_id_for(plane),
        "client_secret": _config.client_secret_for(plane, realm),
        "code": code,
        "redirect_uri": _config.callback_url,
        # PKCE: 認可リクエスト時に生成した code_verifier を提示する
        "code_verifier": code_verifier,
    }
    try:
        token_response = httpx.post(token_url, data=token_payload, timeout=10.0)
    except httpx.HTTPError as exc:
        raise LoginFailedError(LoginErrorCode.IDENTITY_PROVIDER_UNREACHABLE, f"token endpoint unreachable ({type(exc).__name__})") from exc
    if token_response.status_code != 200:
        raise LoginFailedError(LoginErrorCode.TOKEN_EXCHANGE_FAILED, f"token endpoint returned status {token_response.status_code}")
    try:
        token_data = token_response.json()
    except ValueError as exc:
        raise LoginFailedError(LoginErrorCode.TOKEN_EXCHANGE_FAILED, "token endpoint returned a non-JSON body") from exc
    if not isinstance(token_data, dict):
        raise LoginFailedError(LoginErrorCode.TOKEN_EXCHANGE_FAILED, "token endpoint returned a non-object body")
    return token_data


def _complete_login(request: Request, plane: Plane, state_payload: dict[str, Any], code: str | None, error: str | None, registry: TenantRegistry) -> RedirectResponse:
    """state を取り出した後のコールバック処理 (発行元の確認・トークン交換・検証・セッション作成)。

    Args:
        request: リクエスト (同じプレーンの既存セッション Cookie を読む)。
        plane: state のプレーン。
        state_payload: state に保存した内容。
        code: 認可コード。
        error: 認証サーバーが付けた ``error`` (ログ用)。
        registry: テナントレジストリ。

    Returns:
        RedirectResponse(302): ログイン後の画面へのリダイレクト。プレーンのセッション Cookie が付与される。

    Raises:
        LoginFailedError: 失敗した場合。
        HTTPException: トークンの検証に失敗した場合 (:func:`~modules.auth.login.build_login_session`)。
    """
    try:
        realm = validate_realm_name(state_payload.get("realm") or "")
    except ValueError as exc:
        raise LoginFailedError(LoginErrorCode.INVALID_AUTH_STATE, "invalid realm in state") from exc

    if not code:
        raise LoginFailedError(LoginErrorCode.AUTHORIZATION_FAILED, f"no authorization code (error={_safe_oauth_error(error)})")

    tenant_code: str | None = None
    expected_tenant_id: str | None = None
    app_record: TenantRecord | None = None
    if plane == Plane.APP:
        app_record = registry.get_by_realm(realm)
        if not is_active(app_record) or app_record.tenant_code != state_payload.get("tenant_code"):
            raise LoginFailedError(LoginErrorCode.TENANT_UNAVAILABLE, f"tenant of realm {realm} is not active or does not match the state")
        tenant_code = app_record.tenant_code
        expected_tenant_id = str(app_record.tenant_id)
    elif realm != CP_REALM_NAME:
        raise LoginFailedError(LoginErrorCode.LOGIN_REJECTED, f"cp state with realm {realm}")

    token_data = _exchange_code(plane, realm, code, state_payload.get("code_verifier") or "")
    session_data = build_login_session(
        _config,
        plane,
        realm,
        token_data,
        expected_nonce=state_payload.get("nonce"),
        tenant_code=tenant_code,
        expected_tenant_id=expected_tenant_id,
    )

    if app_record is not None:
        # AP のユーザー行の同期 (PF-USR-04 / 05)。セッションを作る前に行い、無効化されたユーザーにはセッションを作らない。
        try:
            sync_app_user_on_login(session_data, tenant_id=app_record.tenant_id, tenant_code=app_record.tenant_code)
        except UserDeactivatedError as exc:
            raise LoginFailedError(LoginErrorCode.LOGIN_REJECTED, f"user is deactivated (tenant_code={app_record.tenant_code} user_id={exc.user_id})") from exc

    # 同じプレーンの既存セッションを破棄してから新しいセッションを発行する
    _discard_session(plane, _session_cookie(request, plane))
    session_id = create_session(plane, session_data)

    response = RedirectResponse(url=_config.post_login_url(plane, tenant_code), status_code=302)
    set_session_cookie(response, plane, session_id, secure=_config.cookie_secure())
    return response


@router.get("/callback", include_in_schema=False)
def callback(
    request: Request,
    state: str = Query(default=""),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    registry: TenantRegistry = Depends(get_tenant_registry),
) -> RedirectResponse:
    """KeyCloak から返った認可コードをトークンに交換し、プレーンのセッションを確立する。

    次のステップで認証を完了する:

    1. **state 検証**: Redis から state に紐づくペイロードを取得・削除し (1 回限り)、
       プレーン・レルム・PKCE の ``code_verifier``・``nonce`` を取り出す。
    2. **発行元の確認**: AP はレジストリでレルムが ACTIVE なテナントのものであることを再確認する
       (ログイン開始からの間に停止された場合に備える)。CP はレルムが ``control-plane`` であること。
    3. **トークン交換**: コンテナ内部 URL 経由で、認可コードと ``code_verifier`` をトークンに交換する。
       クライアントシークレットはプレーンとレルムから導出する。
    4. **トークン検証**: :func:`~modules.auth.login.build_login_session` (id_token / access token の署名・
       クレーム、AP は ``tenant_id`` クレームとレジストリの一致、CP はロール)。
    5. **ユーザー同期 (AP のみ)**: :func:`~main_app.route.auth.login_sync.sync_app_user_on_login` で、テナントの
       コンテキストで AP のユーザー行を作成・同期し ``last_login_at`` を更新する (デフォルト組織の作成を含む。
       01 PF-USR-04 / 05)。無効化されたユーザーはセッションを作らずに拒否する。CP では行わない。
    6. **セッション作成**: プレーンのキー空間に保存し、プレーンの Cookie を設定する。
       同じプレーンの既存セッションは破棄する (AP はブラウザあたり 1 テナント)。

    失敗時は JSON を返さず、フロントエンドのログイン画面へ ``?error=<code>`` を付けて 302 する
    (:func:`~modules.auth.redirects.login_error_path`)。理由の詳細はログにだけ残す。

    ============================================ ===================================
    失敗                                         ``error``
    ============================================ ===================================
    state が無い・期限切れ・使用済み・内容が不正 ``invalid_auth_state``
    認可コードが無い (キャンセル・認証サーバー)  ``authorization_failed``
    テナントが ACTIVE でない・レルムと食い違う   ``tenant_unavailable``
    認証サーバーに到達できない                   ``identity_provider_unreachable``
    トークン交換の失敗                           ``token_exchange_failed``
    トークンが欠けている・検証の失敗             ``invalid_token``
    tenant_id の不一致・CP のロール不足 等       ``login_rejected``
    AP で無効化されたユーザー                    ``login_rejected``
    セッションストア・DB に接続できない          ``service_unavailable``
    想定外のエラー                               ``internal_error``
    ============================================ ===================================

    Args:
        request: リクエスト。
        state: 認可リクエスト時の state。
        code: 認可コード。KeyCloak がエラーを返した場合は無い。
        error: KeyCloak が返したエラー (ログにだけ残す)。
        registry: テナントレジストリ。

    Returns:
        RedirectResponse(302): 成功時はログイン後の画面 (プレーンのセッション Cookie 付き)、
            失敗時はログイン画面 (``?error=<code>``) へのリダイレクト。
    """
    plane: Plane | None = None
    tenant_code: str | None = None
    try:
        # state は認可コードの有無にかかわらず消費する (再利用させない)
        state_payload = pop_auth_state(state) if state else None
        if not state_payload:
            raise LoginFailedError(LoginErrorCode.INVALID_AUTH_STATE, "state not found, expired or already used")
        plane = _plane_of(state_payload)
        if plane == Plane.APP:
            tenant_code = state_payload.get("tenant_code")
        return _complete_login(request, plane, state_payload, code, error, registry)
    except LoginFailedError as exc:
        failure_code = exc.code
        logger.warning("login callback failed (error=%s plane=%s): %s", failure_code.value, plane, exc.reason)
    except HTTPException as exc:
        failure_code = _code_for_http_exception(exc)
        logger.warning("login callback failed (error=%s plane=%s status=%s detail=%s)", failure_code.value, plane, exc.status_code, exc.detail)
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError, OperationalError) as exc:
        failure_code = LoginErrorCode.SERVICE_UNAVAILABLE
        logger.error("login callback failed (error=%s plane=%s): %s", failure_code.value, plane, type(exc).__name__, exc_info=exc)
    except Exception as exc:
        failure_code = LoginErrorCode.INTERNAL_ERROR
        logger.error("login callback failed (error=%s plane=%s): unexpected %s", failure_code.value, plane, type(exc).__name__, exc_info=exc)
    return _login_failure_response(failure_code, plane, tenant_code)


# ------------------------------------------------------------------ 状態


@router.get("/app/status", summary="AP のセッションの状態", responses=problem_responses(401, 503))
def app_status(session_data: Annotated[dict[str, Any], Depends(get_current_app_session)]) -> AppAuthStatus:
    """AP のセッション(Cookie `rf_sid_app`)を検証し、ログイン中のテナントコードとユーザーを返す。

    アクセストークンの期限が切れていればサーバー側で更新する。認証領域名・クライアント ID・テナント ID は返さない。
    セッションが無い・無効・期限切れ、または CP のセッションしか無い場合は 401。
    フロントのルートガードは `tenant_code` を URL のテナントコードと照合する。
    """
    return AppAuthStatus(authenticated=True, plane="app", tenant_code=session_data.get("tenant_code"), user=_auth_user(session_data))


@router.get("/cp/status", summary="CP のセッションの状態", responses=problem_responses(401, 503))
def cp_status(session_data: Annotated[dict[str, Any], Depends(get_current_cp_session)]) -> CpAuthStatus:
    """CP のセッション(Cookie `rf_sid_cp`)を検証し、ログイン中のユーザーを返す。

    アクセストークンの期限が切れていればサーバー側で更新する。認証領域名・クライアント ID は返さない。
    セッションが無い・無効・期限切れ、または AP のセッションしか無い場合は 401。
    """
    return CpAuthStatus(authenticated=True, plane="cp", user=_auth_user(session_data))


# -------------------------------------------------------------- ログアウト


@router.post("/app/logout", summary="AP からログアウト", dependencies=[Depends(require_csrf_protection)], responses=problem_responses(403, 503))
def app_logout(request: Request, response: Response) -> LogoutResult:
    """AP のセッションを破棄して Cookie `rf_sid_app` を削除し、ブラウザを遷移させる URL を返す。

    認証基盤のセッション終了はフロントチャネル(RP-Initiated Logout)で行うため、
    呼び出し側は `logout_url` へトップレベル遷移する(`window.location.href`)。完了後は `/{tenant_code}/login` に戻る。
    CP のセッションには影響しない。セッションが無くても 200(何度呼んでもよい)。

    状態を変える操作のため `X-Requested-With: rf-stack` と許可されたオリジンの `Origin` が必須(無ければ 403)。
    """
    return _logout(Plane.APP, request, response)


@router.post("/cp/logout", summary="CP からログアウト", dependencies=[Depends(require_csrf_protection)], responses=problem_responses(403, 503))
def cp_logout(request: Request, response: Response) -> LogoutResult:
    """CP のセッションを破棄して Cookie `rf_sid_cp` を削除し、ブラウザを遷移させる URL を返す。

    呼び出し側は `logout_url` へトップレベル遷移する。完了後は `/cp/login` に戻る。
    AP のセッションには影響しない。セッションが無くても 200(何度呼んでもよい)。

    状態を変える操作のため `X-Requested-With: rf-stack` と許可されたオリジンの `Origin` が必須(無ければ 403)。
    """
    return _logout(Plane.CP, request, response)
