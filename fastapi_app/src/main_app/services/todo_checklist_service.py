#!/usr/bin/env python
# coding:utf-8
"""ToDo のチェックリストのサービス（docs/spec/ToDoApp.md §4.6 AP-CHK。``/api/v1/todos/{id}/checklist`` から使う）。

FastAPI に依存しない。AP のセッション（テナントコンテキスト下、``app_runtime``）と操作者（``t_user.id`` とロール）を受け取り、
**コミットはサービスが行う**。テナントはコンテキストから得る（引数に取らない）。

使用例（ルーターから）::

    service = TodoChecklistService(session, actor_user_id=active_user.id, actor_roles=roles)
    checklist = service.add_item(todo_id, title="見積もりの送付")
    item = checklist.items[-1]
    checklist = service.update_item(todo_id, item.id, expected_version=item.version, is_done=True)
    checklist = service.reorder_items(todo_id, expected_version=checklist.version, item_ids=[...])

公開メソッドと例外（HTTP ステータスは :mod:`main_app.services.errors`）。戻り値はすべてチェックリスト全体の :class:`TodoChecklistView`:

| メソッド | 例外 |
| --- | --- |
| :meth:`TodoChecklistService.get_checklist` | ``TodoNotFoundError`` |
| :meth:`TodoChecklistService.add_item` | ``TodoValidationError``（``title`` / ``position``、上限超過は ``items`` / ``too_many``）, ``TodoNotFoundError``, ``TodoPermissionDeniedError``（``edit_checklist``） |
| :meth:`TodoChecklistService.update_item` | ``TodoValidationError``（``title`` / ``is_done``）, ``TodoNotFoundError``, ``TodoChecklistItemNotFoundError``, ``TodoChecklistVersionConflictError``（item）, ``TodoPermissionDeniedError`` |
| :meth:`TodoChecklistService.delete_item` | ``TodoNotFoundError``, ``TodoChecklistItemNotFoundError``, ``TodoChecklistVersionConflictError``（item）, ``TodoPermissionDeniedError``（``edit_checklist``） |
| :meth:`TodoChecklistService.reorder_items` | ``TodoValidationError``（``item_ids``。集合の不一致は ``mismatch``）, ``TodoNotFoundError``, ``TodoChecklistVersionConflictError``（checklist）, ``TodoPermissionDeniedError`` |

判定の順序（変更系）: 入力の形式（422）→ ToDo の閲覧範囲（404 ``todo_not_found``）→ 項目（404 ``todo_checklist_item_not_found``。別の ToDo の項目・
削除済み・他テナントを区別しない）→ 版（412）→ 権限（403）→ 現在の状態に依存する検証（422。項目数の上限、並べ替えの集合の一致）。

- 権限（ToDoApp.md §3）: 追加・名前変更・削除・並べ替えは作成者と ``tenant_admin``（``edit_checklist``）、完了・未完了の切り替えは
  作成者・担当者・``tenant_admin``（``check_checklist_item``）。``update_item`` は**実際に変わる項目**で判定する（§10 #18。名前を変えずに
  完了だけを切り替えるなら担当者も通る。値が変わらなければ何もせず、版も変えない）
- 直列化: 変更系は ``t_todo`` を ``FOR UPDATE`` で取得してから項目を数え・並べる（同時の追加で上限・位置が崩れないように）
- 版（§10 #17）: 項目の名前変更・完了の切り替え・削除は項目の ``version``（+1）。追加・削除・並べ替えで ``t_todo.checklist_version`` を +1 し、
  並べ替えはそれを ``expected_version`` に取る。追加は版を取らない
- 位置: ``position`` は 0 からの連番。追加は指定位置（省略・末尾より後は末尾）に挿入し、削除後は詰め直す（§10 #23。物理削除）
- 上限: 1 件の ToDo につき 100 項目（AP-CHK-01）。超える追加は ``TodoValidationError(field="items", reason="too_many")``
- 完了の記録: 完了にすると ``done_at`` / ``done_by`` を設定し、未完了に戻すと消す（AP-CHK-04）。全項目を完了しても ToDo のステータスは変えない（AP-CHK-05）
- アクティビティ ``checklist_changed``（AP-ACT-05。``payload.op`` は ``added`` / ``renamed`` / ``removed`` / ``checked`` / ``unchecked``、
  ``item_id``、``title``、``renamed`` は ``before`` / ``after``）。1 回の更新で名前と完了を変えれば 2 行。並べ替えは記録しない（§10 #20）
- 監査ログ ``todo.checklist_change``（``target_type = 'todo'``。``payload`` は ``ops``・``item_id``・版。並べ替えも ``ops=["reordered"]`` で記録する）
- ToDo 本体の ``version`` / ``updated_at`` / ``updated_by`` は変えない（AP-CHK-08、§10 #16）
"""
import logging
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from main_app.models import TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH, TODO_CHECKLIST_ITEMS_MAX, TodoActivityAction, TTodo, TTodoChecklistItem
from main_app.repositories.todos import checklist as checklist_repo
from main_app.repositories.todos import todos as todo_repo
from main_app.services.common import UNSET, Maybe, change, utc_now
from main_app.services.errors import TodoChecklistItemNotFoundError, TodoChecklistVersionConflictError, TodoPermissionDeniedError, TodoValidationError
from main_app.services.todo_access import (
    actor_of,
    has_control_chars,
    load_user_names,
    record_activity,
    record_todo_audit,
    require_visible_todo,
    user_name_or_unknown,
    validate_actor_args,
)
from main_app.services.todo_policy import TodoActor, TodoOperation, TodoPermissions, todo_permissions
from main_app.services.todo_views import TodoChecklistItemView, TodoChecklistView

