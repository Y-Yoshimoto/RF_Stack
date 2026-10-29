#!/usr/bin/env python
# coding:utf-8
"""ToDo のコメントのサービス（docs/spec/ToDoApp.md §4.5 AP-CMT。``/api/v1/todos/{id}/comments`` から使う）。

FastAPI に依存しない。AP のセッション（テナントコンテキスト下、``app_runtime``）と操作者（``t_user.id`` とロール）を受け取り、
**コミットはサービスが行う**。テナントはコンテキストから得る（引数に取らない）。

使用例（ルーターから）::

    service = TodoCommentService(session, actor_user_id=active_user.id, actor_roles=roles)
    page = service.list_comments(todo_id, limit=50)
    view = service.create_comment(todo_id, body="確認しました")
    view = service.update_comment(todo_id, view.id, expected_version=view.version, body="確認しました（修正）")
    service.delete_comment(todo_id, view.id, expected_version=view.version)

公開メソッドと例外（HTTP ステータスは :mod:`main_app.services.errors`）:

| メソッド | 例外 |
| --- | --- |
| :meth:`TodoCommentService.list_comments` | ``TodoValidationError``（``cursor``）, ``TodoNotFoundError`` |
| :meth:`TodoCommentService.create_comment` | ``TodoValidationError``（``body``）, ``TodoNotFoundError`` |
| :meth:`TodoCommentService.update_comment` | ``TodoValidationError``（``body``）, ``TodoNotFoundError``, ``TodoCommentNotFoundError``, ``TodoCommentVersionConflictError``, ``TodoPermissionDeniedError``（``edit_comment``） |
| :meth:`TodoCommentService.delete_comment` | ``TodoNotFoundError``, ``TodoCommentNotFoundError``, ``TodoCommentVersionConflictError``, ``TodoPermissionDeniedError``（``delete_comment``） |

判定の順序（変更系）: 入力の形式（422）→ ToDo の閲覧範囲（404 ``todo_not_found``。AP-CMT-06）→ コメント（404 ``todo_comment_not_found``。
別の ToDo のコメント・論理削除済み・他テナントを区別しない）→ コメントの版（412）→ 権限（403）。

- 投稿は ToDo を閲覧できる人なら誰でもできる（AP-CMT-01。``TodoPermissions.can_comment``）。編集は投稿者のみ、削除は投稿者と
  ``tenant_admin``（AP-CMT-03, 04。:func:`main_app.services.todo_policy.comment_permissions`）
- 本文は前後の空白を除いて 1〜4,000 文字のプレーンテキスト（改行・タブ以外の制御文字は不可）。同じ本文での編集は何もしない（版も変えない）
- 編集は ``version`` を +1 して ``edited_at`` を設定する（「編集済み」の表示）。削除は論理削除（AP-CMT-05）
- **アクティビティには記録しない**。監査ログ ``todo.comment_create`` / ``todo.comment_update`` / ``todo.comment_delete`` に記録する
  （``target_type = 'todo'``、``target_id`` は ToDo ID、``payload`` にコメント ID と本文の長さ。**本文は残さない**。AP-CMT-08）
- ToDo 本体の ``version`` / ``updated_at`` は変えない（ToDoApp.md §10 #16）
"""
import logging
import uuid
from collections.abc import Collection
from typing import Any

from sqlmodel import Session

from main_app.models import TODO_COMMENT_BODY_MAX_LENGTH, TTodoComment
from main_app.repositories.keyset import Page, normalize_limit
from main_app.repositories.todos import comments as comment_repo
from main_app.services.common import UserNameView, change, utc_now
from main_app.services.errors import TodoCommentNotFoundError, TodoCommentVersionConflictError, TodoPermissionDeniedError, TodoValidationError
from main_app.services.todo_access import actor_of, has_control_chars, load_user_names, normalize_datetime_after, record_todo_audit, require_visible_todo, user_name_or_unknown, validate_actor_args
from main_app.services.todo_policy import TodoActor, TodoOperation, comment_permissions
from main_app.services.todo_views import TodoCommentView

__all__ = ["TodoCommentService", "TodoCommentView"]

logger = logging.getLogger(__name__)

# 監査ログの操作（AP-CMT-08）
ACTION_TODO_COMMENT_CREATE = "todo.comment_create"
ACTION_TODO_COMMENT_UPDATE = "todo.comment_update"
ACTION_TODO_COMMENT_DELETE = "todo.comment_delete"


