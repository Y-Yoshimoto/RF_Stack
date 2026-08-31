#!/usr/bin/env python
# coding:utf-8
"""Redis を使ったサーバーサイドセッション管理モジュール。

セッションデータは Redis に保存し、クライアントには HMAC 署名済みの
セッション ID のみを HttpOnly Cookie として渡す。

設計方針:
    - セッション本体（トークン・ユーザー情報）はすべて Redis に保存する。
    - クライアントに渡す Cookie 値は ``itsdangerous.URLSafeSerializer`` で署名し、
      改ざんを検知できる。
    - OIDC の state パラメータも同じ Redis インスタンスで一時保存し、
      リプレイアタック対策として読み出し時に自動削除 (pop) する。

環境変数:
    REDIS_URL: Redis 接続 URL。デフォルト ``redis://redis_c:6379/0``。
    SESSION_SECRET_KEY: Cookie 署名用の秘密鍵。デフォルト ``change-me-session-secret``。
    SESSION_TTL_SECONDS: セッション有効期限 (秒)。デフォルト 3600。最低 60 秒を保証。
"""
import json
import os
import secrets
from typing import Any

from itsdangerous import BadSignature, URLSafeSerializer
from redis import Redis

SESSION_COOKIE_NAME = "rf_sid"
SESSION_SIGNING_SALT = "rf-stack-session"


def _redis_client() -> Redis:
    """環境変数 ``REDIS_URL`` から Redis クライアントを生成して返す。

    Returns:
        Redis: 文字列デコード済みの Redis クライアントインスタンス。
    """
    redis_url = os.getenv("REDIS_URL", "redis://redis_c:6379/0")
    return Redis.from_url(redis_url, decode_responses=True)


def _serializer() -> URLSafeSerializer:
    """環境変数 ``SESSION_SECRET_KEY`` を使った HMAC シリアライザーを返す。

    Returns:
        URLSafeSerializer: Cookie 署名・検証に使用するシリアライザー。
    """
    secret_key = os.getenv("SESSION_SECRET_KEY", "change-me-session-secret")
    return URLSafeSerializer(secret_key, salt=SESSION_SIGNING_SALT)


def get_session_ttl_seconds() -> int:
    """セッション TTL を環境変数から取得する。

    環境変数 ``SESSION_TTL_SECONDS`` を参照する。数値以外が設定されている場合は
    3600 秒にフォールバックする。安全のため最低 60 秒を保証する。

    Returns:
        int: セッション有効期限 (秒)。最小値は 60。
    """
    ttl_raw = os.getenv("SESSION_TTL_SECONDS", "3600")
    try:
        ttl = int(ttl_raw)
    except ValueError:
        ttl = 3600
    return max(ttl, 60)


def create_session(data: dict[str, Any], ttl_seconds: int | None = None) -> str:
    """新しいセッションを Redis に作成し、セッション ID を返す。

    セッションデータは ``session:{session_id}`` キーで Redis に保存される。
    セッション ID は暗号論的乱数 (32 バイト URL-safe) で生成される。

    Args:
        data: セッションに保存するデータ。
              ``realm``, ``tokens``, ``user`` をキーに持つ dict を想定。
        ttl_seconds: セッションの有効期限 (秒)。``None`` の場合は
                     :func:`get_session_ttl_seconds` の値を使用する。

    Returns:
        str: 生成されたセッション ID (署名なし)。
    """
    session_id = secrets.token_urlsafe(32)
    ttl = ttl_seconds or get_session_ttl_seconds()
    key = f"session:{session_id}"
    _redis_client().setex(key, ttl, json.dumps(data, ensure_ascii=True))
    return session_id


def get_session(session_id: str) -> dict[str, Any] | None:
    """Redis からセッションデータを取得する。

    Args:
        session_id: :func:`create_session` が返した署名なしセッション ID。

    Returns:
        dict | None: セッションデータの dict。セッションが存在しない場合
                     (未作成・期限切れを含む) は ``None`` を返す。
    """
    key = f"session:{session_id}"
    raw = _redis_client().get(key)
    if not raw:
        return None
    return json.loads(raw)


def delete_session(session_id: str) -> None:
    """Redis からセッションを明示的に削除する。

    ログアウト時など、TTL 期限を待たずにセッションを無効化したい場合に使用する。
    存在しないセッション ID を渡した場合は何もしない。

    Args:
        session_id: 削除対象のセッション ID (署名なし)。
    """
    key = f"session:{session_id}"
    _redis_client().delete(key)


def sign_session_id(session_id: str) -> str:
    """セッション ID を HMAC 署名して Cookie に格納できる文字列に変換する。

    署名には ``SESSION_SECRET_KEY`` 環境変数の値を使用する。
    Cookie への格納前に必ずこの関数を通すこと。

    Args:
        session_id: 署名対象のセッション ID (生の文字列)。

    Returns:
        str: HMAC 署名済みの URL-safe 文字列。
    """
    return _serializer().dumps({"sid": session_id})


def unsign_session_id(signed_value: str) -> str | None:
    """署名済み Cookie 値を検証し、元のセッション ID を取り出す。

    署名が不正・改ざんされている場合は ``None`` を返すことで、
    上位レイヤーが安全にエラー処理を行えるようにする。

    Args:
        signed_value: :func:`sign_session_id` が生成した署名済み文字列。

    Returns:
        str | None: 検証成功時は元のセッション ID。
                    署名不正・改ざん検知時は ``None``。
    """
    try:
        payload = _serializer().loads(signed_value)
    except BadSignature:
        return None
    return payload.get("sid")


def save_auth_state(state: str, payload: dict[str, Any], ttl_seconds: int = 300) -> None:
    """OIDC Authorization Code Flow の state パラメータを Redis に一時保存する。

    CSRF 対策として認可リクエスト時に生成した state をここに保存し、
    コールバック時に :func:`pop_auth_state` で検証・削除する。

    Args:
        state: 認可リクエスト時に生成した URL-safe なランダム文字列。
        payload: state に紐づけるデータ。``{"realm": "<realm_name>"}`` を想定。
        ttl_seconds: 一時データの有効期限 (秒)。デフォルト 300 秒 (5 分)。
    """
    key = f"auth_state:{state}"
    _redis_client().setex(key, ttl_seconds, json.dumps(payload, ensure_ascii=True))


def pop_auth_state(state: str) -> dict[str, Any] | None:
    """Redis から state に紐づくペイロードを取り出し、同時に削除する。

    「読んだら消す」ことでリプレイアタックを防ぐ。
    コールバックエンドポイントでのみ呼び出すこと。

    Args:
        state: ブラウザから返ってきた state パラメータ。

    Returns:
        dict | None: 保存時のペイロード dict。
                     存在しない・期限切れの場合は ``None`` を返す。
    """
    key = f"auth_state:{state}"
    client = _redis_client()
    raw = client.get(key)
    if not raw:
        return None
    client.delete(key)
    return json.loads(raw)
