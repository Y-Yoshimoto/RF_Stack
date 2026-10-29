#!/usr/bin/env python
# coding:utf-8
"""ToDo（``t_todo``）・担当者（``t_todo_assignee``）・公開先組織（``t_todo_organization``）の DB アクセスと、
一覧の件数（総件数・チェックリストの進捗・コメント数）・ホームの要約の集計。

- 閲覧範囲の条件は受け取るだけで、ここでは定義しない（:mod:`main_app.services.todo_policy`。AP-VIS-09）
- 既定のクエリは論理削除されていない ToDo（``deleted_at IS NULL``）に限る。``tenant_id`` の条件も明示し、
  02 §4.7 / ToDoApp.md §5 の部分インデックス（``(tenant_id, status)`` / ``(tenant_id, due_date)`` / ``(tenant_id, created_by)``、
  担当者の ``(tenant_id, user_id)``）を使える形にする（RLS の条件だけでは部分インデックスの述語に一致しない）
- 一覧の担当者・公開先組織・件数（:func:`load_todo_counters`）は ToDo の ID の集合でまとめて取得する（N+1 にしない）

セッションは ``app_runtime`` + テナントコンテキスト下（RLS）であること。コミットはしない。
"""
import datetime as dt
import uuid
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, case, delete, func, or_, tuple_
from sqlalchemy.orm import defer
from sqlalchemy.sql import ColumnElement
from sqlmodel import Session, col, select

from main_app.models import TodoPriority, TodoStatus, TodoVisibility, TOrganization, TTodo, TTodoAssignee, TTodoChecklistItem, TTodoComment, TTodoOrganization, TUser
from main_app.repositories.keyset import ListSort, Page

# 一覧の並び替えキー（AP-TODO-06）と既定値
TODO_SORT_KEYS: tuple[str, ...] = ("due_date", "priority", "created_at", "updated_at")
DEFAULT_TODO_SORT = "-created_at"

# 優先度の順位（文字列の辞書順では low < medium < high にならないため）
PRIORITY_RANK: dict[str, int] = {TodoPriority.LOW.value: 1, TodoPriority.MEDIUM.value: 2, TodoPriority.HIGH.value: 3}


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoListFilter:
    """一覧の絞り込み（AP-TODO-06）。``None`` は絞り込まない。

    Attributes:
        statuses: ステータス（いずれか）。
        priorities: 優先度（いずれか）。
        assignee_id: 担当者に含まれるユーザー。
        organization_id: 公開先に含まれる（有効な）組織。
        due_before: 期限がこの日以前（この日を含む。期限なしは除く）。
        due_after: 期限がこの日以降（この日を含む。期限なしは除く）。
        title_query: タイトルの部分一致（大文字小文字を区別しない）。
    """

    statuses: tuple[str, ...] | None = None
    priorities: tuple[str, ...] | None = None
    assignee_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    due_before: dt.date | None = None
    due_after: dt.date | None = None
    title_query: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AssigneeRow:
    """担当者の行とユーザーの表示用の値。"""

    todo_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    is_active: bool
    assigned_at: dt.datetime
    assigned_by: uuid.UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class OrganizationRow:
    """公開先組織（有効なもの）の表示用の値。"""

    todo_id: uuid.UUID
    organization_id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoCounters:
    """ToDo ごとの件数（一覧・詳細の表示用）。

    Attributes:
        done_count: 完了したチェックリスト項目の数。
        total_count: チェックリスト項目の数。
        comment_count: コメント数（論理削除済みを除く）。
    """

    done_count: int = 0
    total_count: int = 0
    comment_count: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class SummaryCounts:
    """ホームの要約の件数（:func:`summary_counts`。いずれも完了を除く）。"""

    assigned_open: int
    assigned_in_progress: int
    assigned_overdue: int
    assigned_due_soon: int
    created_open: int
    created_in_progress: int
    created_overdue: int


# --------------------------------------------------------------------------- ToDo


def _active_todos(tenant_id: uuid.UUID) -> list[ColumnElement[bool]]:
    """論理削除されていない、テナントの ToDo の条件（部分インデックスの述語と一致させる）。"""
    return [col(TTodo.tenant_id) == tenant_id, col(TTodo.deleted_at).is_(None)]


