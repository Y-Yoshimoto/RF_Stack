#!/usr/bin/env python
# coding:utf-8
"""ToDo 本体・コメント・チェックリストのサービスで共有する部品（操作者、閲覧できる ToDo の取得、記録、入力の検証）。

FastAPI に依存しない。:mod:`main_app.services.todo_service` / :mod:`~main_app.services.todo_comment_service` /
:mod:`~main_app.services.todo_checklist_service` が使う。閲覧範囲の**定義**は :mod:`main_app.services.todo_policy` だけにあり、
ここではそれを ``WHERE`` に付けて取得するだけ（AP-VIS-09）。

- :func:`actor_of`: テナントコンテキストと操作者の ``t_user.id``・ロールから :class:`~main_app.services.todo_policy.TodoActor` を作る
- :func:`require_visible_todo`: 閲覧できる ToDo を取得する。無ければ :class:`~main_app.services.errors.TodoNotFoundError`
  （他テナント・存在しない・論理削除済み・閲覧範囲外を区別しない。03 §2）。コメント・チェックリストもまずこれを通す（AP-CMT-06）
"""
import datetime as dt
import enum
import uuid
from collections.abc import Collection
from typing import Any

from sqlmodel import Session

from main_app.models import TodoActivityAction, TTodo
from main_app.repositories import users as user_repo
from main_app.repositories.todos import activities as activity_repo
from main_app.repositories.todos import todos as todo_repo
from main_app.services.common import UserNameView, record_audit
from main_app.services.errors import TodoNotFoundError, TodoValidationError
from main_app.services.todo_policy import TodoActor, visible_condition
from modules.tenancy.context import require_tenant_context

# 監査ログの対象の種別（ToDo 本体・コメント・チェックリストとも ToDo を対象にする。コメント・項目の ID は payload に入れる）
AUDIT_TARGET_TYPE = "todo"


# --------------------------------------------------------------------------- 操作者・閲覧できる ToDo


def validate_actor_args(actor_user_id: Any, actor_roles: Any) -> tuple[uuid.UUID, frozenset[str]]:
    """サービスのコンストラクタの操作者の引数を検証する。

    Args:
        actor_user_id: 操作者の ``t_user.id``。
        actor_roles: 操作者のテナントのロール。

    Returns:
        tuple[uuid.UUID, frozenset[str]]: ユーザー ID とロール。

    Raises:
        TypeError: ``actor_user_id`` が UUID でない、``actor_roles`` が文字列。
    """
    if not isinstance(actor_user_id, uuid.UUID):
        raise TypeError("actor_user_id must be uuid.UUID")
    if isinstance(actor_roles, str):
        raise TypeError("actor_roles must be a collection of role names")
    return actor_user_id, frozenset(actor_roles)


def actor_of(user_id: uuid.UUID, roles: Collection[str]) -> TodoActor:
    """テナントコンテキストから操作者を作る。

    Args:
        user_id: 操作者の AP のユーザー ID（``t_user.id``。IdP の ``sub`` ではない）。
        roles: 操作者のテナントのロール（``tenant_admin`` / ``member``）。

    Returns:
        TodoActor: 操作者（``tenant_id`` はコンテキストの値）。

    Raises:
        modules.tenancy.context.TenantContextMissingError: コンテキストが無い。
    """
    ctx = require_tenant_context()
    return TodoActor(tenant_id=ctx.tenant_id, user_id=user_id, roles=frozenset(roles))


def require_visible_todo(session: Session, actor: TodoActor, todo_id: uuid.UUID, *, for_update: bool = False) -> TTodo:
    """操作者が閲覧できる ToDo を取得する（論理削除済みを除く）。

    Args:
        session: AP のセッション（テナントコンテキスト下）。
        actor: 操作者。
        todo_id: ToDo ID。
        for_update: ``t_todo`` の行ロック（``SELECT ... FOR UPDATE OF t_todo``）を取るか。

    Returns:
        TTodo: ToDo。

    Raises:
        TodoNotFoundError: 存在しない（他テナント・論理削除済み・閲覧範囲外・ID の形式が不正を含む）。
    """
    if not isinstance(todo_id, uuid.UUID):
        raise TodoNotFoundError(todo_id)
    todo = todo_repo.get_todo(session, actor.tenant_id, todo_id, condition=visible_condition(actor), for_update=for_update)
    if todo is None:
        raise TodoNotFoundError(todo_id)
    return todo


