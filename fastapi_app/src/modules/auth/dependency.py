#!/usr/bin/env python
# coding:utf-8
"""FastAPI Dependency として使用する認証検証モジュール。

各エンドポイントに ``Depends(get_current_user)`` を付与することで、
未認証リクエストを一元管理で踣ることができる。

認証フロー:
    1. HttpOnly Cookie ``rf_sid`` から署名済みセッション ID を取得。
    2. ``itsdangerous`` で HMAC 署名を検証し、元のセッション ID を復元。
    3. Redis からセッションデータを取得し、``user`` フィールドを返却。
"""
from fastapi import Cookie, HTTPException

from .session import SESSION_COOKIE_NAME, get_session, unsign_session_id


def get_current_user(rf_sid: str | None = Cookie(default=None)) -> dict:
    """リクエストの Cookie から現在のユーザー情報を取得する FastAPI Dependency。

    HttpOnly Cookie ``rf_sid`` の署名検証と Redis セッション検証を実施する。
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

    user = session_data.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session payload")

    return user
