#!/usr/bin/env python
# coding:utf-8
"""ToDo のサービス（docs/spec/ToDoApp.md §3、§4: AP-TODO / AP-VIS / AP-ASN / AP-ACT。``/api/v1/todos`` から使う）。

FastAPI に依存しない。AP のセッション（テナントコンテキスト下、``app_runtime``）と操作者（``t_user.id`` とロール）を受け取り、
**コミットはサービスが行う**。テナントはコンテキストから得る（引数に取らない）。

使用例（ルーターから）::

    service = TodoService(session, actor_user_id=active_user.id, actor_roles=active_user.claims["roles"])
    page = service.list_todos(scope="assigned", status=["open", "in_progress"], sort="due_date", limit=50)
    view = service.create_todo(title="見積もりを作る", visibility="organization", organization_ids=[org_id])
    view = service.update_todo(view.id, expected_version=view.version, status="done")

公開メソッドと例外（HTTP ステータスは :mod:`main_app.services.errors`）:

| メソッド | 例外 |
| --- | --- |
| :meth:`TodoService.list_todos` | ``TodoValidationError``（``scope`` / ``status`` / ``priority`` / ``q`` / ``sort`` / ``cursor`` 等）。戻り値は ``Page`` に総件数 ``total`` を加えた :class:`TodoListPage` |
| :meth:`TodoService.summarize` | ``TodoValidationError``（``today`` / ``due_soon_days``）。ホームの要約 :class:`TodoSummaryView`（AP-UX-01） |
| :meth:`TodoService.get_todo` | ``TodoNotFoundError`` |
| :meth:`TodoService.create_todo` | ``TodoValidationError``, ``InvalidTodoOrganizationsError``, ``InvalidTodoAssigneesError`` |
| :meth:`TodoService.update_todo` | ``TodoValidationError``, ``TodoNotFoundError``, ``TodoVersionConflictError``, ``TodoPermissionDeniedError``, ``InvalidTodoOrganizationsError`` |
| :meth:`TodoService.delete_todo` | ``TodoNotFoundError``, ``TodoVersionConflictError``, ``TodoPermissionDeniedError`` |
| :meth:`TodoService.set_assignees` | ``TodoValidationError``, ``TodoNotFoundError``, ``TodoVersionConflictError``, ``TodoPermissionDeniedError``, ``InvalidTodoAssigneesError`` |
| :meth:`TodoService.list_activities` | ``TodoNotFoundError``, ``TodoValidationError``（``cursor``）。戻り値は ``Page`` に参照先ユーザーの表示名 ``users`` を加えた :class:`TodoActivityPage` |

判定の順序（変更系）: 入力の形式（422）→ 閲覧範囲（404。他テナント・存在しない・論理削除済みと同じ）→ 版（412）→
操作の権限（403）→ 現在の状態に依存する検証（422。組織・担当者の存在や有効性）。権限は**実際に値が変わる項目**で判定する
（同じ値を送った項目は変更とみなさない。編集画面が全項目を送っても、担当者のステータス変更は通る）。

- 閲覧範囲と権限の定義は :mod:`main_app.services.todo_policy` だけにある（一覧の SQL 条件と単体の取得で同じ条件を使う。AP-VIS-09）
- 変更は行ロック（``SELECT ... FOR UPDATE OF t_todo``）の下で ``version`` を確認し、+1 する（03 §5.2）。値が変わらない更新は
  何もしない（``version`` も変えず、アクティビティ・監査ログも残さない）
- アクティビティ（AP-ACT-01..03）は種別ごとに 1 行（1 回の更新で項目とステータスを変えれば ``updated`` と ``status_changed`` の 2 行）。
  AP 監査ログ（AP-ACT-04）は ``todo.create`` / ``todo.update``（項目・ステータス）/ ``todo.change_visibility`` / ``todo.set_assignees`` / ``todo.delete``。
  監査ログには説明の本文を残さない（変更の有無だけ）
- 一覧・詳細のビューには作成者・最終更新者（``UserNameView``）、チェックリストの進捗、コメント数を付ける。一覧では 1 ページの ToDo の ID で
  まとめて取得する（ToDo 本体・担当者・公開先組織・件数・ユーザー名の 5 クエリ。``include_total`` で総件数の 1 クエリが加わる）
- 操作者の作成と閲覧できる ToDo の取得は :mod:`main_app.services.todo_access`（コメント・チェックリストのサービスと共有）。
  コメントは :mod:`~main_app.services.todo_comment_service`、チェックリストは :mod:`~main_app.services.todo_checklist_service`
"""
import datetime as dt
import enum
import logging
import uuid
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session

