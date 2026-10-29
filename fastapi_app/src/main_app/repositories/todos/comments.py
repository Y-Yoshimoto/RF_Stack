#!/usr/bin/env python
# coding:utf-8
"""ToDo のコメント（``t_todo_comment``。AP-CMT）の DB アクセス。

- 既定のクエリは論理削除されていないコメント（``deleted_at IS NULL``）に限る（AP-CMT-05）。``tenant_id`` の条件も明示し、
  一覧の部分インデックス ``ix_t_todo_comment_tenant_id_todo_id_created_at_id``（``deleted_at IS NULL``）を使える形にする
- 一覧は古い順（``created_at``, ``id`` の昇順。ToDoApp.md §10 #19）のキーセット方式で、投稿者の表示名を結合して 1 クエリで取得する
- 閲覧範囲の確認は呼び出し側（ToDo を閲覧範囲の条件付きで取得してから呼ぶ。AP-CMT-06）

セッションは ``app_runtime`` + テナントコンテキスト下（RLS）であること。コミットはしない。
"""
import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import and_, tuple_
from sqlmodel import Session, col, select

from main_app.models import TTodoComment, TUser
from main_app.repositories.keyset import Page


@dataclass(frozen=True, slots=True, kw_only=True)
class CommentRow:
    """コメントの行と投稿者の表示用の値。"""

    comment: TTodoComment
    author_display_name: str
    author_is_active: bool


def list_comments(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, *, after: tuple[dt.datetime, uuid.UUID] | None, limit: int) -> Page[CommentRow]:
    """ToDo のコメントを古い順にキーセット方式で取得する（論理削除済みを除く。投稿者の表示名を結合する）。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID（コンテキストの値）。
        todo_id: ToDo ID。
        after: 起点（``(created_at, id)``。この組より後を返す）。
        limit: 件数（補正済み）。

    Returns:
        Page[CommentRow]: ページ（``next_after`` は ``(created_at, id)``）。
    """
    statement = (
        select(TTodoComment, TUser.display_name, TUser.is_active)
        .join(TUser, and_(col(TUser.tenant_id) == col(TTodoComment.tenant_id), col(TUser.id) == col(TTodoComment.author_id)))
        .where(col(TTodoComment.tenant_id) == tenant_id, col(TTodoComment.todo_id) == todo_id, col(TTodoComment.deleted_at).is_(None))
    )
    if after is not None:
        statement = statement.where(tuple_(col(TTodoComment.created_at), col(TTodoComment.id)) > tuple_(*after))
    statement = statement.order_by(col(TTodoComment.created_at).asc(), col(TTodoComment.id).asc()).limit(limit + 1)
    rows = [CommentRow(comment=comment, author_display_name=name, author_is_active=active) for comment, name, active in session.exec(statement).all()]
    items = rows[:limit]
    if len(rows) <= limit or not items:
        return Page(items=items, next_after=None)
    last = items[-1].comment
    return Page(items=items, next_after=(last.created_at, last.id))


def get_comment(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, comment_id: uuid.UUID, *, for_update: bool = False) -> TTodoComment | None:
    """ToDo のコメントを取得する（論理削除済み・別の ToDo のコメントは ``None``）。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID。
        todo_id: ToDo ID（コメントがこの ToDo のものであること）。
        comment_id: コメント ID。
        for_update: 行ロック（``SELECT ... FOR UPDATE``）を取るか。

    Returns:
        TTodoComment | None: コメント。
    """
    statement = select(TTodoComment).where(
        col(TTodoComment.id) == comment_id, col(TTodoComment.tenant_id) == tenant_id, col(TTodoComment.todo_id) == todo_id, col(TTodoComment.deleted_at).is_(None)
    )
    if for_update:
        statement = statement.with_for_update()
    return session.exec(statement).first()


def add_comment(session: Session, *, tenant_id: uuid.UUID, todo_id: uuid.UUID, author_id: uuid.UUID, body: str) -> TTodoComment:
    """コメントを追加する（flush はしない）。

    Returns:
        TTodoComment: 追加した行。
    """
    comment = TTodoComment(tenant_id=tenant_id, todo_id=todo_id, author_id=author_id, body=body)
    session.add(comment)
    return comment
