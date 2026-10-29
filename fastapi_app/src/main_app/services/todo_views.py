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
from main_app.services.todo_policy import TodoChecklistPermissions, TodoCommentPermissions, TodoPermissions


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
class TodoChecklistProgressView:
    """チェックリストの進捗（AP-CHK-06。項目が無ければ 0 / 0）。

    Attributes:
        done_count: 完了した項目の数。
        total_count: 項目の数。
    """

    done_count: int
    total_count: int


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
        creator: 作成者の表示名・有効か（AP-UX-03, 09）。
        updater: 最終更新者の表示名・有効か。
        checklist: チェックリストの進捗（AP-CHK-06）。
        comment_count: コメント数（論理削除済みを除く）。
        version: 楽観ロックのバージョン（``ETag``。一覧からも更新できるよう含める。03 §5.2）。コメント・チェックリストの変更では変わらない（§10 #16）。
        created_at: 作成日時。
        updated_at: 更新日時（ToDo 本体の更新日時。コメント・チェックリストの変更では変わらない）。

    ``creator`` / ``updater`` / ``checklist`` / ``comment_count`` は、一覧の 1 ページの ToDo の ID でまとめて取得する（N+1 にしない）。
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
    creator: UserNameView
    updater: UserNameView
    checklist: TodoChecklistProgressView
    comment_count: int
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime


@dataclass(frozen=True, slots=True)
class TodoListPage(Page[TodoView]):
    """ToDo の一覧の 1 ページと総件数（:meth:`main_app.services.todo_service.TodoService.list_todos`）。

    Attributes:
        total: 総件数（``include_total=True`` のときだけ数える。表示範囲・絞り込みを適用し、カーソルには依存しない。それ以外は ``None``）。
    """

    total: int | None = None


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
    | ``checklist_changed`` | ``{"op", "item_id", "title"}``。``op`` は ``added`` / ``renamed`` / ``removed`` / ``checked`` / ``unchecked``。``renamed`` は ``before`` / ``after`` に名前。並べ替えは記録しない |

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


# --------------------------------------------------------------------------- コメント（AP-CMT）


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoCommentView:
    """コメント（:class:`main_app.services.todo_comment_service.TodoCommentService`）。

    Attributes:
        id: コメント ID。
        todo_id: ToDo ID。
        author: 投稿者（無効化されたユーザーも残る。AP-CMT-07）。
        body: 本文（プレーンテキスト）。
        version: コメントの版（``ETag`` / ``If-Match``。ToDo 本体の版とは別）。
        created_at: 投稿日時。
        updated_at: 更新日時。
        edited_at: 本文を編集した日時（``None`` = 編集されていない。「編集済み」の表示用。AP-CMT-03）。
        permissions: 操作者がこのコメントに対して行える操作。
    """

    id: uuid.UUID
    todo_id: uuid.UUID
    author: UserNameView
    body: str
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    edited_at: dt.datetime | None
    permissions: TodoCommentPermissions


# --------------------------------------------------------------------------- チェックリスト（AP-CHK）


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoChecklistItemView:
    """チェックリスト項目。

    Attributes:
        id: 項目 ID。
        title: 項目名。
        position: 並び（0 からの連番）。
        is_done: 完了しているか。
        done_at: 完了した日時（未完了は ``None``）。
        done_by: 完了した人（未完了は ``None``。AP-CHK-04）。
        version: 項目の版（名前変更・完了の切り替え・削除の ``If-Match``）。
        created_at: 作成日時。
        updated_at: 更新日時。
    """

    id: uuid.UUID
    title: str
    position: int
    is_done: bool
    done_at: dt.datetime | None
    done_by: UserNameView | None
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoChecklistView:
    """チェックリスト全体（:class:`main_app.services.todo_checklist_service.TodoChecklistService` のすべてのメソッドの戻り値）。

    Attributes:
        todo_id: ToDo ID。
        version: チェックリスト全体の版（``t_todo.checklist_version``。項目の追加・削除・並べ替えで上がる。並べ替えの ``If-Match``。§10 #17）。
        items: 項目（``position`` の順）。
        done_count: 完了した項目の数。
        total_count: 項目の数。
        permissions: 操作者の権限（``can_edit`` = 追加・名前変更・削除・並べ替え、``can_check`` = 完了の切り替え）。
    """

    todo_id: uuid.UUID
    version: int
    items: tuple[TodoChecklistItemView, ...]
    done_count: int
    total_count: int
    permissions: TodoChecklistPermissions


# --------------------------------------------------------------------------- ホームの要約（AP-UX-01）


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoSummaryAssignedView:
    """自分が担当の ToDo の件数（完了を除く。閲覧できるものだけ）。

    Attributes:
        open: ステータスが ``open``。
        in_progress: ステータスが ``in_progress``。
        overdue: 期限切れ（``due_date < today``）。
        due_soon: 期限間近（``today <= due_date <= due_soon_until``）。
    """

    open: int
    in_progress: int
    overdue: int
    due_soon: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoSummaryCreatedView:
    """自分が作成した ToDo の件数（完了を除く）。

    Attributes:
        open: ステータスが ``open``。
        in_progress: ステータスが ``in_progress``。
        overdue: 期限切れ（``due_date < today``）。
    """

    open: int
    in_progress: int
    overdue: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoSummaryView:
    """ホームの要約（:meth:`main_app.services.todo_service.TodoService.summarize`。ToDoApp.md §10 #21）。

    Attributes:
        today: 判定に使った今日（クライアントのローカル日付。省略時は UTC の日付）。
        due_soon_days: 期限間近の日数（1〜30）。
        due_soon_until: 期限間近の終端（``today + due_soon_days``。この日を含む）。
        assigned: 自分が担当の ToDo の件数。
        created: 自分が作成した ToDo の件数。
    """

    today: dt.date
    due_soon_days: int
    due_soon_until: dt.date
    assigned: TodoSummaryAssignedView
    created: TodoSummaryCreatedView