from main_app.models import TodoActivityAction, TodoPriority, TodoStatus, TodoVisibility, TTodo
from main_app.models.todo import TODO_ASSIGNEES_MAX, TODO_DESCRIPTION_MAX_LENGTH, TODO_TITLE_MAX_LENGTH
from main_app.repositories.keyset import ListSort, normalize_limit
from main_app.repositories.todos import activities as activity_repo
from main_app.repositories.todos import todos as todo_repo
from main_app.repositories.todos.todos import DEFAULT_TODO_SORT, PRIORITY_RANK, TODO_SORT_KEYS, AssigneeRow, OrganizationRow, TodoCounters, TodoListFilter
from main_app.services.common import UNSET, Maybe, UserNameView, change, record_audit, utc_now
from main_app.services.errors import (
    InvalidTodoAssigneesError,
    InvalidTodoOrganizationsError,
    TodoPermissionDeniedError,
    TodoValidationError,
    TodoVersionConflictError,
)
from main_app.services.todo_access import (
    AUDIT_TARGET_TYPE,
    actor_of,
    has_control_chars,
    load_user_names,
    normalize_datetime_after,
    parse_aware_datetime,
    record_activity,
    require_visible_todo,
    split_after,
    to_json,
    user_name_or_unknown,
    validate_actor_args,
)
from main_app.services.todo_policy import TodoActor, TodoOperation, TodoPermissions, TodoScope, effective_visibility, scope_condition, todo_permissions, visible_condition
from main_app.services.todo_views import (
    TodoActivityPage,
    TodoActivityView,
    TodoAssigneeView,
    TodoChecklistProgressView,
    TodoDetailView,
    TodoListPage,
    TodoOrganizationView,
    TodoSummaryAssignedView,
    TodoSummaryCreatedView,
    TodoSummaryView,
    TodoView,
)
from modules.tenancy.context import require_tenant_context

__all__ = [
    "DEFAULT_TODO_SORT",
    "TODO_SORT_KEYS",
    "TodoActivityPage",
    "TodoActivityView",
    "TodoAssigneeView",
    "TodoDetailView",
    "TodoListPage",
    "TodoOrganizationView",
    "TodoPermissions",
    "TodoScope",
    "TodoService",
    "TodoSummaryView",
    "TodoView",
]

logger = logging.getLogger(__name__)

# 公開先組織の上限（仕様に上限は無いが、入力の大きさを抑えるために置く）
TODO_ORGANIZATIONS_MAX = 100

# 監査ログの操作（03 §7、AP-ACT-04）
ACTION_TODO_CREATE = "todo.create"
ACTION_TODO_UPDATE = "todo.update"
ACTION_TODO_CHANGE_VISIBILITY = "todo.change_visibility"
ACTION_TODO_SET_ASSIGNEES = "todo.set_assignees"
ACTION_TODO_DELETE = "todo.delete"

# ホームの要約の期限間近の日数（既定と範囲。ToDoApp.md §10 #21）
DEFAULT_DUE_SOON_DAYS = 7
DUE_SOON_DAYS_MIN = 1
DUE_SOON_DAYS_MAX = 30

# 項目（AP-ACT の ``updated``。権限は ``edit_fields``）
_FIELD_NAMES: tuple[str, ...] = ("title", "description", "due_date", "priority")


