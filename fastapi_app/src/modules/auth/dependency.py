#!/usr/bin/env python
# coding:utf-8
"""FastAPI Dependency として使用する認証検証モジュール (プレーン別)。

各エンドポイント (またはルーター) に依存関数を付与することで、未認証リクエストを一元管理で弾く。

============================== ============== ============================================
依存関数                       Cookie         用途
============================== ============== ============================================
:func:`get_current_app_user`   ``rf_sid_app`` AP (``/api/v1/...``) のユーザー
:func:`get_current_cp_user`    ``rf_sid_cp``  CP (``/api/v1/cp/...``) のユーザー
:func:`require_app_roles`      ``rf_sid_app`` AP のロール確認 (いずれかを持てば可、不足は 403)
:func:`require_cp_roles`       ``rf_sid_cp``  CP のロール確認 (いずれかを持てば可、不足は 403)
:func:`get_current_user`       ``rf_sid_app`` 移行期間中の別名 (= :func:`get_current_app_user`)
============================== ============== ============================================

使用例::

    from fastapi import APIRouter, Depends
    from modules.auth.dependency import get_current_cp_user, require_cp_roles

    router = APIRouter(dependencies=[Depends(get_current_cp_user)])

    @router.post("/tenants")
    def create_tenant(user: dict = Depends(require_cp_roles("saas_admin"))):
        ...

認証フロー:
    1. プレーンの HttpOnly Cookie から署名済みセッション ID を取得する。
    2. ``itsdangerous`` で HMAC 署名を検証し、元のセッション ID を復元する (他プレーン向けの署名は拒否)。
    3. Redis (``session:{plane}:{sid}``) からセッションデータを取得する。
    4. セッションの ``plane`` が期待するプレーンであることを確認する。
    5. access token の有効期限を確認し、切れていれば refresh token で更新する
       (プレーンのクライアント ID と導出したシークレットを使う)。
    6. ``user`` フィールドを返却する。

トークンのライフサイクル:
    KeyCloak の access token は既定で数分と短く、セッション TTL (既定 1 時間) より
    先に切れる。セッションだけが生き残って中のトークンが使えない状態を避けるため、
    アクセスのたびに期限を確認し、必要なら更新してセッションに書き戻す。
    refresh token 自体が切れている場合はセッションを破棄して 401 とする。
    ロールはログイン時点の値を保持する (更新では変えない)。ロールの変更は再ログインで反映される。
"""
from collections.abc import Callable
from typing import Any

from fastapi import Cookie, Depends, HTTPException

from .environment import KeyCloakEnvironmentVariables
from .plane import APP_ROLES, CP_ROLES, Plane
from .session import delete_session, get_session, unsign_session_id, update_session
from .token import is_access_token_expired, is_refresh_token_expired, refresh_access_token

# KeyCloak 設定のグローバルインスタンス
_config = KeyCloakEnvironmentVariables()


