#!/usr/bin/env python
# coding:utf-8
"""FastAPI Dependency として使用する認証検証モジュール。

各エンドポイントに ``Depends(get_current_user)`` を付与することで、
未認証リクエストを一元管理で弾くことができる。

認証フロー:
    1. HttpOnly Cookie ``rf_sid`` から署名済みセッション ID を取得。
    2. ``itsdangerous`` で HMAC 署名を検証し、元のセッション ID を復元。
    3. Redis からセッションデータを取得する。
    4. access token の有効期限を確認し、切れていれば refresh token で更新する。
    5. ``user`` フィールドを返却する。

トークンのライフサイクル:
    KeyCloak の access token は既定で数分と短く、セッション TTL (既定 1 時間) より
    先に切れる。セッションだけが生き残って中のトークンが使えない状態を避けるため、
    アクセスのたびに期限を確認し、必要なら更新してセッションに書き戻す。
    refresh token 自体が切れている場合はセッションを破棄して 401 とする。
"""
from fastapi import Cookie, HTTPException

from .environment import KeyCloakEnvironmentVariables
from .session import delete_session, get_session, unsign_session_id, update_session
from .token import is_access_token_expired, is_refresh_token_expired, refresh_access_token

# KeyCloak 設定のグローバルインスタンス
_config = KeyCloakEnvironmentVariables()


def _refresh_session_tokens(session_id: str, session_data: dict) -> dict | None:
    """セッション内のトークンを更新して保存し直す。

    Args:
        session_id: 対象のセッション ID (署名なし)。
        session_data: 現在のセッションデータ。

    Returns:
        dict | None: 更新後のセッションデータ。更新できなかった場合は ``None``。
    """
    realm = session_data.get("realm")
    tokens = session_data.get("tokens") or {}
    refresh_token = tokens.get("refresh_token")
    if not realm or not refresh_token:
        return None

    token_url = _config.build_realm_endpoint(_config.kc_internal_base, realm, "token")
    new_tokens = refresh_access_token(
        token_url,
        client_id=_config.client_id,
        client_secret=_config.client_secret,
        refresh_token=refresh_token,
    )
    if not new_tokens:
        return None

    # id_token は更新レスポンスに含まれないことがあるため、既存の値を残す
    if not new_tokens.get("id_token"):
        new_tokens["id_token"] = tokens.get("id_token")

    session_data["tokens"] = new_tokens
    if not update_session(session_id, session_data):
        return None
    return session_data


def get_current_user(rf_sid: str | None = Cookie(default=None)) -> dict:
    """リクエストの Cookie から現在のユーザー情報を取得する FastAPI Dependency。

    HttpOnly Cookie ``rf_sid`` の署名検証と Redis セッション検証を実施し、
    必要に応じて access token を更新する。
    ルートパラメータ名 ``rf_sid`` は :data:`~modules.auth.session.SESSION_COOKIE_NAME` の値と一致させる。

    Args:
        rf_sid: FastAPI が Cookie から自動注入する署名済みセッション ID。
                Cookie が存在しない場合は ``None``。

    Returns:
        dict: Redis 上のセッションデータ内の ``user`` フィールド。
              ``sub``, ``preferred_username``, ``email``, ``realm`` キーを持つ。

    Raises:
        HTTPException(401): 以下のいずれかの場合に発生する。

            - Cookie が存在しない (``Not authenticated``)
            - Cookie の HMAC 署名が不正 / 改ざん検知 (``Invalid session``)
            - Redis 上にセッションが存在しない / TTL 期限切れ (``Session expired``)
            - refresh token が期限切れ、または更新に失敗した (``Session expired``)
            - セッションデータに ``user`` フィールドがない (``Invalid session payload``)
    """
    if not rf_sid:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_id = unsign_session_id(rf_sid)
    if not session_id:
        raise HTTPException(status_code=401, detail="Invalid session")

    session_data = get_session(session_id)
    if not session_data:
        raise HTTPException(status_code=401, detail="Session expired")

    tokens = session_data.get("tokens") or {}
    if is_access_token_expired(tokens):
        # refresh token 自体が切れている場合は更新不能なのでセッションを破棄する
        if is_refresh_token_expired(tokens):
            delete_session(session_id)
            raise HTTPException(status_code=401, detail="Session expired")

        refreshed = _refresh_session_tokens(session_id, session_data)
        if not refreshed:
            delete_session(session_id)
            raise HTTPException(status_code=401, detail="Session expired")
        session_data = refreshed

    user = session_data.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session payload")

    return user