class TodoService:
    """ToDo の作成・参照・更新・削除・担当者・アクティビティ（1 リクエストごとにインスタンスを作る）。

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
    def list_todos(
        self,
        *,
        scope: TodoScope | str = TodoScope.ALL,
        status: Iterable[TodoStatus | str] | TodoStatus | str | None = None,
        priority: Iterable[TodoPriority | str] | TodoPriority | str | None = None,
        q: str | None = None,
        organization_id: uuid.UUID | None = None,
        assignee_id: uuid.UUID | None = None,
        due_before: dt.date | None = None,
        due_after: dt.date | None = None,
        sort: str = DEFAULT_TODO_SORT,
        limit: int = 50,
        after: tuple[Any, uuid.UUID] | None = None,
        include_total: bool = False,
    ) -> TodoListPage:
        """閲覧できる ToDo の一覧（AP-TODO-06, 07。論理削除済みを除く）。

        Args:
            scope: 表示範囲（``mine`` / ``assigned`` / ``shared`` / ``all``）。いずれも閲覧できるものに限る。
            status: ステータスで絞り込む（複数はいずれか）。
            priority: 優先度で絞り込む（複数はいずれか）。
            q: タイトルの部分一致（大文字小文字を区別しない。前後の空白は除く。最大 200 文字）。
            organization_id: 公開先に含まれる（有効な）組織で絞り込む。
            assignee_id: 担当者に含まれるユーザーで絞り込む。
            due_before: 期限がこの日以前（この日を含む）。期限なしは除く。
            due_after: 期限がこの日以降（この日を含む）。期限なしは除く。
            sort: 並び替え（``due_date`` / ``priority`` / ``created_at`` / ``updated_at``、先頭の ``-`` で降順。既定 ``-created_at``）。
                ``due_date`` の期限なしは昇順で末尾・降順で先頭。``priority`` は ``low < medium < high``。同じ値は ``id`` 順。
            limit: 件数（1〜200 に補正）。
            after: 起点（前のページの ``next_after``）。値の型は ``due_date`` が ``date | None``（ISO 8601 の文字列も可）、
                ``priority`` が値の文字列、``created_at`` / ``updated_at`` が ``datetime``（タイムゾーン付きの ISO 8601 の文字列も可）。
            include_total: 総件数を数えるか（表示範囲・絞り込みを適用し、カーソルには依存しない。SQL 1 本。AP-UX-02）。

        Returns:
            TodoListPage: ページ（担当者・公開先組織・件数・作成者と更新者の表示名は 1 回ずつのクエリでまとめて取得する）と総件数
            （``include_total`` でなければ ``None``）。

        Raises:
            TodoValidationError: 引数が不正。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        todo_scope = _parse_scope(scope)
        try:
            list_sort = ListSort.parse(sort, TODO_SORT_KEYS)
        except (ValueError, AttributeError):
            raise TodoValidationError("sort", "unsupported") from None
        filters = TodoListFilter(
            statuses=_normalize_filter_values("status", status, TodoStatus),
            priorities=_normalize_filter_values("priority", priority, TodoPriority),
            assignee_id=_optional_uuid("assignee_id", assignee_id),
            organization_id=_optional_uuid("organization_id", organization_id),
            due_before=_optional_date("due_before", due_before),
            due_after=_optional_date("due_after", due_after),
            title_query=_normalize_query(q),
        )
        if not isinstance(include_total, bool):
            raise TodoValidationError("include_total", "type")
        conditions = [visible_condition(actor), scope_condition(actor, todo_scope)]
        page = todo_repo.list_todos(
            self._session, actor.tenant_id, conditions=conditions, filters=filters, sort=list_sort, after=_normalize_todo_after(list_sort, after), limit=normalize_limit(limit)
        )
        decorations = self._decorations(actor, page.items)
        items = [TodoView(**decorations.view_fields(todo)) for todo in page.items]
        total = todo_repo.count_todos(self._session, actor.tenant_id, conditions=conditions, filters=filters) if include_total else None
        return TodoListPage(items=items, next_after=page.next_after, total=total)

    def summarize(self, *, today: dt.date | None = None, due_soon_days: int = DEFAULT_DUE_SOON_DAYS) -> TodoSummaryView:
        """ホームの要約（AP-UX-01。ToDoApp.md §10 #21）。閲覧できる ToDo だけを数え、論理削除済み・完了を除く（SQL 1 本）。

        - 担当: 自分が担当の ``open`` / ``in_progress`` の件数、期限切れ（``due_date < today``）、期限間近（``today <= due_date <= today + due_soon_days``）
        - 作成: 自分が作成した ``open`` / ``in_progress`` の件数、期限切れ

        Args:
            today: 今日（クライアントのローカル日付）。``None`` なら UTC の日付。
            due_soon_days: 期限間近の日数（1〜30）。

        Returns:
            TodoSummaryView: 要約。

        Raises:
            TodoValidationError: ``today`` が日付でない（``datetime`` を含む）・``today + due_soon_days`` が日付の上限を超える（``out_of_range``）、
                ``due_soon_days`` が範囲外（``out_of_range``）・整数でない。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        if today is None:
            today = utc_now().date()
        elif isinstance(today, dt.datetime) or not isinstance(today, dt.date):
            raise TodoValidationError("today", "type")
        if isinstance(due_soon_days, bool) or not isinstance(due_soon_days, int):
            raise TodoValidationError("due_soon_days", "type")
        if not DUE_SOON_DAYS_MIN <= due_soon_days <= DUE_SOON_DAYS_MAX:
            raise TodoValidationError("due_soon_days", "out_of_range")
        try:
            due_soon_until = today + dt.timedelta(days=due_soon_days)
        except OverflowError:
            raise TodoValidationError("today", "out_of_range") from None
        counts = todo_repo.summary_counts(
            self._session,
            actor.tenant_id,
            visible=visible_condition(actor),
            assigned=scope_condition(actor, TodoScope.ASSIGNED),
            created=scope_condition(actor, TodoScope.MINE),
            today=today,
            due_soon_until=due_soon_until,
        )
        return TodoSummaryView(
            today=today,
            due_soon_days=due_soon_days,
            due_soon_until=due_soon_until,
            assigned=TodoSummaryAssignedView(open=counts.assigned_open, in_progress=counts.assigned_in_progress, overdue=counts.assigned_overdue, due_soon=counts.assigned_due_soon),
            created=TodoSummaryCreatedView(open=counts.created_open, in_progress=counts.created_in_progress, overdue=counts.created_overdue),
        )

    def get_todo(self, todo_id: uuid.UUID) -> TodoDetailView:
        """ToDo の詳細（担当者・公開先組織・閲覧範囲・``version``・操作者の権限）。

        Raises:
            TodoNotFoundError: 存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        todo = require_visible_todo(self._session, actor, todo_id)
        return self._detail_view(actor, todo)

    def list_activities(self, todo_id: uuid.UUID, *, limit: int = 50, after: tuple[Any, uuid.UUID] | None = None) -> TodoActivityPage:
        """ToDo のアクティビティ（新しい順。AP-ACT-02: ToDo を閲覧できる人だけが参照できる）。

        ページ内の操作者と ``payload`` が参照するユーザー（担当者の追加・削除、作成時の担当者）の表示名を ``users`` に付ける
        （外れた担当者・無効化されたユーザーも解決できる。ユーザーの取得は 1 回のクエリ）。

        Args:
            todo_id: ToDo ID。
            limit: 件数（1〜200 に補正）。
            after: 起点（前のページの ``next_after``。``(created_at, id)``。日時はタイムゾーン付きの ISO 8601 の文字列も可）。

        Returns:
            TodoActivityPage: ページ（``Page[TodoActivityView]`` + ``users``）。

        Raises:
            TodoNotFoundError: 存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
            TodoValidationError: ``after`` が不正（``field="cursor"``）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        normalized_after = normalize_datetime_after(after)
        todo = require_visible_todo(self._session, actor, todo_id)
        page = activity_repo.list_activities(self._session, actor.tenant_id, todo.id, after=normalized_after, limit=normalize_limit(limit))
        rows = [(row, TodoActivityAction(row.action), dict(row.payload or {})) for row in page.items]
        referenced: set[uuid.UUID] = set()
        for row, action, payload in rows:
            referenced.add(row.actor_id)
            referenced.update(_activity_user_ids(action, payload))
        users: dict[uuid.UUID, UserNameView] = load_user_names(self._session, actor.tenant_id, referenced)
        items = [
            TodoActivityView(
                id=row.id,
                todo_id=row.todo_id,
                actor_id=row.actor_id,
                actor_display_name=users[row.actor_id].display_name if row.actor_id in users else None,
                action=action,
                payload=payload,
                created_at=row.created_at,
            )
            for row, action, payload in rows
        ]
        return TodoActivityPage(items=items, next_after=page.next_after, users=users)

    # ------------------------------------------------------------------ 変更
    def create_todo(
        self,
        *,
        title: str,
        description: str | None = None,
        due_date: dt.date | None = None,
        priority: TodoPriority | str = TodoPriority.MEDIUM,
        status: TodoStatus | str = TodoStatus.OPEN,
        visibility: TodoVisibility | str = TodoVisibility.PRIVATE,
        organization_ids: Sequence[uuid.UUID] = (),
        assignee_ids: Sequence[uuid.UUID] = (),
    ) -> TodoDetailView:
        """ToDo を作成してコミットする（AP-TODO-01..04、AP-VIS-01, 07、AP-ASN-01, 02）。作成者は操作者。

        Args:
            title: タイトル（前後の空白を除いて 1〜200 文字。制御文字は不可）。
            description: 説明（最大 10,000 文字。空文字は ``None``）。
            due_date: 期限（日付。``datetime`` は不可）。
            priority: 優先度（既定 ``medium``）。
            status: ステータス（既定 ``open``）。
            visibility: 閲覧範囲（既定 ``private``）。
            organization_ids: 公開先組織（``organization`` のときは有効な組織を 1 つ以上必須。それ以外では指定不可）。
            assignee_ids: 担当者（最大 20 人。テナント内の有効なユーザー）。

        Returns:
            TodoDetailView: 作成した ToDo。

        Raises:
            TodoValidationError: 入力が不正（``organization_ids`` / ``required`` 等）。
            InvalidTodoOrganizationsError: テナント内に存在しない・論理削除済みの組織。
            InvalidTodoAssigneesError: テナント内に存在しない（``not_found``）・無効化された（``inactive``）ユーザー。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        values: dict[str, Any] = {
            "title": _validate_title(title),
            "description": _validate_description(description),
            "due_date": _validate_due_date(due_date),
            "priority": _enum_value("priority", priority, TodoPriority),
            "status": _enum_value("status", status, TodoStatus),
            "visibility": _enum_value("visibility", visibility, TodoVisibility),
        }
        orgs = _validate_ids("organization_ids", organization_ids, TODO_ORGANIZATIONS_MAX)
        assignees = _validate_ids("assignee_ids", assignee_ids, TODO_ASSIGNEES_MAX)
        if values["visibility"] == TodoVisibility.ORGANIZATION.value:
            if not orgs:
                raise TodoValidationError("organization_ids", "required")
        elif orgs:
            raise TodoValidationError("organization_ids", "not_allowed")
        try:
            self._ensure_organizations_assignable(orgs)
            self._ensure_users_assignable(assignees, field="assignee_ids")
            todo = TTodo(tenant_id=actor.tenant_id, created_by=actor.user_id, updated_by=actor.user_id, **values)
            self._session.add(todo)
            self._session.flush()
            todo_repo.add_organizations(self._session, actor.tenant_id, todo.id, orgs)
            todo_repo.add_assignees(self._session, actor.tenant_id, todo.id, assignees, assigned_by=actor.user_id)
            snapshot = {**{key: to_json(value) for key, value in values.items()}, "organization_ids": to_json(orgs), "assignee_ids": to_json(assignees)}
            self._record_activity(actor, todo.id, TodoActivityAction.CREATED, {"values": snapshot})
            audit_snapshot = {key: value for key, value in snapshot.items() if key != "description"}
            self._record_audit(actor, ACTION_TODO_CREATE, todo.id, audit_snapshot)
            self._session.flush()
            view = self._detail_view(actor, todo)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("ToDo を作成しました: tenant_id=%s todo_id=%s", actor.tenant_id, view.id)
        return view

    def update_todo(
        self,
        todo_id: uuid.UUID,
        *,
        expected_version: int,
        title: Maybe[str] = UNSET,
        description: Maybe[str | None] = UNSET,
        due_date: Maybe[dt.date | None] = UNSET,
        priority: Maybe[TodoPriority | str] = UNSET,
        status: Maybe[TodoStatus | str] = UNSET,
        visibility: Maybe[TodoVisibility | str] = UNSET,
        organization_ids: Maybe[Sequence[uuid.UUID]] = UNSET,
    ) -> TodoDetailView:
        """ToDo を部分更新してコミットする（AP-TODO-05, 08、AP-ASN-03、AP-VIS-07, 08。PATCH。``UNSET`` の項目は変えない）。

        - ``description`` / ``due_date`` の ``None`` は値を消す。それ以外の項目の ``None`` は 422
        - 閲覧範囲を ``organization`` にする（または公開先を変える）ときは有効な組織が 1 つ以上必要。既に公開先にある
          論理削除済みの組織は指定に残してよい（新たには指定できない）。``organization`` 以外にすると公開先は空にする
        - 公開先の組織がすべて削除された ToDo（実質 ``private``）でも、閲覧範囲・公開先を変えない更新はそのまま通す

        Returns:
            TodoDetailView: 更新後の ToDo（値が変わらなければ現在の ToDo）。

        Raises:
            TodoValidationError: 入力が不正。
            TodoNotFoundError: 存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
            TodoVersionConflictError: バージョンが一致しない。
            TodoPermissionDeniedError: 変わる項目に対する権限が無い（``operation``: ``edit_fields`` / ``change_status`` / ``change_visibility``）。
            InvalidTodoOrganizationsError: テナント内に存在しない・論理削除済みの組織を新たに指定した。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        patch: dict[str, Any] = {}
        if title is not UNSET:
            patch["title"] = _validate_title(title)
        if description is not UNSET:
            patch["description"] = _validate_description(description)
        if due_date is not UNSET:
            patch["due_date"] = _validate_due_date(due_date)
        if priority is not UNSET:
            patch["priority"] = _enum_value("priority", priority, TodoPriority)
        new_status = UNSET if status is UNSET else _enum_value("status", status, TodoStatus)
        new_visibility = UNSET if visibility is UNSET else _enum_value("visibility", visibility, TodoVisibility)
        new_orgs = UNSET if organization_ids is UNSET else _validate_ids("organization_ids", organization_ids, TODO_ORGANIZATIONS_MAX)
        try:
            todo = self._lock_visible(actor, todo_id, expected_version)
            assignee_ids = todo_repo.list_assignee_ids(self._session, actor.tenant_id, todo.id)
            permissions = todo_permissions(actor, created_by=todo.created_by, assignee_ids=assignee_ids)

            field_changes = {name: change(getattr(todo, name), value) for name, value in patch.items() if getattr(todo, name) != value}
            status_change = change(todo.status, new_status) if new_status is not UNSET and new_status != todo.status else None
            links = todo_repo.list_organization_links(self._session, actor.tenant_id, todo.id)
            target_visibility = todo.visibility if new_visibility is UNSET else new_visibility
            if target_visibility == TodoVisibility.ORGANIZATION.value:
                desired_orgs = list(links) if new_orgs is UNSET else new_orgs
            else:
                desired_orgs = []
            desired_org_set = set(desired_orgs)
            added_orgs = [org_id for org_id in desired_orgs if org_id not in links]
            removed_orgs = [org_id for org_id in links if org_id not in desired_org_set]
            visibility_change = change(todo.visibility, target_visibility) if target_visibility != todo.visibility else None

            required: list[TodoOperation] = []
            if field_changes:
                required.append(TodoOperation.EDIT_FIELDS)
            if status_change:
                required.append(TodoOperation.CHANGE_STATUS)
            if visibility_change or added_orgs or removed_orgs:
                required.append(TodoOperation.CHANGE_VISIBILITY)
            for operation in required:
                if not permissions.allows(operation):
                    raise TodoPermissionDeniedError(todo.id, operation.value)

            if target_visibility != TodoVisibility.ORGANIZATION.value and new_orgs is not UNSET and new_orgs:
                raise TodoValidationError("organization_ids", "not_allowed")
            if target_visibility == TodoVisibility.ORGANIZATION.value and (visibility_change or added_orgs or removed_orgs):
                self._ensure_organizations_assignable(added_orgs)
                if not any(links.get(org_id, True) for org_id in desired_orgs):
                    raise TodoValidationError("organization_ids", "required")

            if not required:
                view = self._detail_view(actor, todo)
                self._session.rollback()
                return view

            before_version = todo.version
            for name, value in patch.items():
                if name in field_changes:
                    setattr(todo, name, value)
            if status_change:
                todo.status = new_status
            if visibility_change:
                todo.visibility = target_visibility
            todo_repo.remove_organizations(self._session, actor.tenant_id, todo.id, removed_orgs)
            todo_repo.add_organizations(self._session, actor.tenant_id, todo.id, added_orgs)
            todo.version = before_version + 1
            todo.updated_by = actor.user_id
            version = change(before_version, todo.version)

            if field_changes:
                self._record_activity(actor, todo.id, TodoActivityAction.UPDATED, {"changes": to_json(field_changes)})
            if status_change:
                self._record_activity(actor, todo.id, TodoActivityAction.STATUS_CHANGED, {"changes": {"status": status_change}})
            visibility_payload: dict[str, Any] = {}
            if visibility_change:
                visibility_payload["changes"] = {"visibility": visibility_change}
            if added_orgs or removed_orgs:
                visibility_payload["organization_ids"] = {"added": to_json(added_orgs), "removed": to_json(removed_orgs)}
            if visibility_payload:
                self._record_activity(actor, todo.id, TodoActivityAction.VISIBILITY_CHANGED, visibility_payload)

            audit_changes = {name: ({"changed": True} if name == "description" else to_json(value)) for name, value in field_changes.items()}
            if status_change:
                audit_changes["status"] = status_change
            if audit_changes:
                self._record_audit(actor, ACTION_TODO_UPDATE, todo.id, {"changes": audit_changes, "version": version})
            if visibility_payload:
                self._record_audit(actor, ACTION_TODO_CHANGE_VISIBILITY, todo.id, {**visibility_payload, "version": version})

            self._session.flush()
            view = self._detail_view(actor, todo)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("ToDo を更新しました: tenant_id=%s todo_id=%s operations=%s", actor.tenant_id, view.id, ",".join(op.value for op in required))
        return view

    def delete_todo(self, todo_id: uuid.UUID, *, expected_version: int) -> None:
        """ToDo を論理削除してコミットする（AP-TODO-05。以降は誰も参照できない）。担当者・公開先・アクティビティの行は残す。

        Raises:
            TodoNotFoundError: 存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
            TodoVersionConflictError: バージョンが一致しない。
            TodoPermissionDeniedError: 削除の権限が無い（``operation="delete"``）。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        try:
            todo = self._lock_visible(actor, todo_id, expected_version)
            assignee_ids = todo_repo.list_assignee_ids(self._session, actor.tenant_id, todo.id)
            if not todo_permissions(actor, created_by=todo.created_by, assignee_ids=assignee_ids).can_delete:
                raise TodoPermissionDeniedError(todo.id, TodoOperation.DELETE.value)
            before_version = todo.version
            todo.deleted_at = utc_now()
            todo.version = before_version + 1
            todo.updated_by = actor.user_id
            self._record_activity(actor, todo.id, TodoActivityAction.DELETED, {"title": todo.title})
            self._record_audit(actor, ACTION_TODO_DELETE, todo.id, {"title": todo.title, "version": change(before_version, todo.version)})
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("ToDo を削除しました（論理削除）: tenant_id=%s todo_id=%s", actor.tenant_id, todo_id)

    def set_assignees(self, todo_id: uuid.UUID, *, expected_version: int, user_ids: Sequence[uuid.UUID]) -> TodoDetailView:
        """担当者を ``user_ids`` に置き換えてコミットする（AP-ASN-01..05。全置換）。

        残る担当者の行は維持する（``assigned_at`` / ``assigned_by`` を保つ）。無効化されたユーザーは、既に担当者なら
        残せる・外せるが、新たには割り当てられない。変更が無ければ何もしない（``version`` も変えない）。

        Args:
            todo_id: ToDo ID。
            expected_version: ``If-Match`` のバージョン。
            user_ids: 担当者にするユーザー ID（重複は除く。最大 20 人）。

        Returns:
            TodoDetailView: 更新後の ToDo（操作者が自分を外して閲覧できなくなった場合も、この応答は返す）。

        Raises:
            TodoValidationError: 件数が上限を超える、ID の形式が不正（``field="user_ids"``）。
            TodoNotFoundError: 存在しない（他テナント・論理削除済み・閲覧範囲外を含む）。
            TodoVersionConflictError: バージョンが一致しない。
            TodoPermissionDeniedError: 担当者の変更の権限が無い（``operation="change_assignees"``）。
            InvalidTodoAssigneesError: テナント内に存在しない（``not_found``）・無効化された（``inactive``）ユーザーを新たに指定した。
        """
        actor = actor_of(self._actor_user_id, self._actor_roles)
        desired = _validate_ids("user_ids", user_ids, TODO_ASSIGNEES_MAX)
        try:
            todo = self._lock_visible(actor, todo_id, expected_version)
            current = todo_repo.list_assignee_ids(self._session, actor.tenant_id, todo.id)
            if not todo_permissions(actor, created_by=todo.created_by, assignee_ids=current).can_change_assignees:
                raise TodoPermissionDeniedError(todo.id, TodoOperation.CHANGE_ASSIGNEES.value)
            current_set, desired_set = set(current), set(desired)
            added = [user_id for user_id in desired if user_id not in current_set]
            removed = [user_id for user_id in current if user_id not in desired_set]
            if not added and not removed:
                view = self._detail_view(actor, todo)
                self._session.rollback()
                return view
            self._ensure_users_assignable(added, field="user_ids")
            todo_repo.remove_assignees(self._session, actor.tenant_id, todo.id, removed)
            todo_repo.add_assignees(self._session, actor.tenant_id, todo.id, added, assigned_by=actor.user_id)
            before_version = todo.version
            todo.version = before_version + 1
            todo.updated_by = actor.user_id
            payload = {"added": to_json(added), "removed": to_json(removed)}
            self._record_activity(actor, todo.id, TodoActivityAction.ASSIGNEES_CHANGED, payload)
            self._record_audit(actor, ACTION_TODO_SET_ASSIGNEES, todo.id, {**payload, "version": change(before_version, todo.version)})
            self._session.flush()
            view = self._detail_view(actor, todo)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("ToDo の担当者を置き換えました: tenant_id=%s todo_id=%s added=%d removed=%d", actor.tenant_id, view.id, len(added), len(removed))
        return view

    # ------------------------------------------------------------------ 補助
    def _lock_visible(self, actor: TodoActor, todo_id: uuid.UUID, expected_version: int) -> TTodo:
        """閲覧できる ToDo を行ロックして取得し、バージョンを確認する。"""
        todo = require_visible_todo(self._session, actor, todo_id, for_update=True)
        if todo.version != expected_version:
            raise TodoVersionConflictError(todo.id, expected_version, todo.version)
        return todo

    def _decorations(self, actor: TodoActor, todos: Sequence[TTodo]) -> "_ViewDecorations":
        """ビューに付ける担当者・公開先組織・件数・作成者と更新者の表示名を、ToDo の ID でまとめて取得する（4 クエリ。N+1 にしない）。"""
        todo_ids = [todo.id for todo in todos]
        user_ids = {todo.created_by for todo in todos} | {todo.updated_by for todo in todos}
        return _ViewDecorations(
            assignees=todo_repo.load_assignees(self._session, actor.tenant_id, todo_ids),
            organizations=todo_repo.load_active_organizations(self._session, actor.tenant_id, todo_ids),
            counters=todo_repo.load_todo_counters(self._session, actor.tenant_id, todo_ids),
            users=load_user_names(self._session, actor.tenant_id, user_ids),
        )

    def _detail_view(self, actor: TodoActor, todo: TTodo) -> TodoDetailView:
        """詳細のビューを作る（担当者・公開先組織・件数・ユーザー名を読み込む）。"""
        decorations = self._decorations(actor, [todo])
        permissions = todo_permissions(actor, created_by=todo.created_by, assignee_ids={row.user_id for row in decorations.assignees.get(todo.id, [])})
        return TodoDetailView(**decorations.view_fields(todo), description=todo.description, permissions=permissions)

    def _ensure_organizations_assignable(self, organization_ids: Collection[uuid.UUID]) -> None:
        """公開先に新たに指定する組織が、テナント内に存在し論理削除されていないことを確認する。"""
        if not organization_ids:
            return
        found = todo_repo.find_active_organization_ids(self._session, organization_ids)
        unknown = [org_id for org_id in organization_ids if org_id not in found]
        if unknown:
            raise InvalidTodoOrganizationsError(unknown)

    def _ensure_users_assignable(self, user_ids: Collection[uuid.UUID], *, field: str) -> None:
        """新たに割り当てるユーザーが、テナント内に存在し有効であることを確認する（AP-ASN-02）。"""
        if not user_ids:
            return
        states = todo_repo.find_user_states(self._session, user_ids)
        unknown = [user_id for user_id in user_ids if user_id not in states]
        if unknown:
            raise InvalidTodoAssigneesError(unknown, "not_found", field=field)
        inactive = [user_id for user_id in user_ids if not states[user_id]]
        if inactive:
            raise InvalidTodoAssigneesError(inactive, "inactive", field=field)

    def _record_activity(self, actor: TodoActor, todo_id: uuid.UUID, action: TodoActivityAction, payload: dict[str, Any]) -> None:
        """アクティビティを追記する（同じトランザクション。AP-ACT-03）。"""
        record_activity(self._session, actor, todo_id, action, payload)

    def _record_audit(self, actor: TodoActor, action: str, todo_id: uuid.UUID, payload: dict[str, Any]) -> None:
        """AP 監査ログを追記する（同じトランザクション。AP-ACT-04）。"""
        record_audit(self._session, require_tenant_context(), actor_id=actor.user_id, action=action, target_type=AUDIT_TARGET_TYPE, target_id=todo_id, payload=payload)