def load_user_names(session: Session, tenant_id: uuid.UUID, user_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, UserNameView]:
    """ユーザー ID から表示名・有効かをまとめて取得する（1 クエリ。無効化されたユーザーを含み、テナント内に無い ID は含まない）。"""
    return {user_id: UserNameView(id=user_id, display_name=name, is_active=active) for user_id, name, active in user_repo.list_user_names(session, tenant_id, set(user_ids))}


def user_name_or_unknown(users: dict[uuid.UUID, UserNameView], user_id: uuid.UUID) -> UserNameView:
    """表示名を引く。見つからなければ（外部キーがあるため通常は起きない）表示名を空、無効として返す。"""
    return users.get(user_id) or UserNameView(id=user_id, display_name="", is_active=False)


# --------------------------------------------------------------------------- 記録（アクティビティ・監査ログ）


def record_activity(session: Session, actor: TodoActor, todo_id: uuid.UUID, action: TodoActivityAction, payload: dict[str, Any]) -> None:
    """アクティビティを追記する（同じトランザクション。AP-ACT-03）。"""
    activity_repo.add_activity(session, tenant_id=actor.tenant_id, todo_id=todo_id, actor_id=actor.user_id, action=action, payload=payload)


def record_todo_audit(session: Session, actor: TodoActor, action: str, todo_id: uuid.UUID, payload: dict[str, Any]) -> None:
    """ToDo を対象（``target_type = 'todo'``）にした AP 監査ログを追記する（同じトランザクション。AP-ACT-04、AP-CMT-08）。"""
    record_audit(session, require_tenant_context(), actor_id=actor.user_id, action=action, target_type=AUDIT_TARGET_TYPE, target_id=todo_id, payload=payload)


def to_json(value: Any) -> Any:
    """アクティビティ・監査ログの ``payload`` 用に JSON に変換できる値にする。"""
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: to_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_json(item) for item in value]
    return value


# --------------------------------------------------------------------------- 入力


def has_control_chars(value: str, *, allow_whitespace: bool) -> bool:
    """制御文字を含むか（``allow_whitespace`` なら改行・タブは許可する）。"""
    allowed = {"\n", "\r", "\t"} if allow_whitespace else set()
    return any((ord(ch) < 0x20 and ch not in allowed) or ord(ch) == 0x7F for ch in value)


def split_after(after: Any) -> tuple[Any, uuid.UUID]:
    """一覧の起点を ``(値, id)`` に分ける（不正なら ``TodoValidationError(field="cursor")``）。"""
    if not isinstance(after, tuple | list) or len(after) != 2:
        raise TodoValidationError("cursor", "format")
    value, raw_id = after
    try:
        last_id = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
    except ValueError:
        raise TodoValidationError("cursor", "format") from None
    return value, last_id


def parse_aware_datetime(value: Any) -> dt.datetime:
    """タイムゾーン付きの日時（``datetime`` または ISO 8601 の文字列）。"""
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            raise TodoValidationError("cursor", "format") from None
    if not isinstance(value, dt.datetime) or value.tzinfo is None:
        raise TodoValidationError("cursor", "format")
    return value


def normalize_datetime_after(after: Any) -> tuple[dt.datetime, uuid.UUID] | None:
    """``(created_at, id)`` の起点（アクティビティ・コメント）。日時はタイムゾーン付きの ISO 8601 の文字列も可。"""
    if after is None:
        return None
    value, last_id = split_after(after)
    return parse_aware_datetime(value), last_id