def get_todo(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, *, condition: ColumnElement[bool], for_update: bool = False) -> TTodo | None:
    """論理削除されておらず、``condition``（閲覧範囲）を満たす ToDo を取得する。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID（コンテキストの値）。
        todo_id: ToDo ID。
        condition: 閲覧範囲の条件（``todo_policy.visible_condition``）。
        for_update: ``t_todo`` の行ロック（``SELECT ... FOR UPDATE OF t_todo``）を取るか。

    Returns:
        TTodo | None: ToDo。存在しない・他テナント・論理削除済み・閲覧範囲外は ``None``。
    """
    statement = select(TTodo).where(col(TTodo.id) == todo_id, *_active_todos(tenant_id), condition)
    if for_update:
        statement = statement.with_for_update(of=TTodo)
    return session.exec(statement).first()


def _sort_expression(key: str) -> ColumnElement[Any]:
    """並び替えキーの式。"""
    match key:
        case "due_date":
            return col(TTodo.due_date)
        case "priority":
            return case(PRIORITY_RANK, value=col(TTodo.priority), else_=0)
        case "created_at":
            return col(TTodo.created_at)
        case "updated_at":
            return col(TTodo.updated_at)
    raise ValueError(f"unsupported sort key: {key}")


def _keyset_condition(sort: ListSort, after: tuple[Any, uuid.UUID]) -> ColumnElement[bool]:
    """起点より後の行の条件。

    ``due_date`` は NULL を含むため、昇順は NULLS LAST、降順は NULLS FIRST（PostgreSQL の既定と同じ。
    昇順の逆順になる）として、NULL を行値の比較に入れずに条件を組み立てる。
    """
    value, last_id = after
    id_column = col(TTodo.id)
    if sort.key == "due_date":
        due = col(TTodo.due_date)
        if not sort.descending:
            if value is None:
                return and_(due.is_(None), id_column > last_id)
            return or_(due > value, and_(due == value, id_column > last_id), due.is_(None))
        if value is None:
            return or_(and_(due.is_(None), id_column < last_id), due.is_not(None))
        return and_(due.is_not(None), or_(due < value, and_(due == value, id_column < last_id)))
    expression = _sort_expression(sort.key)
    sort_value = PRIORITY_RANK[value] if sort.key == "priority" else value
    key = tuple_(expression, id_column)
    return key < tuple_(sort_value, last_id) if sort.descending else key > tuple_(sort_value, last_id)


def _order_by(sort: ListSort) -> list[Any]:
    """ORDER BY（最後に ``id`` を付けて順序を安定させる。03 §3）。"""
    expression = _sort_expression(sort.key)
    if sort.descending:
        primary = expression.desc().nulls_first() if sort.key == "due_date" else expression.desc()
        return [primary, col(TTodo.id).desc()]
    primary = expression.asc().nulls_last() if sort.key == "due_date" else expression.asc()
    return [primary, col(TTodo.id).asc()]


def _sort_value(todo: TTodo, key: str) -> Any:
    """次のページの起点に使う並び替えキーの値（``priority`` は文字列の値のまま返す）。"""
    return getattr(todo, key)


def _filter_conditions(tenant_id: uuid.UUID, filters: TodoListFilter) -> list[ColumnElement[bool]]:
    """絞り込みの条件。"""
    conditions: list[ColumnElement[bool]] = []
    if filters.statuses:
        conditions.append(col(TTodo.status).in_(filters.statuses))
    if filters.priorities:
        conditions.append(col(TTodo.priority).in_(filters.priorities))
    if filters.due_before is not None:
        conditions.append(col(TTodo.due_date) <= filters.due_before)
    if filters.due_after is not None:
        conditions.append(col(TTodo.due_date) >= filters.due_after)
    if filters.title_query:
        escaped = filters.title_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(col(TTodo.title).ilike(f"%{escaped}%", escape="\\"))
    if filters.assignee_id is not None:
        assigned = select(col(TTodoAssignee.todo_id)).where(col(TTodoAssignee.tenant_id) == tenant_id, col(TTodoAssignee.user_id) == filters.assignee_id)
        conditions.append(col(TTodo.id).in_(assigned))
    if filters.organization_id is not None:
        shared = (
            select(col(TTodoOrganization.todo_id))
            .join(TOrganization, and_(col(TOrganization.tenant_id) == col(TTodoOrganization.tenant_id), col(TOrganization.id) == col(TTodoOrganization.organization_id)))
            .where(col(TTodoOrganization.tenant_id) == tenant_id, col(TTodoOrganization.organization_id) == filters.organization_id, col(TOrganization.deleted_at).is_(None))
        )
        conditions.append(and_(col(TTodo.visibility) == TodoVisibility.ORGANIZATION.value, col(TTodo.id).in_(shared)))
    return conditions


