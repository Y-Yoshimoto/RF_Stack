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
    POST /api/auth/logout    セッションを削除し、ログアウトする。

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
import secrets
from base64 import urlsafe_b64decode
from json import loads
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import RedirectResponse

from modules.auth.session import (
    SESSION_COOKIE_NAME,
    create_session,
    delete_session,
    pop_auth_state,
    save_auth_state,
    sign_session_id,
    unsign_session_id,
)
from modules.auth.environment import KeyCloakEnvironmentVariables

router = APIRouter()

# KeyCloak 設定のグローバルインスタンス
_config = KeyCloakEnvironmentVariables()


def _decode_jwt_payload(token: str) -> dict:
    """JWT の payload 部分を署名検証なしでデコードする。

    id_token からユーザー情報を取得する目的専用。
    **トークンの真正性検証には使用しないこと。**
    (KeyCloak によるトークン発行の時点で真正性は保証済みである。)

    Args:
        token: JWT 文字列 (``header.payload.signature`` 形式)。

    Returns:
        dict: Base64URL デコードされた payload の dict。

    Raises:
        ValueError: JWT が 3 部分構成でない場合。
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")

    payload_segment = parts[1]
    padding = "=" * ((4 - len(payload_segment) % 4) % 4)
    payload_raw = urlsafe_b64decode(f"{payload_segment}{padding}".encode("utf-8"))
    return loads(payload_raw.decode("utf-8"))


def _extract_userinfo(token_data: dict, realm: str, access_token: str) -> dict:
    """トークンレスポンスからユーザー情報を取得する。

    ``id_token`` が利用可能な場合は JWT をデコードしてユーザー情報を取得する。
    ``id_token`` が存在しない場合や JWT の形式が不正な場合は、
    KeyCloak の userinfo エンドポイントにフォールバックする。

    この戦略により、KeyCloak の内部 URL / 外部 URL の issuer ミスマッチが
    発生した場合でも、``id_token`` があればログインを継続できる。

    Args:
        token_data: KeyCloak トークンエンドポイント (``/token``) のレスポンス dict。
        realm: リクエスト元の Realm 名。userinfo フォールバック時に使用する。
        access_token: userinfo フォールバック時に使用する Bearer トークン。

    Returns:
        dict: ``sub``, ``preferred_username``, ``email``, ``realm`` キーを持つ dict。

    Raises:
        HTTPException(401): userinfo エンドポイントが 200 以外を返した場合。
    """
    id_token = token_data.get("id_token")
    if id_token:
        try:
            id_payload = _decode_jwt_payload(id_token)
            return {
                "sub": id_payload.get("sub"),
                "preferred_username": id_payload.get("preferred_username"),
                "email": id_payload.get("email"),
                "realm": realm,
            }
        except Exception:
            # id_token の形式が異常な場合は userinfo へフォールバックする
            pass

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

    Args:
        realm: ログイン先の KeyCloak Realm 名。テナント識別子に該当する。

    Returns:
        RedirectResponse(302): KeyCloak 認可エンドポイントへのリダイレクト。

    Raises:
        HTTPException(400): ``realm`` クエリパラメータが空の場合。
    """
    realm_name = realm.strip()
    if not realm_name:
        raise HTTPException(status_code=400, detail="realm is required")

    state = secrets.token_urlsafe(24)
    save_auth_state(state, {"realm": realm_name})

    auth_url = _config.build_realm_endpoint(_config.kc_external_base, realm_name, "auth")
    query = urlencode(
        {
            "client_id": _config.client_id,
            "response_type": "code",
            "scope": "openid profile email",
            "redirect_uri": _config.callback_url,
            "state": state,
        }
    )
    return RedirectResponse(url=f"{auth_url}?{query}", status_code=302)