# --------------------------------------------------------------------------- ビューの組み立て


@dataclass(frozen=True, slots=True, kw_only=True)
class _ViewDecorations:
    """ビューに付ける値（ToDo の ID でまとめて取得したもの）。"""

    assignees: dict[uuid.UUID, list[AssigneeRow]]
    organizations: dict[uuid.UUID, list[OrganizationRow]]
    counters: dict[uuid.UUID, TodoCounters]
    users: dict[uuid.UUID, UserNameView]

    def view_fields(self, todo: TTodo) -> dict[str, Any]:
        """:class:`TodoView` の項目（説明を除く）。"""
        counters = self.counters.get(todo.id) or TodoCounters()
        return {
            **_view_fields(todo, self.assignees.get(todo.id, []), self.organizations.get(todo.id, [])),
            "creator": user_name_or_unknown(self.users, todo.created_by),
            "updater": user_name_or_unknown(self.users, todo.updated_by),
            "checklist": TodoChecklistProgressView(done_count=counters.done_count, total_count=counters.total_count),
            "comment_count": counters.comment_count,
        }


def _view_fields(todo: TTodo, assignees: Sequence[AssigneeRow], organizations: Sequence[OrganizationRow]) -> dict[str, Any]:
    """:class:`TodoView` の ToDo 本体・担当者・公開先組織の項目（説明・件数・ユーザー名を除く）。"""
    return {
        "id": todo.id,
        "title": todo.title,
        "status": TodoStatus(todo.status),
        "priority": TodoPriority(todo.priority),
        "due_date": todo.due_date,
        "visibility": TodoVisibility(todo.visibility),
        "effective_visibility": effective_visibility(todo.visibility, len(organizations)),
        "organizations": tuple(TodoOrganizationView(id=row.organization_id, name=row.name) for row in organizations),
        "assignees": tuple(
            TodoAssigneeView(user_id=row.user_id, display_name=row.display_name, is_active=row.is_active, assigned_at=row.assigned_at, assigned_by=row.assigned_by) for row in assignees
        ),
        "created_by": todo.created_by,
        "updated_by": todo.updated_by,
        "version": todo.version,
        "created_at": todo.created_at,
        "updated_at": todo.updated_at,
    }