def list_todos(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    conditions: Sequence[ColumnElement[bool]],
    filters: TodoListFilter,
    sort: ListSort,
    after: tuple[Any, uuid.UUID] | None,
    limit: int,
) -> Page[TTodo]:
    """ToDo の一覧をキーセット方式で取得する（説明 ``description`` は読み込まない）。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID（コンテキストの値）。
        conditions: 閲覧範囲・表示範囲の条件（``todo_policy``）。
        filters: 絞り込み。
        sort: 並び順（キーは :data:`TODO_SORT_KEYS`）。
        after: 起点（``(並び替えキーの値, id)``。値は ``due_date`` が ``date | None``、``priority`` が値の文字列、日時は ``datetime``）。
        limit: 件数（補正済み）。

    Returns:
        Page[TTodo]: ページ。``next_after`` の値の型は ``after`` と同じ。
    """
    statement = select(TTodo).options(defer(col(TTodo.description))).where(*_active_todos(tenant_id), *conditions, *_filter_conditions(tenant_id, filters))
    if after is not None:
        statement = statement.where(_keyset_condition(sort, after))
    statement = statement.order_by(*_order_by(sort)).limit(limit + 1)
    rows = session.exec(statement).all()
    items = list(rows[:limit])
    if len(rows) <= limit or not items:
        return Page(items=items, next_after=None)
    last = items[-1]
    return Page(items=items, next_after=(_sort_value(last, sort.key), last.id))


def count_todos(session: Session, tenant_id: uuid.UUID, *, conditions: Sequence[ColumnElement[bool]], filters: TodoListFilter) -> int:
    """一覧の総件数（:func:`list_todos` と同じ条件。カーソル・並び順・件数には依存しない。SQL 1 本）。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID（コンテキストの値）。
        conditions: 閲覧範囲・表示範囲の条件（``todo_policy``）。
        filters: 絞り込み。

    Returns:
        int: 件数。
    """
    statement = select(func.count()).select_from(TTodo).where(*_active_todos(tenant_id), *conditions, *_filter_conditions(tenant_id, filters))
    return int(session.exec(statement).one())


def load_todo_counters(session: Session, tenant_id: uuid.UUID, todo_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, TodoCounters]:
    """ToDo ごとのチェックリストの進捗とコメント数をまとめて取得する（SQL 1 本。項目・コメントを ToDo ごとに集計して外部結合する）。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID。
        todo_ids: ToDo ID（閲覧範囲の確認は呼び出し側）。

    Returns:
        dict[uuid.UUID, TodoCounters]: ToDo ID → 件数（テナント内に無い ID はキーが無い）。
    """
    if not todo_ids:
        return {}
    ids = list(todo_ids)
    checklist = (
        select(col(TTodoChecklistItem.todo_id).label("todo_id"), func.count().label("total"), func.count().filter(col(TTodoChecklistItem.is_done)).label("done"))
        .where(col(TTodoChecklistItem.tenant_id) == tenant_id, col(TTodoChecklistItem.todo_id).in_(ids))
        .group_by(col(TTodoChecklistItem.todo_id))
        .subquery("checklist")
    )
    comments = (
        select(col(TTodoComment.todo_id).label("todo_id"), func.count().label("total"))
        .where(col(TTodoComment.tenant_id) == tenant_id, col(TTodoComment.todo_id).in_(ids), col(TTodoComment.deleted_at).is_(None))
        .group_by(col(TTodoComment.todo_id))
        .subquery("comments")
    )
    statement = (
        select(col(TTodo.id), func.coalesce(checklist.c.done, 0), func.coalesce(checklist.c.total, 0), func.coalesce(comments.c.total, 0))
        .select_from(TTodo)
        .outerjoin(checklist, checklist.c.todo_id == col(TTodo.id))
        .outerjoin(comments, comments.c.todo_id == col(TTodo.id))
        .where(col(TTodo.tenant_id) == tenant_id, col(TTodo.id).in_(ids))
    )
    return {todo_id: TodoCounters(done_count=int(done), total_count=int(total), comment_count=int(comment_count)) for todo_id, done, total, comment_count in session.exec(statement).all()}