class TodoCommentService:
    """ToDo のコメントの一覧・投稿・編集・削除（1 リクエストごとにインスタンスを作る）。

    Args:
        session: AP のセッション（テナントコンテキスト下）。
        actor_user_id: 操作者の AP のユーザー ID（``t_user.id``。IdP の ``sub`` ではない）。
        actor_roles: 操作者のテナントのロール（``tenant_admin`` / ``member``。セッションの ``roles``）。
    """

    def __init__(self, session: Session, *, actor_user_id: uuid.UUID, actor_roles: Collection[str]) -> None:
        """依存を保持する。"""
        self._session = session
        self._actor_user_id, self._actor_roles = validate_actor_args(actor_user_id, actor_roles)

    def list_comments(self, todo_id: uuid.UUID, *, limit: int = 50, after: tuple[Any, uuid.UUID] | None = None) -> Page[TodoCommentView]:
        """ToDo のコメントを古い順に返す（AP-CMT-02。論理削除済みを除く。投稿者は結合して 1 クエリ）。

        Args:
            todo_id: ToDo ID。
            limit: 件数（1〜200 に補正）。
            after: 起点（前のページの ``next_after``。``(created_at, id)``。日時はタイムゾーン付きの ISO 8601 の文字列も可）。

        Returns:
            Page[TodoCommentView]: ページ。

        Raises:
            TodoValidationError: ``after`` が不正（``field="cursor"``）。
            TodoNotFoundError: ToDo が存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        normalized_after = normalize_datetime_after(after)
        todo = require_visible_todo(self._session, actor, todo_id)
        page = comment_repo.list_comments(self._session, actor.tenant_id, todo.id, after=normalized_after, limit=normalize_limit(limit))
        items = [_comment_view(actor, row.comment, UserNameView(id=row.comment.author_id, display_name=row.author_display_name, is_active=row.author_is_active)) for row in page.items]
        return Page(items=items, next_after=page.next_after)

    def create_comment(self, todo_id: uuid.UUID, *, body: str) -> TodoCommentView:
        """コメントを投稿してコミットする（AP-CMT-01。ToDo を閲覧できれば誰でも投稿できる）。

        Args:
            todo_id: ToDo ID。
            body: 本文（前後の空白を除いて 1〜4,000 文字）。

        Returns:
            TodoCommentView: 投稿したコメント。

        Raises:
            TodoValidationError: 本文が不正（``field="body"``）。
            TodoNotFoundError: ToDo が存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        value = _validate_body(body)
        try:
            todo = require_visible_todo(self._session, actor, todo_id)
            comment = comment_repo.add_comment(self._session, tenant_id=actor.tenant_id, todo_id=todo.id, author_id=actor.user_id, body=value)
            self._session.flush()
            record_todo_audit(self._session, actor, ACTION_TODO_COMMENT_CREATE, todo.id, {"comment_id": str(comment.id), "body_length": len(value)})
            self._session.flush()
            view = self._view(actor, comment)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("ToDo のコメントを投稿しました: tenant_id=%s todo_id=%s comment_id=%s", actor.tenant_id, view.todo_id, view.id)
        return view

    def update_comment(self, todo_id: uuid.UUID, comment_id: uuid.UUID, *, expected_version: int, body: str) -> TodoCommentView:
        """コメントの本文を編集してコミットする（AP-CMT-03。投稿者のみ。``tenant_admin`` も他人のコメントは編集できない）。

        同じ本文なら何もしない（``version`` / ``edited_at`` も変えず、監査ログも残さない）。権限の確認はその前に行う。

        Args:
            todo_id: ToDo ID。
            comment_id: コメント ID。
            expected_version: ``If-Match`` のコメントの版。
            body: 本文（前後の空白を除いて 1〜4,000 文字）。

        Returns:
            TodoCommentView: 編集後のコメント。

        Raises:
            TodoValidationError: 本文が不正（``field="body"``）。
            TodoNotFoundError: ToDo が存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
            TodoCommentNotFoundError: コメントが存在しない（別の ToDo のもの・論理削除済みを含む）。
            TodoCommentVersionConflictError: 版が一致しない。
            TodoPermissionDeniedError: 投稿者でない（``operation="edit_comment"``）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        value = _validate_body(body)
        try:
            comment = self._lock_comment(actor, todo_id, comment_id, expected_version, TodoOperation.EDIT_COMMENT)
            if comment.body == value:
                view = self._view(actor, comment)
                self._session.rollback()
                return view
            before_length, before_version = len(comment.body), comment.version
            comment.body = value
            comment.version = before_version + 1
            comment.edited_at = utc_now()
            payload = {"comment_id": str(comment.id), "body_length": change(before_length, len(value)), "version": change(before_version, comment.version)}
            record_todo_audit(self._session, actor, ACTION_TODO_COMMENT_UPDATE, comment.todo_id, payload)
            self._session.flush()
            view = self._view(actor, comment)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("ToDo のコメントを編集しました: tenant_id=%s todo_id=%s comment_id=%s", actor.tenant_id, view.todo_id, view.id)
        return view

    def delete_comment(self, todo_id: uuid.UUID, comment_id: uuid.UUID, *, expected_version: int) -> None:
        """コメントを論理削除してコミットする（AP-CMT-04, 05。投稿者と ``tenant_admin``）。

        Args:
            todo_id: ToDo ID。
            comment_id: コメント ID。
            expected_version: ``If-Match`` のコメントの版。

        Raises:
            TodoNotFoundError: ToDo が存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
            TodoCommentNotFoundError: コメントが存在しない（別の ToDo のもの・論理削除済みを含む）。
            TodoCommentVersionConflictError: 版が一致しない。
            TodoPermissionDeniedError: 投稿者でも ``tenant_admin`` でもない（``operation="delete_comment"``）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        try:
            comment = self._lock_comment(actor, todo_id, comment_id, expected_version, TodoOperation.DELETE_COMMENT)
            before_version = comment.version
            comment.deleted_at = utc_now()
            comment.version = before_version + 1
            payload = {"comment_id": str(comment.id), "author_id": str(comment.author_id), "body_length": len(comment.body), "version": change(before_version, comment.version)}
            record_todo_audit(self._session, actor, ACTION_TODO_COMMENT_DELETE, comment.todo_id, payload)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("ToDo のコメントを削除しました（論理削除）: tenant_id=%s todo_id=%s comment_id=%s", actor.tenant_id, todo_id, comment_id)

    # ------------------------------------------------------------------ 補助
    def _lock_comment(self, actor: TodoActor, todo_id: uuid.UUID, comment_id: uuid.UUID, expected_version: int, operation: TodoOperation) -> TTodoComment:
        """閲覧できる ToDo のコメントを行ロックして取得し、版と権限を確認する（404 todo → 404 comment → 412 → 403）。"""
        todo = require_visible_todo(self._session, actor, todo_id)
        comment = comment_repo.get_comment(self._session, actor.tenant_id, todo.id, comment_id, for_update=True) if isinstance(comment_id, uuid.UUID) else None
        if comment is None:
            raise TodoCommentNotFoundError(todo.id, comment_id)
        if comment.version != expected_version:
            raise TodoCommentVersionConflictError(comment.id, expected_version, comment.version)
        if not comment_permissions(actor, author_id=comment.author_id).allows(operation):
            raise TodoPermissionDeniedError(todo.id, operation.value)
        return comment

    def _view(self, actor: TodoActor, comment: TTodoComment) -> TodoCommentView:
        """1 件のコメントのビュー（投稿者の表示名を読み込む）。"""
        users = load_user_names(self._session, actor.tenant_id, [comment.author_id])
        return _comment_view(actor, comment, user_name_or_unknown(users, comment.author_id))


def _comment_view(actor: TodoActor, comment: TTodoComment, author: UserNameView) -> TodoCommentView:
    """コメントのビューを作る。"""
    return TodoCommentView(
        id=comment.id,
        todo_id=comment.todo_id,
        author=author,
        body=comment.body,
        version=comment.version,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        edited_at=comment.edited_at,
        permissions=comment_permissions(actor, author_id=comment.author_id),
    )


def _validate_body(body: Any) -> str:
    """本文（前後の空白を除いて 1〜4,000 文字。改行・タブ以外の制御文字は不可。AP-CMT-01）。"""
    if not isinstance(body, str) or not body.strip():
        raise TodoValidationError("body", "required")
    value = body.strip()
    if len(value) > TODO_COMMENT_BODY_MAX_LENGTH:
        raise TodoValidationError("body", "too_long")
    if has_control_chars(value, allow_whitespace=True):
        raise TodoValidationError("body", "format")
    return value