__all__ = ["TodoChecklistItemView", "TodoChecklistService", "TodoChecklistView"]

logger = logging.getLogger(__name__)

# 監査ログの操作
ACTION_TODO_CHECKLIST_CHANGE = "todo.checklist_change"

# アクティビティの payload.op（§10 #20）と、監査ログだけに記録する並べ替え
OP_ADDED = "added"
OP_RENAMED = "renamed"
OP_REMOVED = "removed"
OP_CHECKED = "checked"
OP_UNCHECKED = "unchecked"
OP_REORDERED = "reordered"


class TodoChecklistService:
    """ToDo のチェックリスト項目の参照・追加・更新・削除・並べ替え（1 リクエストごとにインスタンスを作る）。

    Args:
        session: AP のセッション（テナントコンテキスト下）。
        actor_user_id: 操作者の AP のユーザー ID（``t_user.id``。IdP の ``sub`` ではない）。
        actor_roles: 操作者のテナントのロール（``tenant_admin`` / ``member``。セッションの ``roles``）。
    """

    def __init__(self, session: Session, *, actor_user_id: uuid.UUID, actor_roles: Collection[str]) -> None:
        """依存を保持する。"""
        self._session = session
        self._actor_user_id, self._actor_roles = validate_actor_args(actor_user_id, actor_roles)

    # ------------------------------------------------------------------ 参照
    def get_checklist(self, todo_id: uuid.UUID) -> TodoChecklistView:
        """ToDo のチェックリスト（項目は ``position`` の順。操作者の権限付き）。

        Raises:
            TodoNotFoundError: ToDo が存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        todo = require_visible_todo(self._session, actor, todo_id)
        return self._view(actor, todo, version=todo.checklist_version, permissions=self._permissions(actor, todo))

    # ------------------------------------------------------------------ 変更
    def add_item(self, todo_id: uuid.UUID, *, title: str, position: int | None = None) -> TodoChecklistView:
        """項目を追加してコミットする（AP-CHK-01..03。``checklist_version`` を +1）。

        Args:
            todo_id: ToDo ID。
            title: 項目名（前後の空白を除いて 1〜200 文字。制御文字は不可）。
            position: 挿入する位置（0 始まり。``None``・末尾より後は末尾）。

        Returns:
            TodoChecklistView: 追加後のチェックリスト。

        Raises:
            TodoValidationError: 入力が不正（``title`` / ``position``）、項目数が上限（``field="items"``、``reason="too_many"``）。
            TodoNotFoundError: ToDo が存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
            TodoPermissionDeniedError: 作成者・``tenant_admin`` でない（``operation="edit_checklist"``）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        value = _validate_title(title)
        requested_position = _validate_position(position)
        try:
            todo = require_visible_todo(self._session, actor, todo_id, for_update=True)
            permissions = self._require(actor, todo, TodoOperation.EDIT_CHECKLIST)
            count = checklist_repo.count_items(self._session, actor.tenant_id, todo.id)
            if count >= TODO_CHECKLIST_ITEMS_MAX:
                raise TodoValidationError("items", "too_many")
            target = count if requested_position is None else min(requested_position, count)
            if target < count:
                checklist_repo.shift_positions(self._session, actor.tenant_id, todo.id, from_position=target, delta=1)
            item = checklist_repo.add_item(self._session, tenant_id=actor.tenant_id, todo_id=todo.id, title=value, position=target, created_by=actor.user_id)
            self._session.flush()
            version = self._bump(actor, todo)
            record_activity(self._session, actor, todo.id, TodoActivityAction.CHECKLIST_CHANGED, {"op": OP_ADDED, "item_id": str(item.id), "title": value})
            self._audit(actor, todo, [OP_ADDED], item_id=item.id, extra={"position": target, "checklist_version": version})
            self._session.flush()
            view = self._view(actor, todo, version=version.after, permissions=permissions)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("チェックリスト項目を追加しました: tenant_id=%s todo_id=%s item_id=%s", actor.tenant_id, view.todo_id, item.id)
        return view

    def update_item(
        self,
        todo_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        expected_version: int,
        title: Maybe[str] = UNSET,
        is_done: Maybe[bool] = UNSET,
    ) -> TodoChecklistView:
        """項目の名前・完了を部分更新してコミットする（AP-CHK-03, 04。``UNSET`` の項目は変えない。項目の ``version`` を +1）。

        権限は実際に変わる項目で判定する（名前が変われば ``edit_checklist``、完了が変われば ``check_checklist_item``。§10 #18）。
        どちらも変わらなければ何もしない（版も変えない）。

        Args:
            todo_id: ToDo ID。
            item_id: 項目 ID。
            expected_version: ``If-Match`` の項目の版。
            title: 項目名（前後の空白を除いて 1〜200 文字）。
            is_done: 完了か。

        Returns:
            TodoChecklistView: 更新後のチェックリスト（``version`` = ``checklist_version`` は変わらない）。

        Raises:
            TodoValidationError: 入力が不正（``title`` / ``is_done``）。
            TodoNotFoundError: ToDo が存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
            TodoChecklistItemNotFoundError: 項目が存在しない（別の ToDo の項目を含む）。
            TodoChecklistVersionConflictError: 項目の版が一致しない（``target="item"``）。
            TodoPermissionDeniedError: 変わる項目に対する権限が無い（``edit_checklist`` / ``check_checklist_item``）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        new_title = UNSET if title is UNSET else _validate_title(title)
        if is_done is not UNSET and not isinstance(is_done, bool):
            raise TodoValidationError("is_done", "type")
        try:
            todo, item = self._lock_item(actor, todo_id, item_id, expected_version)
            permissions = self._permissions(actor, todo)
            renamed = new_title is not UNSET and new_title != item.title
            toggled = is_done is not UNSET and is_done != item.is_done
            required = ([TodoOperation.EDIT_CHECKLIST] if renamed else []) + ([TodoOperation.CHECK_CHECKLIST_ITEM] if toggled else [])
            for operation in required:
                if not permissions.allows(operation):
                    raise TodoPermissionDeniedError(todo.id, operation.value)
            if not required:
                view = self._view(actor, todo, version=todo.checklist_version, permissions=permissions)
                self._session.rollback()
                return view

            ops: list[str] = []
            before_title, before_version = item.title, item.version
            if renamed:
                item.title = new_title
                ops.append(OP_RENAMED)
            if toggled:
                item.is_done = bool(is_done)
                item.done_at = utc_now() if item.is_done else None
                item.done_by = actor.user_id if item.is_done else None
                ops.append(OP_CHECKED if item.is_done else OP_UNCHECKED)
            item.version = before_version + 1
            item.updated_by = actor.user_id
            for op in ops:
                payload: dict[str, Any] = {"op": op, "item_id": str(item.id), "title": item.title}
                if op == OP_RENAMED:
                    payload.update(before=before_title, after=item.title)
                record_activity(self._session, actor, todo.id, TodoActivityAction.CHECKLIST_CHANGED, payload)
            self._audit(actor, todo, ops, item_id=item.id, extra={"version": change(before_version, item.version)})
            self._session.flush()
            view = self._view(actor, todo, version=todo.checklist_version, permissions=permissions)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("チェックリスト項目を更新しました: tenant_id=%s todo_id=%s item_id=%s ops=%s", actor.tenant_id, view.todo_id, item_id, ",".join(ops))
        return view

    def delete_item(self, todo_id: uuid.UUID, item_id: uuid.UUID, *, expected_version: int) -> TodoChecklistView:
        """項目を物理削除し、``position`` を詰め直してコミットする（§10 #23。``checklist_version`` を +1）。

        Args:
            todo_id: ToDo ID。
            item_id: 項目 ID。
            expected_version: ``If-Match`` の項目の版。

        Returns:
            TodoChecklistView: 削除後のチェックリスト。

        Raises:
            TodoNotFoundError: ToDo が存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
            TodoChecklistItemNotFoundError: 項目が存在しない（別の ToDo の項目を含む）。
            TodoChecklistVersionConflictError: 項目の版が一致しない（``target="item"``）。
            TodoPermissionDeniedError: 作成者・``tenant_admin`` でない（``operation="edit_checklist"``）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        try:
            todo, item = self._lock_item(actor, todo_id, item_id, expected_version)
            permissions = self._require(actor, todo, TodoOperation.EDIT_CHECKLIST)
            removed_id, removed_title, removed_position = item.id, item.title, item.position
            self._session.expunge(item)
            checklist_repo.delete_item(self._session, actor.tenant_id, todo.id, removed_id)
            checklist_repo.shift_positions(self._session, actor.tenant_id, todo.id, from_position=removed_position + 1, delta=-1)
            version = self._bump(actor, todo)
            record_activity(self._session, actor, todo.id, TodoActivityAction.CHECKLIST_CHANGED, {"op": OP_REMOVED, "item_id": str(removed_id), "title": removed_title})
            self._audit(actor, todo, [OP_REMOVED], item_id=removed_id, extra={"checklist_version": version})
            self._session.flush()
            view = self._view(actor, todo, version=version.after, permissions=permissions)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("チェックリスト項目を削除しました: tenant_id=%s todo_id=%s item_id=%s", actor.tenant_id, view.todo_id, removed_id)
        return view

    def reorder_items(self, todo_id: uuid.UUID, *, expected_version: int, item_ids: Sequence[uuid.UUID]) -> TodoChecklistView:
        """項目の並びを ``item_ids`` の順に置き換えてコミットする（AP-CHK-03, 07。``checklist_version`` を +1）。

        ``item_ids`` は現在の項目 ID の集合と完全に一致すること（過不足・重複は ``mismatch``）。並びが変わらなければ何もしない（版も変えない）。
        アクティビティには記録しない（§10 #20）。

        Args:
            todo_id: ToDo ID。
            expected_version: ``If-Match`` のチェックリストの版（``checklist_version``）。
            item_ids: 項目 ID の新しい並び（全件）。

        Returns:
            TodoChecklistView: 並べ替え後のチェックリスト。

        Raises:
            TodoValidationError: ``item_ids`` の型・形式が不正、現在の項目と集合が一致しない（``field="item_ids"``、``reason="mismatch"``）。
            TodoNotFoundError: ToDo が存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
            TodoChecklistVersionConflictError: チェックリストの版が一致しない（``target="checklist"``）。
            TodoPermissionDeniedError: 作成者・``tenant_admin`` でない（``operation="edit_checklist"``）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        desired = _validate_item_ids(item_ids)
        try:
            todo = require_visible_todo(self._session, actor, todo_id, for_update=True)
            if todo.checklist_version != expected_version:
                raise TodoChecklistVersionConflictError(todo.id, expected_version, todo.checklist_version, target="checklist")
            permissions = self._require(actor, todo, TodoOperation.EDIT_CHECKLIST)
            current = [item.id for item in checklist_repo.list_items(self._session, actor.tenant_id, todo.id)]
            if len(desired) != len(current) or set(desired) != set(current):
                raise TodoValidationError("item_ids", "mismatch")
            if desired == current:
                view = self._view(actor, todo, version=todo.checklist_version, permissions=permissions)
                self._session.rollback()
                return view
            checklist_repo.set_positions(self._session, actor.tenant_id, todo.id, desired)
            version = self._bump(actor, todo)
            self._audit(actor, todo, [OP_REORDERED], item_id=None, extra={"checklist_version": version})
            self._session.flush()
            view = self._view(actor, todo, version=version.after, permissions=permissions)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("チェックリスト項目を並べ替えました: tenant_id=%s todo_id=%s items=%d", actor.tenant_id, view.todo_id, len(desired))
        return view

    # ------------------------------------------------------------------ 補助
    def _permissions(self, actor: TodoActor, todo: TTodo) -> TodoPermissions:
        """ToDo に対する操作者の権限（担当者を読み込む）。"""
        assignee_ids = todo_repo.list_assignee_ids(self._session, actor.tenant_id, todo.id)
        return todo_permissions(actor, created_by=todo.created_by, assignee_ids=assignee_ids)

    def _require(self, actor: TodoActor, todo: TTodo, operation: TodoOperation) -> TodoPermissions:
        """権限を確認する（無ければ :class:`TodoPermissionDeniedError`）。"""
        permissions = self._permissions(actor, todo)
        if not permissions.allows(operation):
            raise TodoPermissionDeniedError(todo.id, operation.value)
        return permissions

    def _lock_item(self, actor: TodoActor, todo_id: uuid.UUID, item_id: uuid.UUID, expected_version: int) -> tuple[TTodo, TTodoChecklistItem]:
        """ToDo を行ロックして項目を取得し、項目の版を確認する（404 todo → 404 item → 412）。"""
        todo = require_visible_todo(self._session, actor, todo_id, for_update=True)
        item = checklist_repo.get_item(self._session, actor.tenant_id, todo.id, item_id, for_update=True) if isinstance(item_id, uuid.UUID) else None
        if item is None:
            raise TodoChecklistItemNotFoundError(todo.id, item_id)
        if item.version != expected_version:
            raise TodoChecklistVersionConflictError(item.id, expected_version, item.version, target="item")
        return todo, item

    def _bump(self, actor: TodoActor, todo: TTodo) -> "_VersionChange":
        """``checklist_version`` を +1 する（ToDo 本体の版・更新日時は変えない）。"""
        self._session.flush()
        before = todo.checklist_version
        checklist_repo.bump_checklist_version(self._session, actor.tenant_id, todo.id, new_version=before + 1)
        return _VersionChange(before=before, after=before + 1)

    def _audit(self, actor: TodoActor, todo: TTodo, ops: Sequence[str], *, item_id: uuid.UUID | None, extra: dict[str, Any]) -> None:
        """監査ログ ``todo.checklist_change`` を追記する。"""
        payload: dict[str, Any] = {"ops": list(ops)}
        if item_id is not None:
            payload["item_id"] = str(item_id)
        for key, value in extra.items():
            payload[key] = change(value.before, value.after) if isinstance(value, _VersionChange) else value
        record_todo_audit(self._session, actor, ACTION_TODO_CHECKLIST_CHANGE, todo.id, payload)

    def _view(self, actor: TodoActor, todo: TTodo, *, version: int, permissions: TodoPermissions) -> TodoChecklistView:
        """チェックリスト全体のビュー（項目と完了した人の表示名を読み込む）。"""
        self._session.flush()
        items = checklist_repo.list_items(self._session, actor.tenant_id, todo.id)
        users = load_user_names(self._session, actor.tenant_id, {item.done_by for item in items if item.done_by is not None})
        views = tuple(
            TodoChecklistItemView(
                id=item.id,
                title=item.title,
                position=item.position,
                is_done=item.is_done,
                done_at=item.done_at,
                done_by=user_name_or_unknown(users, item.done_by) if item.done_by is not None else None,
                version=item.version,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        )
        return TodoChecklistView(
            todo_id=todo.id,
            version=version,
            items=views,
            done_count=sum(1 for item in views if item.is_done),
            total_count=len(views),
            permissions=permissions.checklist,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class _VersionChange:
    """版の変更前後（監査ログの ``payload`` 用）。"""

    before: int
    after: int


def _validate_title(title: Any) -> str:
    """項目名（前後の空白を除いて 1〜200 文字。制御文字は不可。AP-CHK-02）。"""
    if not isinstance(title, str) or not title.strip():
        raise TodoValidationError("title", "required")
    value = title.strip()
    if len(value) > TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH:
        raise TodoValidationError("title", "too_long")
    if has_control_chars(value, allow_whitespace=False):
        raise TodoValidationError("title", "format")
    return value


def _validate_position(position: Any) -> int | None:
    """挿入する位置（0 以上の整数。``None`` は末尾）。"""
    if position is None:
        return None
    if isinstance(position, bool) or not isinstance(position, int):
        raise TodoValidationError("position", "type")
    if position < 0:
        raise TodoValidationError("position", "out_of_range")
    return position


def _validate_item_ids(item_ids: Any) -> list[uuid.UUID]:
    """並べ替えの項目 ID（UUID の列。重複・過不足は状態に依存する検証で ``mismatch`` にする）。"""
    if item_ids is None or isinstance(item_ids, str | bytes) or not isinstance(item_ids, Sequence):
        raise TodoValidationError("item_ids", "type")
    if not all(isinstance(item_id, uuid.UUID) for item_id in item_ids):
        raise TodoValidationError("item_ids", "format")
    if len(item_ids) > TODO_CHECKLIST_ITEMS_MAX:
        raise TodoValidationError("item_ids", "mismatch")
    return list(item_ids)