def summary_counts(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    visible: ColumnElement[bool],
    assigned: ColumnElement[bool],
    created: ColumnElement[bool],
    today: dt.date,
    due_soon_until: dt.date,
) -> SummaryCounts:
    """ホームの要約の件数を ``count(*) FILTER`` で数える（SQL 1 本。論理削除済み・完了を除く。ToDoApp.md §10 #21）。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID。
        visible: 閲覧範囲の条件（``todo_policy.visible_condition``）。
        assigned: 操作者が担当している条件（``todo_policy.scope_condition(actor, ASSIGNED)``）。
        created: 操作者が作成した条件（``todo_policy.scope_condition(actor, MINE)``）。
        today: 今日。期限切れは ``due_date < today``。
        due_soon_until: 期限間近の終端（期限間近は ``today <= due_date <= due_soon_until``）。

    Returns:
        SummaryCounts: 件数。
    """
    status, due = col(TTodo.status), col(TTodo.due_date)
    is_open, is_in_progress = status == TodoStatus.OPEN.value, status == TodoStatus.IN_PROGRESS.value
    overdue = due < today
    due_soon = and_(due >= today, due <= due_soon_until)
    statement = select(
        func.count().filter(and_(assigned, is_open)),
        func.count().filter(and_(assigned, is_in_progress)),
        func.count().filter(and_(assigned, overdue)),
        func.count().filter(and_(assigned, due_soon)),
        func.count().filter(and_(created, is_open)),
        func.count().filter(and_(created, is_in_progress)),
        func.count().filter(and_(created, overdue)),
    ).where(*_active_todos(tenant_id), visible, status != TodoStatus.DONE.value, or_(assigned, created))
    row = session.exec(statement).one()
    return SummaryCounts(
        assigned_open=int(row[0]),
        assigned_in_progress=int(row[1]),
        assigned_overdue=int(row[2]),
        assigned_due_soon=int(row[3]),
        created_open=int(row[4]),
        created_in_progress=int(row[5]),
        created_overdue=int(row[6]),
    )


# --------------------------------------------------------------------------- 担当者


def load_assignees(session: Session, tenant_id: uuid.UUID, todo_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, list[AssigneeRow]]:
    """ToDo ごとの担当者（ユーザーの表示名・有効/無効付き）をまとめて取得する（割り当て日時順）。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID。
        todo_ids: ToDo ID。

    Returns:
        dict[uuid.UUID, list[AssigneeRow]]: ToDo ID → 担当者（担当者がいない ToDo はキーが無い）。
    """
    if not todo_ids:
        return {}
    statement = (
        select(TTodoAssignee.todo_id, TTodoAssignee.user_id, TTodoAssignee.assigned_at, TTodoAssignee.assigned_by, TUser.display_name, TUser.is_active)
        .join(TUser, and_(col(TUser.tenant_id) == col(TTodoAssignee.tenant_id), col(TUser.id) == col(TTodoAssignee.user_id)))
        .where(col(TTodoAssignee.tenant_id) == tenant_id, col(TTodoAssignee.todo_id).in_(list(todo_ids)))
        .order_by(col(TTodoAssignee.todo_id), col(TTodoAssignee.assigned_at), col(TTodoAssignee.user_id))
    )
    result: dict[uuid.UUID, list[AssigneeRow]] = defaultdict(list)
    for todo_id, user_id, assigned_at, assigned_by, display_name, is_active in session.exec(statement).all():
        result[todo_id].append(AssigneeRow(todo_id=todo_id, user_id=user_id, display_name=display_name, is_active=is_active, assigned_at=assigned_at, assigned_by=assigned_by))
    return dict(result)


def list_assignee_ids(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID) -> list[uuid.UUID]:
    """ToDo の担当者のユーザー ID（割り当て日時順）。"""
    statement = (
        select(TTodoAssignee.user_id)
        .where(col(TTodoAssignee.tenant_id) == tenant_id, col(TTodoAssignee.todo_id) == todo_id)
        .order_by(col(TTodoAssignee.assigned_at), col(TTodoAssignee.user_id))
    )
    return list(session.exec(statement).all())


def add_assignees(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, user_ids: Collection[uuid.UUID], *, assigned_by: uuid.UUID) -> None:
    """担当者を追加する（複合外部キーにより他テナントのユーザーは DB でも拒否される）。"""
    for user_id in user_ids:
        session.add(TTodoAssignee(tenant_id=tenant_id, todo_id=todo_id, user_id=user_id, assigned_by=assigned_by))