def _refresh_session_tokens(plane: Plane, session_id: str, session_data: dict) -> dict | None:
    """セッション内のトークンを更新して保存し直す。

    Args:
        plane: プレーン。
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
        client_id=_config.client_id_for(plane),
        client_secret=_config.client_secret_for(plane, realm),
        refresh_token=refresh_token,
    )
    if not new_tokens:
        return None

    # id_token は更新レスポンスに含まれないことがあるため、既存の値を残す
    if not new_tokens.get("id_token"):
        new_tokens["id_token"] = tokens.get("id_token")

    session_data["tokens"] = new_tokens
    if not update_session(plane, session_id, session_data):
        return None
    return session_data


def load_session(plane: Plane, signed_session_id: str | None) -> dict[str, Any]:
    """署名済みセッション ID からセッションを読み込み、必要ならトークンを更新して返す。

    Args:
        plane: 期待するプレーン。
        signed_session_id: Cookie の値。

    Returns:
        dict: セッションデータ全体 (``user`` を含む)。

    Raises:
        HTTPException(401): 以下のいずれかの場合に発生する。

            - Cookie が存在しない (``Not authenticated``)
            - Cookie の HMAC 署名が不正 / 他プレーン向け / 改ざん検知 (``Invalid session``)
            - Redis 上にセッションが存在しない / TTL 期限切れ (``Session expired``)
            - refresh token が期限切れ、または更新に失敗した (``Session expired``)
            - セッションのプレーンが一致しない、``user`` が無い (``Invalid session payload``)
    """
    if not signed_session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_id = unsign_session_id(plane, signed_session_id)
    if not session_id:
        raise HTTPException(status_code=401, detail="Invalid session")

    session_data = get_session(plane, session_id)
    if not session_data:
        raise HTTPException(status_code=401, detail="Session expired")

    user = session_data.get("user")
    if session_data.get("plane") != plane.value or not isinstance(user, dict) or user.get("plane") != plane.value:
        raise HTTPException(status_code=401, detail="Invalid session payload")

    tokens = session_data.get("tokens") or {}
    if is_access_token_expired(tokens):
        # refresh token 自体が切れている場合は更新不能なのでセッションを破棄する
        if is_refresh_token_expired(tokens):
            delete_session(plane, session_id)
            raise HTTPException(status_code=401, detail="Session expired")

        refreshed = _refresh_session_tokens(plane, session_id, session_data)
        if not refreshed:
            delete_session(plane, session_id)
            raise HTTPException(status_code=401, detail="Session expired")
        session_data = refreshed

    return session_data


def get_current_app_session(rf_sid_app: str | None = Cookie(default=None)) -> dict[str, Any]:
    """AP のセッションデータ全体を返す FastAPI Dependency (``/api/auth/app/*`` 用)。

    通常のエンドポイントは :func:`get_current_app_user` を使うこと。

    Args:
        rf_sid_app: Cookie ``rf_sid_app`` の値。

    Returns:
        dict: セッションデータ (``tenant_code`` 等を含む)。

    Raises:
        HTTPException(401): :func:`load_session` を参照。
    """
    return load_session(Plane.APP, rf_sid_app)


def get_current_cp_session(rf_sid_cp: str | None = Cookie(default=None)) -> dict[str, Any]:
    """CP のセッションデータ全体を返す FastAPI Dependency (``/api/auth/cp/*`` 用)。

    通常のエンドポイントは :func:`get_current_cp_user` を使うこと。

    Args:
        rf_sid_cp: Cookie ``rf_sid_cp`` の値。

    Returns:
        dict: セッションデータ。

    Raises:
        HTTPException(401): :func:`load_session` を参照。
    """
    return load_session(Plane.CP, rf_sid_cp)


def get_current_app_user(session: dict[str, Any] = Depends(get_current_app_session)) -> dict[str, Any]:
    """AP の認証済みユーザーを返す FastAPI Dependency。

    Cookie ``rf_sid_app`` のセッションを検証する。CP のセッション (``rf_sid_cp``) では認証されない。
    セッションの読み込みは :func:`get_current_app_session` に委ねる (同一リクエスト内では 1 回だけ実行される)。

    Args:
        session: :func:`get_current_app_session` が返すセッションデータ。

    Returns:
        dict: ``sub``, ``preferred_username``, ``email``, ``realm``, ``plane`` (= ``"app"``),
              ``roles``, ``tenant_id`` を持つユーザー情報。

    Raises:
        HTTPException(401): セッションが無い・無効・期限切れ、またはプレーンが ``app`` でない場合。
    """
    return session["user"]


def get_current_cp_user(session: dict[str, Any] = Depends(get_current_cp_session)) -> dict[str, Any]:
    """CP の認証済みユーザーを返す FastAPI Dependency。

    Cookie ``rf_sid_cp`` のセッションを検証する。AP のセッション (``rf_sid_app``) では認証されない。
    セッションの読み込みは :func:`get_current_cp_session` に委ねる (同一リクエスト内では 1 回だけ実行される)。

    Args:
        session: :func:`get_current_cp_session` が返すセッションデータ。

    Returns:
        dict: ``sub``, ``preferred_username``, ``email``, ``realm``, ``plane`` (= ``"cp"``), ``roles`` を持つユーザー情報。

    Raises:
        HTTPException(401): セッションが無い・無効・期限切れ、またはプレーンが ``cp`` でない場合。
    """
    return session["user"]


# 移行期間中の別名。既存の Depends(get_current_user) / dependency_overrides[get_current_user] はそのまま動く。
get_current_user = get_current_app_user


def _require_roles(roles: tuple[str, ...], allowed: frozenset[str], user_dependency: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """ロール確認の依存関数を生成する。

    Args:
        roles: 要求するロール (いずれかを持てば可)。
        allowed: プレーンで扱うロールの集合。
        user_dependency: ユーザーを解決する依存関数。

    Returns:
        Callable: ユーザー情報を返す依存関数。

    Raises:
        ValueError: ロールが空、またはプレーンで扱わないロールを含む場合 (定義時の誤り)。
    """
    if not roles:
        raise ValueError("at least one role is required")
    unknown = sorted(set(roles) - allowed)
    if unknown:
        raise ValueError(f"unknown roles for this plane: {', '.join(unknown)}")
    required = frozenset(roles)

    def _dependency(user: dict[str, Any] = Depends(user_dependency)) -> dict[str, Any]:
        if required.isdisjoint(user.get("roles") or []):
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return _dependency


def require_app_roles(*roles: str) -> Callable[..., dict[str, Any]]:
    """AP のロールを要求する依存関数を返す。

    指定したロールの **いずれか** を持てば通過し、ユーザー情報を返す。持たなければ 403。
    未認証は :func:`get_current_app_user` が 401 を返す。

    使用例::

        @router.post("/organizations")
        def create_organization(user: dict = Depends(require_app_roles("tenant_admin"))):
            ...

    Args:
        *roles: ``tenant_admin`` / ``member`` のいずれか 1 つ以上。

    Returns:
        Callable: FastAPI の依存関数。

    Raises:
        ValueError: ロールが空、または AP のロールでない値を含む場合。
    """
    return _require_roles(roles, APP_ROLES, get_current_app_user)


def require_cp_roles(*roles: str) -> Callable[..., dict[str, Any]]:
    """CP のロールを要求する依存関数を返す。

    指定したロールの **いずれか** を持てば通過し、ユーザー情報を返す。持たなければ 403。
    未認証は :func:`get_current_cp_user` が 401 を返す。

    使用例::

        # 参照系: どちらのロールでも可
        router = APIRouter(dependencies=[Depends(require_cp_roles("saas_admin", "saas_viewer"))])

        # 変更系: saas_admin のみ
        @router.post("/tenants")
        def create_tenant(user: dict = Depends(require_cp_roles("saas_admin"))):
            ...

    Args:
        *roles: ``saas_admin`` / ``saas_viewer`` のいずれか 1 つ以上。

    Returns:
        Callable: FastAPI の依存関数。

    Raises:
        ValueError: ロールが空、または CP のロールでない値を含む場合。
    """
    return _require_roles(roles, CP_ROLES, get_current_cp_user)
