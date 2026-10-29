#!/usr/bin/env python
# coding:utf-8
"""ToDo のサービスが返すビュー（セッションから切り離した値。API のレスポンスに使う）。

:mod:`main_app.services.todo_service` から再エクスポートしている。
"""
import datetime as dt
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from main_app.models import TodoActivityAction, TodoPriority, TodoStatus, TodoVisibility
from main_app.repositories.keyset import Page
from main_app.services.common import UserNameView
from main_app.services.todo_policy import TodoPermissions


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoAssigneeView:
    """担当者。

    Attributes:
        user_id: ユーザー ID。
        display_name: 表示名。
        is_active: 有効か（無効化されても割り当ては残る。画面では「無効」と表示する。AP-ASN-04）。
        assigned_at: 割り当て日時。
        assigned_by: 割り当てたユーザー ID。
    """

    user_id: uuid.UUID
    display_name: str
    is_active: bool
    assigned_at: dt.datetime
    assigned_by: uuid.UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoOrganizationView:
    """公開先組織（有効なもののみ。論理削除された組織は含めない。AP-VIS-08）。

    Attributes:
        id: 組織 ID。
        name: 組織名。
    """

    id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoView:
    """一覧の要素（説明 ``description`` は含めない。詳細は :class:`TodoDetailView`）。

    Attributes:
        id: ToDo ID。
        title: タイトル。
        status: ステータス。
        priority: 優先度。
        due_date: 期限（日付）。
        visibility: 設定された閲覧範囲。
        effective_visibility: 実際の閲覧範囲。``visibility`` が ``organization`` で有効な公開先組織が無ければ ``private``
            （AP-VIS-08。編集画面で組織の再指定を促す目印）。
        organizations: 有効な公開先組織（組織名順）。
        assignees: 担当者（割り当て日時順。無効化されたユーザーを含む）。
        created_by: 作成者のユーザー ID。
        updated_by: 最終更新者のユーザー ID。
        version: 楽観ロックのバージョン（``ETag``。一覧からも更新できるよう含める。03 §5.2）。
        created_at: 作成日時。
        updated_at: 更新日時。
    """

    id: uuid.UUID
    title: str
    status: TodoStatus
    priority: TodoPriority
    due_date: dt.date | None
    visibility: TodoVisibility
    effective_visibility: TodoVisibility
    organizations: tuple[TodoOrganizationView, ...]
    assignees: tuple[TodoAssigneeView, ...]
    created_by: uuid.UUID
    updated_by: uuid.UUID
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoDetailView(TodoView):
    """詳細（一覧の項目 + 説明 + 操作者の権限）。

    Attributes:
        description: 説明。
        permissions: 操作者が行える操作（画面のボタンの出し分け用。判定はサービスが更新時にも行う）。
    """

    description: str | None
    permissions: TodoPermissions


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoActivityView:
    """アクティビティ（AP-ACT-02）。

    ``payload`` の形（値は JSON に変換済み。日付は ISO 8601 の文字列、ID は文字列）:

    | ``action`` | ``payload`` |
    | --- | --- |
    | ``created`` | ``{"values": {title, description, status, priority, due_date, visibility, organization_ids, assignee_ids}}`` |
    | ``updated`` | ``{"changes": {<title / description / due_date / priority>: {"before", "after"}}}`` |
    | ``status_changed`` | ``{"changes": {"status": {"before", "after"}}}`` |
    | ``visibility_changed`` | ``{"changes": {"visibility": {"before", "after"}}, "organization_ids": {"added": [...], "removed": [...]}}``（変わった方だけ） |
    | ``assignees_changed`` | ``{"added": [...], "removed": [...]}`` |
    | ``deleted`` | ``{"title": ...}`` |

    Attributes:
        id: アクティビティ ID。
        todo_id: ToDo ID。
        actor_id: 操作者のユーザー ID。
        actor_display_name: 操作者の表示名。
        action: 種別。
        payload: 変更前後の差分。
        created_at: 記録日時（同じ操作で記録した行は同じ値）。
    """

    id: uuid.UUID
    todo_id: uuid.UUID
    actor_id: uuid.UUID
    actor_display_name: str | None
    action: TodoActivityAction
    payload: dict[str, Any]
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class TodoActivityPage(Page[TodoActivityView]):
    """アクティビティの 1 ページと、参照されるユーザーの表示名（:meth:`main_app.services.todo_service.TodoService.list_activities`）。

    :class:`~main_app.repositories.keyset.Page` の ``items`` / ``next_after`` に ``users`` を加えたもの（``Page`` として扱える）。

    Attributes:
        users: ユーザー ID → 表示名・有効か。ページ内の操作者（``actor_id``）と ``payload`` が参照するユーザー
            （``created`` の ``values.assignee_ids``、``assignees_changed`` の ``added`` / ``removed``）。
            無効化されたユーザー・担当者から外れたユーザーも含む。テナント内に存在しない ID（他テナントの ID を含む）は含めない
            （画面では「不明なユーザー」等と表示する）。
    """

    users: Mapping[uuid.UUID, UserNameView] = field(default_factory=dict)