def remove_assignees(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, user_ids: Collection[uuid.UUID]) -> int:
    """担当者を外す。残る担当者の行は触らない（``assigned_at`` を保つ）。

    Returns:
        int: 削除した行数。
    """
    if not user_ids:
        return 0
    statement = delete(TTodoAssignee).where(col(TTodoAssignee.tenant_id) == tenant_id, col(TTodoAssignee.todo_id) == todo_id, col(TTodoAssignee.user_id).in_(list(user_ids)))
    return int(session.connection().execute(statement).rowcount or 0)


def find_user_states(session: Session, user_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, bool]:
    """指定したユーザーのうちテナント内に存在するものの有効/無効を返す。

    Returns:
        dict[uuid.UUID, bool]: ユーザー ID → ``is_active``（存在しないユーザーはキーが無い）。
    """
    if not user_ids:
        return {}
    statement = select(TUser.id, TUser.is_active).where(col(TUser.id).in_(list(user_ids)))
    return {user_id: is_active for user_id, is_active in session.exec(statement).all()}


# --------------------------------------------------------------------------- 公開先組織


def load_active_organizations(session: Session, tenant_id: uuid.UUID, todo_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, list[OrganizationRow]]:
    """ToDo ごとの公開先組織のうち、**有効な**（論理削除されていない）ものをまとめて取得する（組織名順）。

    Returns:
        dict[uuid.UUID, list[OrganizationRow]]: ToDo ID → 組織（有効な公開先が無い ToDo はキーが無い）。
    """
    if not todo_ids:
        return {}
    statement = (
        select(TTodoOrganization.todo_id, TOrganization.id, TOrganization.name)
        .join(TOrganization, and_(col(TOrganization.tenant_id) == col(TTodoOrganization.tenant_id), col(TOrganization.id) == col(TTodoOrganization.organization_id)))
        .where(col(TTodoOrganization.tenant_id) == tenant_id, col(TTodoOrganization.todo_id).in_(list(todo_ids)), col(TOrganization.deleted_at).is_(None))
        .order_by(col(TTodoOrganization.todo_id), col(TOrganization.name), col(TOrganization.id))
    )
    result: dict[uuid.UUID, list[OrganizationRow]] = defaultdict(list)
    for todo_id, organization_id, name in session.exec(statement).all():
        result[todo_id].append(OrganizationRow(todo_id=todo_id, organization_id=organization_id, name=name))
    return dict(result)


def list_organization_links(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID) -> dict[uuid.UUID, bool]:
    """ToDo の公開先組織の行（論理削除された組織を含む）。

    Returns:
        dict[uuid.UUID, bool]: 組織 ID → 有効か（``False`` = 論理削除済み）。
    """
    statement = (
        select(TTodoOrganization.organization_id, TOrganization.deleted_at)
        .join(TOrganization, and_(col(TOrganization.tenant_id) == col(TTodoOrganization.tenant_id), col(TOrganization.id) == col(TTodoOrganization.organization_id)))
        .where(col(TTodoOrganization.tenant_id) == tenant_id, col(TTodoOrganization.todo_id) == todo_id)
        .order_by(col(TTodoOrganization.organization_id))
    )
    return {organization_id: deleted_at is None for organization_id, deleted_at in session.exec(statement).all()}


def find_active_organization_ids(session: Session, organization_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """指定した組織のうち、テナント内に存在し論理削除されていないものの ID。"""
    if not organization_ids:
        return set()
    statement = select(TOrganization.id).where(col(TOrganization.id).in_(list(organization_ids)), col(TOrganization.deleted_at).is_(None))
    return set(session.exec(statement).all())


def add_organizations(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, organization_ids: Collection[uuid.UUID]) -> None:
    """公開先組織を追加する。"""
    for organization_id in organization_ids:
        session.add(TTodoOrganization(tenant_id=tenant_id, todo_id=todo_id, organization_id=organization_id))


def remove_organizations(session: Session, tenant_id: uuid.UUID, todo_id: uuid.UUID, organization_ids: Collection[uuid.UUID]) -> int:
    """公開先組織を外す。

    Returns:
        int: 削除した行数。
    """
    if not organization_ids:
        return 0
    statement = delete(TTodoOrganization).where(
        col(TTodoOrganization.tenant_id) == tenant_id, col(TTodoOrganization.todo_id) == todo_id, col(TTodoOrganization.organization_id).in_(list(organization_ids))
    )
    return int(session.connection().execute(statement).rowcount or 0)
