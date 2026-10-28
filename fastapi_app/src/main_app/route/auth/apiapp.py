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
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

from modules.auth.csrf import require_csrf_protection
from modules.auth.dependency import get_current_app_session, get_current_cp_session
from modules.auth.environment import KeyCloakEnvironmentVariables, validate_realm_name
from modules.auth.login import LOGIN_REJECTED_DETAIL, build_login_session
from modules.auth.plane import CP_REALM_NAME, Plane, is_valid_tenant_code
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
from modules.tenancy.providers import get_tenant_registry
from modules.tenancy.registry import TenantRegistry, is_active

logger = logging.getLogger(__name__)

router = APIRouter()

# KeyCloak 設定のグローバルインスタンス
_config = KeyCloakEnvironmentVariables()

# ログインを開始できないテナント (形式不正・未登録・ACTIVE でない) の遷移先のエラーコード。
# 理由を区別せず同じ応答にし、テナントの存在を明かさない。
TENANT_UNAVAILABLE_ERROR = "tenant_unavailable"


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
        RedirectResponse(302): フロントエンドのログイン画面 (``?error=tenant_unavailable``) へのリダイレクト。
    """
    return RedirectResponse(url=f"{_config.frontend_url}/login?{urlencode({'error': TENANT_UNAVAILABLE_ERROR})}", status_code=302)


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


def _status_payload(plane: Plane, session_data: dict[str, Any]) -> dict[str, Any]:
    """認証状態 API のレスポンスを組み立てる。

    レルム名・クライアント ID・tenant_id はフロントに返さない (01 §10.2)。
    AP はルートガードで URL のテナントコードと照合するため ``tenant_code`` を返す。

    Args:
        plane: プレーン。
        session_data: セッションデータ。

    Returns:
        dict: ``{"authenticated": True, "plane": ..., "user": {...}}`` (AP は ``tenant_code`` も)。
    """
    user = session_data.get("user") or {}
    payload: dict[str, Any] = {
        "authenticated": True,
        "plane": plane.value,
        "user": {
            "sub": user.get("sub"),
            "preferred_username": user.get("preferred_username"),
            "email": user.get("email"),
            "roles": list(user.get("roles") or []),
        },
    }
    if plane == Plane.APP:
        payload["tenant_code"] = session_data.get("tenant_code")
    return payload


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


def _logout(plane: Plane, signed_session_id: str | None) -> JSONResponse:
    """プレーンのローカルセッションを破棄し、KeyCloak のログアウト URL を返す。

    Args:
        plane: プレーン。
        signed_session_id: Cookie の値。

    Returns:
        JSONResponse(200): ``{"logout_url": "<遷移先URL>"}``。プレーンの Cookie を削除する。
    """
    session_data = _discard_session(plane, signed_session_id)
    response = JSONResponse(content={"logout_url": _build_end_session_url(plane, session_data)})
    clear_session_cookie(response, plane, secure=_config.cookie_secure())
    return response


# ------------------------------------------------------------- ログイン開始


@router.get("/app/login", include_in_schema=False)
def app_login(tenant_code: str = Query(default=""), registry: TenantRegistry = Depends(get_tenant_registry)):
    """AP (テナント) の KeyCloak 認可画面にリダイレクトする。

    ``tenant_code`` をテナントレジストリで **ACTIVE なテナントのレルム** に解決してからリダイレクトする。
    レルム名は受け取らない (管理レルムや CP のレルムへのログイン開始を防ぐ)。

    形式不正・未登録・ACTIVE でないテナントは区別せず、フロントエンドのログイン画面
    (``/login?error=tenant_unavailable``) へリダイレクトする (テナントの存在を明かさない)。

    Args:
        tenant_code: テナントコード (大文字は小文字に正規化する)。
        registry: テナントレジストリ。

    Returns:
        RedirectResponse(302): KeyCloak 認可エンドポイント、またはフロントエンドのログイン画面へのリダイレクト。
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


