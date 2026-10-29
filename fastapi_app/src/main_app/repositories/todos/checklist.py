#!/usr/bin/env python
# coding:utf-8
"""ToDo のチェックリスト項目（``t_todo_checklist_item``。AP-CHK）と、チェックリスト全体の版（``t_todo.checklist_version``）の DB アクセス。

- 項目は物理削除（ToDoApp.md §10 #23）。``position`` は 0 からの連番をアプリ層で保つ。一意制約
  ``(tenant_id, todo_id, position)`` は ``DEFERRABLE INITIALLY DEFERRED`` のため、1 トランザクション内の付け替えは途中で重なってよい
- ``position`` の付け替え（挿入・詰め直し・並べ替え）は Core の ``UPDATE`` で行い、項目の ``updated_at`` / ``version`` は変えない
  （並びの変更はチェックリスト全体の版で扱う。§10 #17）
- :func:`bump_checklist_version` は ``t_todo`` の ``version`` / ``updated_at`` を変えない（AP-CHK-08。``updated_at`` の ``onupdate`` を打ち消す）
- 呼び出し側が ``t_todo`` を ``FOR UPDATE`` で取得して、同じ ToDo のチェックリストの変更を直列化すること（上限・位置の整合のため）

セッションは ``app_runtime`` + テナントコンテキスト下（RLS）であること。コミットはしない。
"""
import uuid
from collections.abc import Sequence

from sqlalchemy import case, delete, func, update
from sqlmodel import Session, col, select

from main_app.models import TTodo, TTodoChecklistItem


def list_items(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID) -> list[TTodoChecklistItem]:
    """ToDo の項目を ``position`` の順に取得する（Core の ``UPDATE`` の後でも最新の値を読むよう、読み込み済みの行を上書きする）。"""
    statement = (
        select(TTodoChecklistItem)
        .where(col(TTodoChecklistItem.tenant_id) == tenant_id, col(TTodoChecklistItem.todo_id) == todo_id)
        .order_by(col(TTodoChecklistItem.position), col(TTodoChecklistItem.id))
        .execution_options(populate_existing=True)
    )
    return list(session.exec(statement).all())


def get_item(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, item_id: uuid.UUID, *, for_update: bool = False) -> TTodoChecklistItem | None:
    """ToDo の項目を取得する（別の ToDo の項目は ``None``）。"""
    statement = select(TTodoChecklistItem).where(
        col(TTodoChecklistItem.id) == item_id, col(TTodoChecklistItem.tenant_id) == tenant_id, col(TTodoChecklistItem.todo_id) == todo_id
    )
    if for_update:
        statement = statement.with_for_update()
    return session.exec(statement.execution_options(populate_existing=True)).first()


def count_items(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID) -> int:
    """ToDo の項目数。"""
    statement = select(func.count()).select_from(TTodoChecklistItem).where(col(TTodoChecklistItem.tenant_id) == tenant_id, col(TTodoChecklistItem.todo_id) == todo_id)
    return int(session.exec(statement).one())


def shift_positions(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, *, from_position: int, delta: int) -> None:
    """``position >= from_position`` の項目の ``position`` に ``delta`` を足す（挿入の場所空け・削除後の詰め直し）。"""
    statement = (
        update(TTodoChecklistItem)
        .where(col(TTodoChecklistItem.tenant_id) == tenant_id, col(TTodoChecklistItem.todo_id) == todo_id, col(TTodoChecklistItem.position) >= from_position)
        .values(position=col(TTodoChecklistItem.position) + delta, updated_at=col(TTodoChecklistItem.updated_at))
    )
    session.connection().execute(statement)


def set_positions(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, item_ids: Sequence[uuid.UUID]) -> None:
    """``item_ids`` の順に ``position`` を 0 から振り直す（並べ替え。SQL 1 本）。``item_ids`` は ToDo の全項目であること。"""
    if not item_ids:
        return
    position = case({item_id: index for index, item_id in enumerate(item_ids)}, value=col(TTodoChecklistItem.id))
    statement = (
        update(TTodoChecklistItem)
        .where(col(TTodoChecklistItem.tenant_id) == tenant_id, col(TTodoChecklistItem.todo_id) == todo_id, col(TTodoChecklistItem.id).in_(list(item_ids)))
        .values(position=position, updated_at=col(TTodoChecklistItem.updated_at))
    )
    session.connection().execute(statement)


def add_item(session: Session, *, tenant_id: uuid.UUID, todo_id: uuid.UUID, title: str, position: int, created_by: uuid.UUID) -> TTodoChecklistItem:
    """項目を追加する（flush はしない）。``position`` の場所は呼び出し側が空けておく。"""
    item = TTodoChecklistItem(tenant_id=tenant_id, todo_id=todo_id, title=title, position=position, created_by=created_by, updated_by=created_by)
    session.add(item)
    return item


def delete_item(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, item_id: uuid.UUID) -> int:
    """項目を物理削除する。

    Returns:
        int: 削除した行数。
    """
    statement = delete(TTodoChecklistItem).where(col(TTodoChecklistItem.tenant_id) == tenant_id, col(TTodoChecklistItem.todo_id) == todo_id, col(TTodoChecklistItem.id) == item_id)
    return int(session.connection().execute(statement).rowcount or 0)


def bump_checklist_version(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, *, new_version: int) -> None:
    """``t_todo.checklist_version`` を ``new_version`` にする（``version`` / ``updated_at`` / ``updated_by`` は変えない）。"""
    statement = (
        update(TTodo)
        .where(col(TTodo.tenant_id) == tenant_id, col(TTodo.id) == todo_id)
        .values(checklist_version=new_version, updated_at=col(TTodo.updated_at))
    )
    session.connection().execute(statement)
