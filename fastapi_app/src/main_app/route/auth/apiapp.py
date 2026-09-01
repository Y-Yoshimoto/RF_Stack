#!/usr/bin/env python
# coding:utf-8
"""KeyCloak と連携する OIDC Authorization Code Flow の認証エンドポイント群。

実装前提:
    - FastAPI が BFF (Backend-for-Frontend) として動作する。
    - React は Vite proxy 経由で ``/api/**`` を FastAPI に転送するため、
      ブラウザから見ると全ての通信は同一オリジン (localhost:5173) となる。
    - トークン交換や userinfo 取得は Docker 内部ネットワーク経由の内部 URL を使用する。
    - ブラウザへのリダイレクトは KeyCloak 外部公開 URL を使用する。

エンドポイント一覧:
    GET  /api/auth/login     認可リクエストを開始する。
    GET  /api/auth/callback  コードをトークンに交換し、セッションを作成する。
    GET  /api/auth/status    セッションを検証し、ユーザー情報を返す。
    POST /api/auth/logout    セッションを削除し、KeyCloak のログアウト URL を返す。

関連環境変数:
    KEYCLOAK_URL: コンテナ内部からアクセスする KeyCloak URL。
                  デフォルト ``http://keycloak_c:8080``。
    KEYCLOAK_EXTERNAL_URL: ブラウザからアクセスする KeyCloak 公開 URL。
                           デフォルト ``http://localhost:8080``。
    KEYCLOAK_HTTP_RELATIVE_PATH: KeyCloak のコンテキストパス。デフォルト ``keycloak``。
    KEYCLOAK_CLIENT_ID: OIDC クライアント ID。デフォルト ``fastapi-app``。
    KEYCLOAK_CLIENT_SECRET: OIDC クライアントシークレット。
    APP_CALLBACK_URL: KeyCloak からのリダイレクト先 URL。
                      デフォルト ``http://localhost:5173/api/auth/callback``。
    FRONTEND_URL: ログイン/ログアウト後のリダイレクト先ベース URL。
                  デフォルト ``http://localhost:5173``。
"""
import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from modules.auth.dependency import get_current_user
from modules.auth.environment import KeyCloakEnvironmentVariables, validate_realm_name
from modules.auth.session import (
    SESSION_COOKIE_NAME,
    create_session,
    delete_session,
    get_session,
    pop_auth_state,
    save_auth_state,
    sign_session_id,
    unsign_session_id,
)
from modules.auth.token import (
    CODE_CHALLENGE_METHOD,
    build_token_record,
    generate_nonce,
    generate_pkce_pair,
    verify_id_token,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# KeyCloak 設定のグローバルインスタンス
_config = KeyCloakEnvironmentVariables()


def _extract_userinfo(token_data: dict, realm: str, access_token: str, expected_nonce: str | None) -> dict:
    """トークンレスポンスからユーザー情報を取得する。

    ``id_token`` がある場合は **JWKS による署名検証** を行ったうえで
    クレームからユーザー情報を取得する。``id_token`` が無い場合に限り、
    KeyCloak の userinfo エンドポイントにフォールバックする。

    Note:
        以前は id_token を署名検証せずデコードしていたが、検証を行うよう変更した。
        検証に失敗した場合は userinfo にフォールバックせず 401 を返す。
        フォールバックしてしまうと検証を行う意味が失われるため。

    Args:
        token_data: KeyCloak トークンエンドポイント (``/token``) のレスポンス dict。
        realm: リクエスト元の Realm 名。
        access_token: userinfo フォールバック時に使用する Bearer トークン。
        expected_nonce: 認可リクエスト時に送信した nonce。id_token の検証に使用する。

    Returns:
        dict: ``sub``, ``preferred_username``, ``email``, ``realm`` キーを持つ dict。

    Raises:
        HTTPException(401): id_token の検証に失敗した場合、
                            または userinfo エンドポイントが 200 以外を返した場合。
    """
    id_token = token_data.get("id_token")
    if id_token:
        try:
            claims = verify_id_token(
                id_token,
                jwks_uri=_config.build_jwks_uri(realm),
                audience=_config.client_id,
                allowed_issuers=_config.allowed_issuers(realm),
                expected_nonce=expected_nonce,
            )
        except Exception as exc:
            # 検証失敗は認証失敗として扱う。userinfo へのフォールバックは行わない。
            logger.warning("id_token verification failed: %s", exc)
            raise HTTPException(status_code=401, detail="Invalid id_token") from exc

        return {
            "sub": claims.get("sub"),
            "preferred_username": claims.get("preferred_username"),
            "email": claims.get("email"),
            "realm": realm,
        }

    # id_token が発行されなかった場合のみ userinfo で補完する
    userinfo_url = _config.build_realm_endpoint(_config.kc_internal_base, realm, "userinfo")
    userinfo_response = httpx.get(
        userinfo_url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10.0,
    )
    if userinfo_response.status_code != 200:
        raise HTTPException(status_code=401, detail="Failed to fetch user info")

    userinfo = userinfo_response.json()
    return {
        "sub": userinfo.get("sub"),
        "preferred_username": userinfo.get("preferred_username"),
        "email": userinfo.get("email"),
        "realm": realm,
    }


@router.get("/login", include_in_schema=False)
def login(realm: str):
    """指定された Realm の KeyCloak 認可画面にリダイレクトする。

    CSRF 対策のためにランダムな state を生成し、Realm 名とともに Redis に一時保存する。
    ``scope=openid profile email`` を指定することで、``id_token`` および
    ``email``/``preferred_username`` クレームの発行を KeyCloak に要求する。

    PKCE (S256) と nonce を使用する。``code_verifier`` と ``nonce`` は
    state と同じ Redis エントリに保存し、コールバック時に取り出して検証する。

    Args:
        realm: ログイン先の KeyCloak Realm 名。テナント識別子に該当する。

    Returns:
        RedirectResponse(302): KeyCloak 認可エンドポイントへのリダイレクト。

    Raises:
        HTTPException(400): ``realm`` が未指定、または許可されない文字を含む場合。
    """
    try:
        realm_name = validate_realm_name(realm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state = secrets.token_urlsafe(24)
    code_verifier, code_challenge = generate_pkce_pair()
    nonce = generate_nonce()
    # code_verifier はサーバー側にのみ保持し、トークン交換時にだけ送信する
    save_auth_state(state, {"realm": realm_name, "code_verifier": code_verifier, "nonce": nonce})

    auth_url = _config.build_realm_endpoint(_config.kc_external_base, realm_name, "auth")
    query = urlencode(
        {
            "client_id": _config.client_id,
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


@router.get("/callback", include_in_schema=False)
def callback(code: str, state: str):
    """KeyCloak から返った認可コードをトークンに交換し、セッションを確立する。

    次のステップで認証を完了する:

    1. **state 検証**: Redis から state に紐づくペイロードを取得・削除し、CSRF を防ぐ。
       同時に PKCE の ``code_verifier`` と ``nonce`` を取り出す。
    2. **トークン交換**: コンテナ内部 URL 経由で、認可コードと ``code_verifier`` を
       access/refresh/id_token に交換する。
    3. **ユーザー情報取得**: ``id_token`` を JWKS で署名検証し、クレームからユーザー情報を取得する
       (``id_token`` が無い場合のみ userinfo エンドポイントにフォールバック)。
    4. **セッション作成**: トークン・ユーザー情報を Redis に保存し、署名済み Cookie をクライアントに返す。
    5. **フロントエンドにリダイレクト**: ``FRONTEND_URL/button`` へ 302 リダイレクトする。

    Args:
        code: KeyCloak から返った認可コード。
        state: CSRF 検証用の state 文字列。

    Returns:
        RedirectResponse(302): ``FRONTEND_URL/button`` へのリダイレクト。
                               ``rf_sid`` HttpOnly Cookie が付与される。
                               ``Secure`` 属性は ``APP_ENV`` から導出される。

    Raises:
        HTTPException(400): state が不正 / Redis に存在しない場合、または Realm 情報がない場合。
        HTTPException(401): トークン交換失敗、またはユーザー情報取得失敗の場合。
    """
    state_payload = pop_auth_state(state)
    if not state_payload:
        raise HTTPException(status_code=400, detail="Invalid state")

    realm = state_payload.get("realm")
    if not realm:
        raise HTTPException(status_code=400, detail="Invalid realm")

    code_verifier = state_payload.get("code_verifier")
    nonce = state_payload.get("nonce")

    token_url = _config.build_realm_endpoint(_config.kc_internal_base, realm, "token")
    token_payload = {
        "grant_type": "authorization_code",
        "client_id": _config.client_id,
        "client_secret": _config.client_secret,
        "code": code,
        "redirect_uri": _config.callback_url,
    }
    # PKCE: 認可リクエスト時に生成した code_verifier を提示する
    if code_verifier:
        token_payload["code_verifier"] = code_verifier

    token_response = httpx.post(token_url, data=token_payload, timeout=10.0)
    if token_response.status_code != 200:
        raise HTTPException(status_code=401, detail="Token exchange failed")

    token_data = token_response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    if not access_token or not refresh_token:
        raise HTTPException(status_code=401, detail="Invalid token response")

    user = _extract_userinfo(token_data, realm, access_token, nonce)
    session_id = create_session(
        {
            "realm": realm,
            # 有効期限を絶対時刻に正規化して保存する(後から期限切れを判定できるようにするため)
            "tokens": build_token_record(token_data),
            "user": user,
        }
    )

    response = RedirectResponse(url=f"{_config.frontend_url}/button", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sign_session_id(session_id),
        httponly=True,
        # 開発環境は http のため False、本番環境では True になる
        secure=_config.cookie_secure(),
        samesite="lax",
        path="/",
    )
    return response


@router.get("/status", include_in_schema=False)
def auth_status(user: dict = Depends(get_current_user)):
    """セッション Cookie を検証し、認証状態とユーザー情報を返す。

    React がページロード時に呼び出し、ユーザーの認証状態を確認するために使用する。
    Vite proxy 経由で ``GET /api/auth/status`` として呼び出す。

    Cookie の検証は :func:`~modules.auth.dependency.get_current_user` に委ねる。
    未認証時の 401 応答も同 Dependency が行うため、本関数は認証済みの場合のみ実行される。

    Args:
        user: Dependency が Cookie から解決した認証済みユーザー情報。

    Returns:
        dict: ``{"authenticated": True, "user": {...}}`` の形式。
              ``user`` には ``sub``, ``preferred_username``, ``email``, ``realm`` が含まれる。
    """
    return {
        "authenticated": True,
        "user": user,
    }


def _build_end_session_url(realm: str, id_token: str | None) -> str:
    """KeyCloak の RP-Initiated Logout (end session) URL を構築する。

    **外部公開 URL** を使う点が重要である。KeyCloak はトークンの ``iss`` と
    アクセスされた URL の一致を検証するため、内部 URL (``keycloak_c:8080``) に
    ログアウトを要求すると ``invalid_grant: Invalid token issuer`` で拒否される。
    ブラウザは外部 URL に到達できるので、フロントチャネルで遷移させる。

    Args:
        realm: セッションが属する Realm 名。
        id_token: セッションに保存されている id_token。
                  ``id_token_hint`` として渡すとログアウト確認画面を省略できる。

    Returns:
        str: ブラウザを遷移させるべき KeyCloak のログアウト URL。
    """
    logout_url = _config.build_realm_endpoint(_config.kc_external_base, realm, "logout")
    params = {
        "client_id": _config.client_id,
        "post_logout_redirect_uri": f"{_config.frontend_url}/login",
    }
    if id_token:
        params["id_token_hint"] = id_token
    return f"{logout_url}?{urlencode(params)}"


@router.post("/logout", include_in_schema=False)
def logout(rf_sid: str | None = Cookie(default=None)):
    """ローカルセッションを破棄し、KeyCloak のログアウト URL を返す。

    KeyCloak 側の SSO セッション終了は **フロントチャネル (RP-Initiated Logout)**
    で行う。本エンドポイントはリダイレクトを返さず、遷移先 URL を JSON で返すので、
    呼び出し側 (SPA) が ``window.location.href`` でトップレベル遷移すること。

    Note:
        バックチャネル (サーバーから KeyCloak へ refresh_token を POST) は
        本構成では使えない。ブラウザが外部 URL で認可するためトークンの ``iss`` が
        外部 URL になり、サーバーからの内部 URL 呼び出しでは issuer 検証に失敗する。

    処理順:

    1. Cookie の署名を検証してセッション ID を復元する。
    2. セッションから Realm と id_token を取り出し、ログアウト URL を組み立てる。
    3. Redis からローカルセッションを削除する。
    4. Cookie を無効化し、遷移先 URL を JSON で返す。

    セッションが無い場合でも Cookie 無効化は行い、フロントエンドのログインページを
    遷移先として返す。

    Args:
        rf_sid: Cookie から自動注入される署名済みセッション ID。

    Returns:
        JSONResponse(200): ``{"logout_url": "<遷移先URL>"}``。
                           レスポンスから ``rf_sid`` Cookie が削除される。
    """
    # セッションが無い場合の既定の遷移先
    logout_url = f"{_config.frontend_url}/login"

    if rf_sid:
        session_id = unsign_session_id(rf_sid)
        if session_id:
            session_data = get_session(session_id) or {}
            realm = session_data.get("realm")
            if realm:
                id_token = (session_data.get("tokens") or {}).get("id_token")
                logout_url = _build_end_session_url(realm, id_token)
            delete_session(session_id)

    response = JSONResponse(content={"logout_url": logout_url})
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return response