def _activity_user_ids(action: TodoActivityAction, payload: dict[str, Any]) -> set[uuid.UUID]:
    """アクティビティの ``payload`` が参照するユーザー ID を取り出す（形は :class:`TodoActivityView` の docstring）。

    ``created`` の ``values.assignee_ids``、``assignees_changed`` の ``added`` / ``removed``。UUID として読めない値は無視する
    （``payload`` は記録時の JSON のため、壊れていても一覧の取得は止めない）。
    """
    if action == TodoActivityAction.CREATED:
        values = payload.get("values")
        candidates = values.get("assignee_ids") if isinstance(values, dict) else None
        raw = list(candidates) if isinstance(candidates, list) else []
    elif action == TodoActivityAction.ASSIGNEES_CHANGED:
        raw = [value for key in ("added", "removed") if isinstance(payload.get(key), list) for value in payload[key]]
    else:
        return set()
    result: set[uuid.UUID] = set()
    for value in raw:
        try:
            result.add(uuid.UUID(str(value)))
        except ValueError:
            continue
    return result


# --------------------------------------------------------------------------- 入力検証


def _validate_title(title: Any) -> str:
    """タイトル（前後の空白を除いて 1〜200 文字。制御文字は不可。AP-TODO-04）。"""
    if not isinstance(title, str) or not title.strip():
        raise TodoValidationError("title", "required")
    value = title.strip()
    if len(value) > TODO_TITLE_MAX_LENGTH:
        raise TodoValidationError("title", "too_long")
    if has_control_chars(value, allow_whitespace=False):
        raise TodoValidationError("title", "format")
    return value


