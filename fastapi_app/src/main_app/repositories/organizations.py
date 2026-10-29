#!/usr/bin/env python
# coding:utf-8
"""AP の組織（``t_organization``）と組織メンバー（``t_organization_member``）の DB アクセス。

既定のクエリは論理削除されていない行（``deleted_at IS NULL``。03 §5.1）だけを対象にする。
セッションは ``app_runtime`` + テナントコンテキスト下（RLS）であること。コミットはしない。
"""
import uuid
from collections.abc import Collection
from typing import Any

from sqlalchemy import and_, delete, func
from sqlmodel import Session, col, select

from main_app.models import TOrganization, TOrganizationMember
from main_app.repositories.keyset import ListSort, Page, apply_keyset, build_page

# 一覧の並び替えキー（03 §3。NOT NULL の列のみ）
ORGANIZATION_SORT_COLUMNS: dict[str, Any] = {
    "name": col(TOrganization.name),
    "created_at": col(TOrganization.created_at),
}
DEFAULT_ORGANIZATION_SORT = "name"


def get_organization(session: Session, organization_id: uuid.UUID, *, for_update: bool = False) -> TOrganization | None:
    """有効な（論理削除されていない）組織を ID で取得する。

    Args:
        session: AP のセッション。
        organization_id: 組織 ID。
        for_update: 行ロック（``SELECT ... FOR UPDATE``）を取るか。

    Returns:
        TOrganization | None: 組織。論理削除済み・他テナントは ``None``。
    """
    statement = select(TOrganization).where(TOrganization.id == organization_id, col(TOrganization.deleted_at).is_(None))
    if for_update:
        statement = statement.with_for_update()
    return session.exec(statement).first()


def find_active_organization_id_by_name(session: Session, name: str, *, exclude_id: uuid.UUID | None = None) -> uuid.UUID | None:
    """有効な組織の中から、名前（大文字小文字を区別しない）が一致する組織の ID を探す。

    Args:
        session: AP のセッション。
        name: 組織名。
        exclude_id: 除外する組織 ID（名前の変更で自分自身を除く）。

    Returns:
        uuid.UUID | None: 組織 ID。
    """
    statement = select(TOrganization.id).where(func.lower(TOrganization.name) == name.lower(), col(TOrganization.deleted_at).is_(None))
    if exclude_id is not None:
        statement = statement.where(TOrganization.id != exclude_id)
    return session.exec(statement).first()


def any_organization_exists(session: Session) -> bool:
    """テナントに組織の行が 1 件でもあるか（論理削除済みを含む）。デフォルト組織の作成の判定に使う。

    Args:
        session: AP のセッション。

    Returns:
        bool: 1 件以上あれば ``True``。
    """
    return session.exec(select(TOrganization.id).limit(1)).first() is not None


def list_organizations(session: Session, *, sort: ListSort, after: tuple[Any, uuid.UUID] | None, limit: int) -> Page[TOrganization]:
    """有効な組織の一覧をキーセット方式で取得する。

    Args:
        session: AP のセッション。
        sort: 並び順（キーは :data:`ORGANIZATION_SORT_COLUMNS`）。
        after: 起点。
        limit: 件数（補正済み）。

    Returns:
        Page[TOrganization]: ページ。
    """
    statement = select(TOrganization).where(col(TOrganization.deleted_at).is_(None))
    statement = apply_keyset(statement, ORGANIZATION_SORT_COLUMNS[sort.key], col(TOrganization.id), sort, after, limit)
    return build_page(session.exec(statement).all(), limit, sort.key)


def list_member_ids(session: Session, organization_id: uuid.UUID) -> list[uuid.UUID]:
    """組織のメンバーのユーザー ID を返す（ID 順）。

    Args:
        session: AP のセッション。
        organization_id: 組織 ID。

    Returns:
        list[uuid.UUID]: ユーザー ID。
    """
    statement = select(TOrganizationMember.user_id).where(TOrganizationMember.organization_id == organization_id).order_by(col(TOrganizationMember.user_id))
    return list(session.exec(statement).all())


def list_active_organizations_of_user(session: Session, user_id: uuid.UUID) -> list[TOrganization]:
    """ユーザーが所属する有効な（論理削除されていない）組織を返す（組織名順、同名は ID 順）。

    逆引きは ``t_organization_member`` の ``(tenant_id, user_id)`` のインデックスを使う。

    Args:
        session: AP のセッション。
        user_id: ユーザー ID。

    Returns:
        list[TOrganization]: 組織。所属が無い・存在しないユーザーは空。
    """
    statement = (
        select(TOrganization)
        .join(TOrganizationMember, and_(col(TOrganizationMember.tenant_id) == col(TOrganization.tenant_id), col(TOrganizationMember.organization_id) == col(TOrganization.id)))
        .where(col(TOrganizationMember.user_id) == user_id, col(TOrganization.deleted_at).is_(None))
        .order_by(col(TOrganization.name), col(TOrganization.id))
    )
    return list(session.exec(statement).all())


def add_members(session: Session, tenant_id: uuid.UUID, organization_id: uuid.UUID, user_ids: Collection[uuid.UUID]) -> None:
    """組織にメンバーを追加する（複合外部キーにより他テナントのユーザーは DB でも拒否される）。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID（コンテキストの値）。
        organization_id: 組織 ID。
        user_ids: 追加するユーザー ID（未所属のもの）。
    """
    for user_id in user_ids:
        session.add(TOrganizationMember(tenant_id=tenant_id, organization_id=organization_id, user_id=user_id))


def remove_members(session: Session, organization_id: uuid.UUID, user_ids: Collection[uuid.UUID]) -> int:
    """組織からメンバーを外す。

    Args:
        session: AP のセッション。
        organization_id: 組織 ID。
        user_ids: 外すユーザー ID。

    Returns:
        int: 削除した行数。
    """
    if not user_ids:
        return 0
    statement = delete(TOrganizationMember).where(col(TOrganizationMember.organization_id) == organization_id, col(TOrganizationMember.user_id).in_(list(user_ids)))
    return int(session.connection().execute(statement).rowcount or 0)
