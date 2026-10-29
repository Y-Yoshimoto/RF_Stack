#!/usr/bin/env python
# coding:utf-8
"""AP の API（``/api/v1``）で共通の依存関数。

- :func:`require_active_app_user` — セッションのユーザーが AP で有効かを各リクエストで確認する(01 PF-USR-03、05 #32)。
  ``main_app/route/v1/apiapp.py`` のルーター全体に適用する。無効化されたユーザー・同期前のユーザーは、
  Redis のセッションを破棄して 401 にする。``t_user.is_active`` を正とし、キャッシュしない。
- :data:`TenantAdminDep` — 変更系のエンドポイントに ``tenant_admin`` を要求する(01 §7.5)。
- :func:`get_user_service` / :func:`get_organization_service` / :func:`get_todo_service` / :func:`get_todo_comment_service` /
  :func:`get_todo_checklist_service` — サービスを 1 リクエスト分だけ作る。
  テストでは ``app.dependency_overrides`` で差し替える(Keycloak の管理クライアントのフェイクなど)。
"""
import logging
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends

from main_app.services.errors import UserDeactivatedError, UserNotSyncedError
from main_app.services.organization_service import OrganizationService
from main_app.services.todo_checklist_service import TodoChecklistService
from main_app.services.todo_comment_service import TodoCommentService
from main_app.services.todo_service import TodoService
from main_app.services.user_service import UserService
from main_app.services.user_sync import require_active_session_user
from modules.auth.dependency import app_session_cookie, get_current_app_user, require_app_roles
from modules.auth.plane import Plane
from modules.auth.session import delete_session, unsign_session_id
from modules.tenancy.app_dependency import AppSessionDep

logger = logging.getLogger(__name__)

# 参照系: テナントのどのロールでも可。変更系: tenant_admin のみ(01 §7.5)。
require_tenant_member = require_app_roles("tenant_admin", "member")
require_tenant_admin = require_app_roles("tenant_admin")
TenantAdminDep = Annotated[dict[str, Any], Depends(require_tenant_admin)]


@dataclass(frozen=True, slots=True)
class ActiveAppUser:
    """AP で有効と確認できたセッションのユーザー。

    Attributes:
        id: AP のユーザー ID(``t_user.id``)。
        subject: IdP の利用者 ID(セッションの ``sub``)。
        claims: セッションのユーザー情報(``preferred_username`` / ``email`` / ``roles`` 等)。
    """

    id: uuid.UUID
    subject: str
    claims: dict[str, Any]


def _discard_session(signed_session_id: str | None) -> None:
    """Redis の AP セッションを削除する(署名が不正・既に無ければ何もしない)。"""
    session_id = unsign_session_id(Plane.APP, signed_session_id) if signed_session_id else None
    if session_id:
        delete_session(Plane.APP, session_id)


def require_active_app_user(
    session: AppSessionDep,
    user: Annotated[dict[str, Any], Depends(get_current_app_user)],
    signed_session_id: Annotated[str | None, Depends(app_session_cookie)],
) -> ActiveAppUser:
    """セッションのユーザーが AP で有効かを確認し、AP のユーザー ID を含めて返す FastAPI 依存関数。

    ユーザー行を ``sub`` で 1 回 SELECT する(``require_active_session_user``)。テナントコンテキストと
    CSRF 対策の後に評価されるよう、ルーターの ``dependencies`` の最後に置く。

    Args:
        session: AP の DB セッション(エンドポイントと同じリクエスト内で共有される)。
        user: セッションのユーザー情報。
        signed_session_id: Cookie ``rf_sid_app`` の値(失効時のセッション削除に使う)。

    Returns:
        ActiveAppUser: 有効なユーザー。

    Raises:
        UserDeactivatedError: ユーザーが無効化されている(401 ``user_deactivated``。セッションを破棄する)。
        UserNotSyncedError: ユーザー行が無い(401 ``user_not_synced``。セッションを破棄する。再ログインで同期される)。
    """
    subject = str(user["sub"])
    try:
        user_id = require_active_session_user(session, idp_subject=subject)
    except (UserDeactivatedError, UserNotSyncedError) as exc:
        _discard_session(signed_session_id)
        logger.info("AP のセッションを破棄しました: reason=%s", exc.code)
        raise
    return ActiveAppUser(id=user_id, subject=subject, claims=user)


ActiveAppUserDep = Annotated[ActiveAppUser, Depends(require_active_app_user)]


def get_user_service(session: AppSessionDep, actor: ActiveAppUserDep) -> UserService:
    """ユーザー管理サービスを作る FastAPI 依存関数(Keycloak の管理クライアントは操作ごとにサービスが作って閉じる)。"""
    return UserService(session, actor_subject=actor.subject)


def get_organization_service(session: AppSessionDep, actor: ActiveAppUserDep) -> OrganizationService:
    """組織管理サービスを作る FastAPI 依存関数。"""
    return OrganizationService(session, actor_subject=actor.subject)


def get_todo_service(session: AppSessionDep, actor: ActiveAppUserDep) -> TodoService:
    """ToDo サービスを作る FastAPI 依存関数(操作者は ``t_user.id`` とセッションのロール。閲覧範囲・権限の判定はサービスが行う)。"""
    return TodoService(session, actor_user_id=actor.id, actor_roles=actor.claims.get("roles") or [])


def get_todo_comment_service(session: AppSessionDep, actor: ActiveAppUserDep) -> TodoCommentService:
    """ToDo のコメントのサービスを作る FastAPI 依存関数(操作者の指定は :func:`get_todo_service` と同じ)。"""
    return TodoCommentService(session, actor_user_id=actor.id, actor_roles=actor.claims.get("roles") or [])


def get_todo_checklist_service(session: AppSessionDep, actor: ActiveAppUserDep) -> TodoChecklistService:
    """ToDo のチェックリストのサービスを作る FastAPI 依存関数(操作者の指定は :func:`get_todo_service` と同じ)。"""
    return TodoChecklistService(session, actor_user_id=actor.id, actor_roles=actor.claims.get("roles") or [])


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
OrganizationServiceDep = Annotated[OrganizationService, Depends(get_organization_service)]
TodoServiceDep = Annotated[TodoService, Depends(get_todo_service)]
TodoCommentServiceDep = Annotated[TodoCommentService, Depends(get_todo_comment_service)]
TodoChecklistServiceDep = Annotated[TodoChecklistService, Depends(get_todo_checklist_service)]