def _validate_description(description: Any) -> str | None:
    """説明（任意。最大 10,000 文字。空文字は ``None``。NUL 等の制御文字は不可。AP-TODO-04）。"""
    if description is None:
        return None
    if not isinstance(description, str):
        raise TodoValidationError("description", "type")
    if description == "":
        return None
    if len(description) > TODO_DESCRIPTION_MAX_LENGTH:
        raise TodoValidationError("description", "too_long")
    if has_control_chars(description, allow_whitespace=True):
        raise TodoValidationError("description", "format")
    return description


def _validate_due_date(due_date: Any) -> dt.date | None:
    """期限（日付。時刻を持たない。AP-TODO-04）。"""
    if due_date is None:
        return None
    if isinstance(due_date, dt.datetime) or not isinstance(due_date, dt.date):
        raise TodoValidationError("due_date", "type")
    return due_date


def _optional_date(field: str, value: Any) -> dt.date | None:
    """絞り込みの日付。"""
    if value is None:
        return None
    if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
        raise TodoValidationError(field, "type")
    return value


def _optional_uuid(field: str, value: Any) -> uuid.UUID | None:
    """絞り込みの ID。"""
    if value is None:
        return None
    if not isinstance(value, uuid.UUID):
        raise TodoValidationError(field, "format")
    return value


