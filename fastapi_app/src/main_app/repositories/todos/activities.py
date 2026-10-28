#!/usr/bin/env python
# coding:utf-8
"""ToDo アクティビティ（``t_todo_activity``。AP-ACT-01..04）の追記と一覧。

利用者に見せる変更履歴（AP 監査ログとは別。03 §7）。ToDo の変更と同じトランザクションで追記する（AP-ACT-03）。
一覧はインデックス ``ix_t_todo_activity_tenant_id_todo_id_created_at`` を使う（``tenant_id`` と ``todo_id`` の条件 + ``created_at`` 順）。
閲覧範囲の確認は呼び出し側（ToDo を閲覧範囲の条件付きで取得してから呼ぶ）。コミットはしない。
"""
import uuid
from typing import Any

from sqlmodel import Session, col, select

from main_app.models import TodoActivityAction, TTodoActivity
from main_app.repositories.keyset import ListSort, Page, apply_keyset, build_page

# 一覧の並び順（新しい順。同じトランザクションの行は created_at が同じため、UUIDv7 の id で記録順に並ぶ）
ACTIVITY_SORT = ListSort(key="created_at", descending=True)


def add_activity(session: Session, *, tenant_id: uuid.UUID, todo_id: uuid.UUID, actor_id: uuid.UUID, action: TodoActivityAction, payload: dict[str, Any]) -> TTodoActivity:
    """アクティビティを 1 行追加する（flush はしない）。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID（コンテキストの値）。
        todo_id: ToDo ID。
        actor_id: 操作者のユーザー ID。
        action: 種別。
        payload: 変更前後の差分（JSON に変換できる値のみ）。

    Returns:
        TTodoActivity: 追加した行。
    """
    row = TTodoActivity(tenant_id=tenant_id, todo_id=todo_id, actor_id=actor_id, action=action.value, payload=payload)
    session.add(row)
    return row


def list_activities(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, *, after: tuple[Any, uuid.UUID] | None, limit: int) -> Page[TTodoActivity]:
    """ToDo のアクティビティを新しい順にキーセット方式で取得する。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID。
        todo_id: ToDo ID。
        after: 起点（``(created_at, id)``）。
        limit: 件数（補正済み）。

    Returns:
        Page[TTodoActivity]: ページ（``next_after`` は ``(created_at, id)``）。
    """
    statement = select(TTodoActivity).where(col(TTodoActivity.tenant_id) == tenant_id, col(TTodoActivity.todo_id) == todo_id)
    statement = apply_keyset(statement, col(TTodoActivity.created_at), col(TTodoActivity.id), ACTIVITY_SORT, after, limit)
    return build_page(session.exec(statement).all(), limit, ACTIVITY_SORT.key)
