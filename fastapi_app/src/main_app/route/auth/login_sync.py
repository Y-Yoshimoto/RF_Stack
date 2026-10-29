#!/usr/bin/env python
# coding:utf-8
"""AP のログイン完了時のユーザー同期の呼び出し (01 PF-USR-04 / 05、05 #31)。

通常のコールバック (:func:`~main_app.route.auth.apiapp.callback`) と開発用ログイン
(:func:`~main_app.route.auth.dev_login.dev_login`) の AP の分岐が、**セッションを作る前に** 呼ぶ。
CP のログインとトークン更新では呼ばない (トークン更新で ``last_login_at`` を更新しない。PF-USR-05)。

テナントはレジストリで確認済みの値 (``tenant_id`` / ``tenant_code``) だけを受け取り、トークンのクレームからは決めない。
その値でテナントコンテキストを設定し、``app_runtime`` のセッション (RLS) で
:func:`~main_app.services.user_sync.sync_user_on_login` を呼ぶ (コミットは同期処理が行う)。

失敗時の扱い (呼び出し側。いずれもセッションを作らない):
    - :class:`~main_app.services.errors.UserDeactivatedError`: コールバックは ``login_rejected``、開発用ログインは 403 (``login_rejected``)
    - ``sqlalchemy.exc.OperationalError`` (DB に接続できない): コールバックは ``service_unavailable``、開発用ログインは 503 (共通の例外ハンドラ)
    - それ以外: コールバックは ``internal_error``、開発用ログインは 500 (共通の例外ハンドラ)
"""
import uuid
from typing import Any

from main_app.services.user_sync import UserSyncResult, sync_user_on_login
from modules.tenancy.context import TenantContext, tenant_scope
from modules.tenancy.providers import open_app_session


def _parse_uuid(value: Any) -> uuid.UUID | None:
    """IdP の利用者 ID を ``TenantContext.user_id`` 用に UUID にする (UUID でなければ ``None``)。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def login_display_name(user: dict[str, Any]) -> str | None:
    """ログイン同期に渡す表示名 (``name`` クレーム、無ければ ``preferred_username``)。

    Keycloak の ``name`` は姓・名から作られ、AP のユーザー管理 (``UserService``) の表示名と同じ形になる。
    ``preferred_username`` を優先すると、管理画面で変更した表示名がログインのたびに上書きされるため使わない。

    Args:
        user: セッションのユーザー情報 (:func:`~modules.auth.login.build_login_session` の ``user``)。

    Returns:
        str | None: 表示名。どちらも無ければ ``None`` (同期処理がメール → ``sub`` で代用する)。
    """
    for key in ("name", "preferred_username"):
        value = user.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def login_name_part(user: dict[str, Any], key: str) -> str | None:
    """ログイン同期に渡す姓・名 (``given_name`` / ``family_name``)。

    セッションにキーがあれば (:func:`~modules.auth.login.build_login_session` が作ったセッション)、クレームが無い・空でも
    ``""`` を返して写しを NULL にする (IdP で未設定になった値を残さない)。キーが無ければ ``None`` (写しを更新しない)。

    Args:
        user: セッションのユーザー情報。
        key: ``given_name`` または ``family_name``。

    Returns:
        str | None: 値。``None`` は「更新しない」。
    """
    if key not in user:
        return None
    value = user.get(key)
    return value if isinstance(value, str) else ""


def login_roles(user: dict[str, Any]) -> list[str] | None:
    """ログイン同期に渡すロール (セッションの ``roles``。AP の許可リストで絞り込み済み)。リストでなければ ``None`` (写しを更新しない)。"""
    roles = user.get("roles")
    if not isinstance(roles, list):
        return None
    return [role for role in roles if isinstance(role, str)]


def sync_app_user_on_login(session_data: dict[str, Any], *, tenant_id: uuid.UUID, tenant_code: str) -> UserSyncResult:
    """AP のログイン完了時に、テナントのコンテキストでユーザー行を同期する (デフォルト組織の作成を含む)。

    表示名・メールに加えて、一覧表示用の写し (姓・名・ロール) も渡す (姓・名は ``given_name`` / ``family_name``、
    ロールはセッションの ``roles`` = アクセストークンのレルムロールのうち ``tenant_admin`` / ``member``)。

    Args:
        session_data: これから作る AP のセッションの内容 (:func:`~modules.auth.login.build_login_session` の戻り値)。
        tenant_id: ログイン先のテナント ID (レジストリで確認済みの値)。
        tenant_code: ログイン先のテナントコード (レジストリで確認済みの値)。

    Returns:
        UserSyncResult: 同期の結果。

    Raises:
        main_app.services.errors.UserDeactivatedError: ユーザーが無効化されている (ログインを拒否する)。
        ValueError: セッションのユーザーに ``sub`` が無い。
        sqlalchemy.exc.SQLAlchemyError: DB の操作に失敗した (接続できない場合は ``OperationalError``)。
    """
    user = session_data.get("user") or {}
    idp_subject = user.get("sub")
    if not isinstance(idp_subject, str) or not idp_subject:
        raise ValueError("session user has no subject")
    ctx = TenantContext(tenant_id=tenant_id, tenant_code=tenant_code, user_id=_parse_uuid(idp_subject), plane="app")
    with tenant_scope(ctx), open_app_session() as session:
        return sync_user_on_login(
            session,
            tenant_id=tenant_id,
            idp_subject=idp_subject,
            email=user.get("email"),
            display_name=login_display_name(user),
            first_name=login_name_part(user, "given_name"),
            last_name=login_name_part(user, "family_name"),
            roles=login_roles(user),
        )