def _enum_value(field: str, value: Any, enum_type: type[enum.StrEnum]) -> str:
    """列挙値を検証して値の文字列を返す（``None`` は ``required``）。"""
    if value is None:
        raise TodoValidationError(field, "required")
    try:
        return enum_type(value).value
    except ValueError:
        raise TodoValidationError(field, "unsupported") from None


def _validate_ids(field: str, ids: Any, max_count: int) -> list[uuid.UUID]:
    """ID の列を検証し、重複を除いて返す（指定順）。"""
    if ids is None or isinstance(ids, str | bytes) or not isinstance(ids, Sequence | set | frozenset):
        raise TodoValidationError(field, "type")
    if not all(isinstance(item, uuid.UUID) for item in ids):
        raise TodoValidationError(field, "format")
    unique = list(dict.fromkeys(ids))
    if len(unique) > max_count:
        raise TodoValidationError(field, "too_many")
    return unique


def _parse_scope(scope: Any) -> TodoScope:
    """表示範囲。"""
    try:
        return TodoScope(scope)
    except ValueError:
        raise TodoValidationError("scope", "unsupported") from None


def _normalize_filter_values(field: str, values: Any, enum_type: type[enum.StrEnum]) -> tuple[str, ...] | None:
    """絞り込みの列挙値（1 つまたは複数）。空なら絞り込まない。"""
    if values is None:
        return None
    items = [values] if isinstance(values, str) else values
    if not isinstance(items, Iterable):
        raise TodoValidationError(field, "type")
    result: list[str] = []
    for item in items:
        try:
            result.append(enum_type(item).value)
        except ValueError:
            raise TodoValidationError(field, "unsupported") from None
    return tuple(dict.fromkeys(result)) or None