@router.get("/callback", include_in_schema=False)
def callback(
    state: str = Query(default=""),
    code: str | None = Query(default=None),
    registry: TenantRegistry = Depends(get_tenant_registry),
    rf_sid_app: str | None = Cookie(default=None),
    rf_sid_cp: str | None = Cookie(default=None),
):
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
    5. **セッション作成**: プレーンのキー空間に保存し、プレーンの Cookie を設定する。
       同じプレーンの既存セッションは破棄する (AP はブラウザあたり 1 テナント)。

    Args:
        state: 認可リクエスト時の state。
        code: 認可コード。KeyCloak がエラーを返した場合は無い。
        registry: テナントレジストリ。
        rf_sid_app: 既存の AP セッション Cookie。
        rf_sid_cp: 既存の CP セッション Cookie。

    Returns:
        RedirectResponse(302): フロントエンドへのリダイレクト。プレーンのセッション Cookie が付与される。

    Raises:
        HTTPException(400): state が不正・期限切れ、または認可コードが無い場合。
        HTTPException(401): トークン交換・検証に失敗した場合。
        HTTPException(403): テナントが利用できない、``tenant_id`` の不一致、CP のロール不足の場合。
    """
    # state は認可コードの有無にかかわらず消費する (再利用させない)
    state_payload = pop_auth_state(state) if state else None
    if not state_payload:
        raise HTTPException(status_code=400, detail="Invalid state")

    try:
        plane = Plane(state_payload.get("plane"))
        realm = validate_realm_name(state_payload.get("realm") or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid state") from exc

    if not code:
        raise HTTPException(status_code=400, detail="Authorization failed")

    tenant_code: str | None = None
    expected_tenant_id: str | None = None
    if plane == Plane.APP:
        record = registry.get_by_realm(realm)
        if not is_active(record) or record.tenant_code != state_payload.get("tenant_code"):
            raise HTTPException(status_code=403, detail=LOGIN_REJECTED_DETAIL)
        tenant_code = record.tenant_code
        expected_tenant_id = str(record.tenant_id)
    elif realm != CP_REALM_NAME:
        raise HTTPException(status_code=403, detail=LOGIN_REJECTED_DETAIL)

    token_url = _config.build_realm_endpoint(_config.kc_internal_base, realm, "token")
    token_payload = {
        "grant_type": "authorization_code",
        "client_id": _config.client_id_for(plane),
        "client_secret": _config.client_secret_for(plane, realm),
        "code": code,
        "redirect_uri": _config.callback_url,
        # PKCE: 認可リクエスト時に生成した code_verifier を提示する
        "code_verifier": state_payload.get("code_verifier") or "",
    }
    try:
        token_response = httpx.post(token_url, data=token_payload, timeout=10.0)
    except httpx.HTTPError as exc:
        logger.warning("token exchange failed to reach KeyCloak (plane=%s realm=%s): %s", plane.value, realm, type(exc).__name__)
        raise HTTPException(status_code=502, detail="Failed to reach KeyCloak") from exc
    if token_response.status_code != 200:
        logger.warning("token exchange failed (plane=%s realm=%s status=%s)", plane.value, realm, token_response.status_code)
        raise HTTPException(status_code=401, detail="Token exchange failed")

    session_data = build_login_session(
        _config,
        plane,
        realm,
        token_response.json(),
        expected_nonce=state_payload.get("nonce"),
        tenant_code=tenant_code,
        expected_tenant_id=expected_tenant_id,
    )

    # 同じプレーンの既存セッションを破棄してから新しいセッションを発行する
    _discard_session(plane, rf_sid_app if plane == Plane.APP else rf_sid_cp)
    session_id = create_session(plane, session_data)

    response = RedirectResponse(url=_config.post_login_url(plane), status_code=302)
    set_session_cookie(response, plane, session_id, secure=_config.cookie_secure())
    return response


# ------------------------------------------------------------------ 状態


@router.get("/app/status", include_in_schema=False)
def app_status(session_data: dict = Depends(get_current_app_session)):
    """AP セッションを検証し、認証状態とユーザー情報を返す。

    未認証時は依存関数が 401 を返す。

    Returns:
        dict: ``{"authenticated": True, "plane": "app", "tenant_code": ..., "user": {sub, preferred_username, email, roles}}``。
    """
    return _status_payload(Plane.APP, session_data)


@router.get("/cp/status", include_in_schema=False)
def cp_status(session_data: dict = Depends(get_current_cp_session)):
    """CP セッションを検証し、認証状態とユーザー情報を返す。

    未認証時は依存関数が 401 を返す。

    Returns:
        dict: ``{"authenticated": True, "plane": "cp", "user": {sub, preferred_username, email, roles}}``。
    """
    return _status_payload(Plane.CP, session_data)


# -------------------------------------------------------------- ログアウト


@router.post("/app/logout", include_in_schema=False, dependencies=[Depends(require_csrf_protection)])
def app_logout(rf_sid_app: str | None = Cookie(default=None)):
    """AP のローカルセッションを破棄し、KeyCloak のログアウト URL を返す。

    KeyCloak 側の SSO セッション終了は **フロントチャネル (RP-Initiated Logout)** で行う。
    遷移先 URL を JSON で返すので、呼び出し側 (SPA) が ``window.location.href`` でトップレベル遷移すること。
    ログアウト後は ``/{tenant_code}/login`` に戻る。CP のセッションには影響しない。

    変更系のため ``X-Requested-With: rf-stack`` と許可された ``Origin`` が必須 (無ければ 403)。

    Returns:
        JSONResponse(200): ``{"logout_url": "<遷移先URL>"}``。``rf_sid_app`` Cookie を削除する。
    """
    return _logout(Plane.APP, rf_sid_app)


@router.post("/cp/logout", include_in_schema=False, dependencies=[Depends(require_csrf_protection)])
def cp_logout(rf_sid_cp: str | None = Cookie(default=None)):
    """CP のローカルセッションを破棄し、KeyCloak のログアウト URL を返す。

    ログアウト後は ``/cp/login`` に戻る。AP のセッションには影響しない。
    変更系のため ``X-Requested-With: rf-stack`` と許可された ``Origin`` が必須 (無ければ 403)。

    Returns:
        JSONResponse(200): ``{"logout_url": "<遷移先URL>"}``。``rf_sid_cp`` Cookie を削除する。
    """
    return _logout(Plane.CP, rf_sid_cp)
