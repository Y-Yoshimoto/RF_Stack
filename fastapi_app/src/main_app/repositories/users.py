#!/usr/bin/env python
# coding:utf-8
"""AP のユーザー（``t_user``）の DB アクセス。

セッションは ``app_runtime`` + テナントコンテキスト下（RLS）であること。``tenant_id`` の条件は RLS に任せず、
書き込みでは呼び出し側が明示的に設定する（WITH CHECK でも拒否される）。コミットはしない。
"""
import uuid
from collections.abc import Collection
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from main_app.models import TUser
from main_app.repositories.keyset import ListSort, Page, apply_keyset, build_page

# 一覧の並び替えキー（03 §3。NOT NULL の列のみ）
USER_SORT_COLUMNS: dict[str, Any] = {
    "display_name": col(TUser.display_name),
    "created_at": col(TUser.created_at),
}
DEFAULT_USER_SORT = "display_name"


def get_user(session: Session, user_id: uuid.UUID, *, for_update: bool = False) -> TUser | None:
    """ユーザーを ID で取得する（他テナントの行は RLS により見えない）。

    Args:
        session: AP のセッション。
        user_id: ユーザー ID。
        for_update: 行ロック（``SELECT ... FOR UPDATE``）を取るか。

    Returns:
        TUser | None: ユーザー。
    """
    statement = select(TUser).where(TUser.id == user_id)
    if for_update:
        statement = statement.with_for_update()
    return session.exec(statement).first()


def get_user_by_subject(session: Session, idp_subject: str, *, for_update: bool = False) -> TUser | None:
    """IdP の利用者 ID（``sub``）でユーザーを取得する。

    Args:
        session: AP のセッション。
        idp_subject: IdP の利用者 ID。
        for_update: 行ロックを取るか。

    Returns:
        TUser | None: ユーザー。
    """
    statement = select(TUser).where(TUser.idp_subject == idp_subject)
    if for_update:
        statement = statement.with_for_update()
    return session.exec(statement).first()


def find_user_id_by_email(session: Session, email: str) -> uuid.UUID | None:
    """メールアドレス（大文字小文字を区別しない）でユーザー ID を探す。

    Args:
        session: AP のセッション。
        email: メールアドレス。

    Returns:
        uuid.UUID | None: ユーザー ID。
    """
    return session.exec(select(TUser.id).where(func.lower(TUser.email) == email.lower())).first()


def find_existing_user_ids(session: Session, user_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """指定した ID のうち、テナント内に存在するユーザーの ID を返す。

    Args:
        session: AP のセッション。
        user_ids: ユーザー ID。

    Returns:
        set[uuid.UUID]: 存在するユーザー ID。
    """
    if not user_ids:
        return set()
    return set(session.exec(select(TUser.id).where(col(TUser.id).in_(list(user_ids)))).all())


def list_users(session: Session, *, sort: ListSort, after: tuple[Any, uuid.UUID] | None, limit: int, is_active: bool | None = None) -> Page[TUser]:
    """ユーザーの一覧をキーセット方式で取得する。

    Args:
        session: AP のセッション。
        sort: 並び順（キーは :data:`USER_SORT_COLUMNS`）。
        after: 起点。
        limit: 件数（補正済み）。
        is_active: 有効/無効で絞り込む（``None`` なら絞り込まない）。

    Returns:
        Page[TUser]: ページ。
    """
    statement = select(TUser)
    if is_active is not None:
        statement = statement.where(TUser.is_active == is_active)
    statement = apply_keyset(statement, USER_SORT_COLUMNS[sort.key], col(TUser.id), sort, after, limit)
    return build_page(session.exec(statement).all(), limit, sort.key)