@router.get("/callback", include_in_schema=False)
def callback(code: str, state: str):
    """KeyCloak から返った認可コードをトークンに交換し、セッションを確立する。

    次のステップで認証を完了する:

    1. **state 検証**: Redis から state に紐づくペイロードを取得・削除し、CSRF を防ぐ。
    2. **トークン交換**: コンテナ内部 URL 経由で認可コードを access/refresh/id_token に交換する。
    3. **ユーザー情報取得**: ``id_token`` の JWT をデコードし、失敗時は userinfo エンドポイントにフォールバック。
    4. **セッション作成**: トークン・ユーザー情報を Redis に保存し、署名済み Cookie をクライアントに返す。
    5. **フロントエンドにリダイレクト**: ``FRONTEND_URL/button`` へ 302 リダイレクトする。

    Args:
        code: KeyCloak から返った認可コード。
        state: CSRF 検証用の state 文字列。

    Returns:
        RedirectResponse(302): ``FRONTEND_URL/button`` へのリダイレクト。
                               ``rf_sid`` HttpOnly Cookie が付与される。

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

    token_url = _config.build_realm_endpoint(_config.kc_internal_base, realm, "token")
    token_payload = {
        "grant_type": "authorization_code",
        "client_id": _config.client_id,
        "client_secret": _config.client_secret,
        "code": code,
        "redirect_uri": _config.callback_url,
    }

    token_response = httpx.post(token_url, data=token_payload, timeout=10.0)
    if token_response.status_code != 200:
        raise HTTPException(status_code=401, detail="Token exchange failed")

    token_data = token_response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    if not access_token or not refresh_token:
        raise HTTPException(status_code=401, detail="Invalid token response")

    user = _extract_userinfo(token_data, realm, access_token)
    session_id = create_session(
        {
            "realm": realm,
            "tokens": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": token_data.get("expires_in"),
                "refresh_expires_in": token_data.get("refresh_expires_in"),
            },
            "user": user,
        }
    )

    response = RedirectResponse(url=f"{_config.frontend_url}/button", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sign_session_id(session_id),
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/status", include_in_schema=False)
def auth_status(rf_sid: str | None = Cookie(default=None)):
    """セッション Cookie を検証し、認証状態とユーザー情報を返す。

    React がページロード時に呼び出し、ユーザーの認証状態を確認するために使用する。
    Vite proxy 経由で ``GET /api/auth/status`` として呼び出す。

    Args:
        rf_sid: Cookie から自動注入される署名済みセッション ID。

    Returns:
        dict: ``{"authenticated": True, "user": {...}}`` の形式。
              ``user`` には ``sub``, ``preferred_username``, ``email``, ``realm`` が含まれる。

    Raises:
        HTTPException(401): Cookie がない、署名不正、またはセッションが期限切れの場合。
    """
    if not rf_sid:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_id = unsign_session_id(rf_sid)
    if not session_id:
        raise HTTPException(status_code=401, detail="Invalid session")

    from modules.auth.session import get_session

    session_data = get_session(session_id)
    if not session_data:
        raise HTTPException(status_code=401, detail="Session expired")

    return {
        "authenticated": True,
        "user": session_data.get("user"),
    }


@router.post("/logout", include_in_schema=False)
def logout(rf_sid: str | None = Cookie(default=None)):
    """セッションを削除し、Cookie を無効化してログインページにリダイレクトする。

    セッション Cookie が存在する場合は、署名を検証して Redis からセッションを削除する。
    Cookie がない場合やセッションが存在しない場合でも、Cookie 削除およびリダイレクトは必ず実行する。

    Args:
        rf_sid: Cookie から自動注入される署名済みセッション ID。Cookie あ Cookie 無効化の対象となる。

    Returns:
        RedirectResponse(302): ``FRONTEND_URL/login`` へのリダイレクト。
                               レスポンスから ``rf_sid`` Cookie が削除される。
    """
    if rf_sid:
        session_id = unsign_session_id(rf_sid)
        if session_id:
            delete_session(session_id)

    response = RedirectResponse(url=f"{_config.frontend_url}/login", status_code=302)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return response