def _normalize_query(q: Any) -> str | None:
    """タイトルの検索語（前後の空白を除く。空なら絞り込まない）。"""
    if q is None:
        return None
    if not isinstance(q, str):
        raise TodoValidationError("q", "type")
    value = q.strip()
    if not value:
        return None
    if len(value) > TODO_TITLE_MAX_LENGTH:
        raise TodoValidationError("q", "too_long")
    if has_control_chars(value, allow_whitespace=False):
        raise TodoValidationError("q", "format")
    return value


def _normalize_todo_after(sort: ListSort, after: Any) -> tuple[Any, uuid.UUID] | None:
    """一覧の起点を並び替えキーに合う型にする。"""
    if after is None:
        return None
    value, last_id = split_after(after)
    match sort.key:
        case "due_date":
            if value is None:
                return None, last_id
            if isinstance(value, str):
                try:
                    return dt.date.fromisoformat(value), last_id
                except ValueError:
                    raise TodoValidationError("cursor", "format") from None
            if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
                raise TodoValidationError("cursor", "format")
            return value, last_id
        case "priority":
            if not isinstance(value, str) or value not in PRIORITY_RANK:
                raise TodoValidationError("cursor", "format")
            return str(value), last_id
        case _:
            return parse_aware_datetime(value), last_id
