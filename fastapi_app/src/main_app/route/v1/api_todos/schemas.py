#!/usr/bin/env python
# coding:utf-8
"""ToDo API(``/api/v1/todos``)のリクエスト・レスポンスのスキーマ。

DB のテーブルモデル(``TTodo`` 等)はそのまま返さず、サービスのビュー(``todo_views.py``)に対応する公開用の項目だけを定義する。
日時は UTC(``Z``)の ISO 8601、期限(``due_date``)は時刻を持たない ``YYYY-MM-DD``(03 §4)。
一覧の要素(``TodoRead``)は説明を含めず、詳細(``TodoDetail``)でだけ説明と操作者の権限を返す(ToDoApp.md §10 #13)。
"""
import datetime as dt
import uuid
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from main_app.models import TodoActivityAction, TodoPriority, TodoStatus, TodoVisibility
from main_app.models.todo import TODO_ASSIGNEES_MAX, TODO_DESCRIPTION_MAX_LENGTH, TODO_TITLE_MAX_LENGTH
from main_app.services.todo_service import TODO_ORGANIZATIONS_MAX
from modules.api_common.datetime_types import UtcDatetime
from modules.api_common.pagination import CursorPage


class TodoOrganizationRead(BaseModel):
    """公開先の組織(有効なもののみ)。"""

    id: uuid.UUID = Field(description="組織 ID(UUIDv7)")
    name: str = Field(description="組織名")


class TodoAssigneeRead(BaseModel):
    """担当者。"""

    user_id: uuid.UUID = Field(description="ユーザー ID(`GET /api/v1/users` の `id` と同じ値)")
    display_name: str = Field(description="表示名")
    is_active: bool = Field(description="有効か。無効化されたユーザーも割り当ては残る(画面では「無効」と表示する)")
    assigned_at: UtcDatetime = Field(description="割り当て日時(UTC)")
    assigned_by: uuid.UUID = Field(description="割り当てたユーザーの ID")


class TodoPermissionsRead(BaseModel):
    """操作者がその ToDo に対して行える操作(画面のボタンの出し分け用。判定はサーバーが更新時にも行う)。"""

    can_edit_fields: bool = Field(description="項目(タイトル・説明・期限・優先度)を変更できるか")
    can_change_status: bool = Field(description="ステータスを変更できるか")
    can_change_visibility: bool = Field(description="閲覧範囲・公開先組織を変更できるか")
    can_change_assignees: bool = Field(description="担当者を変更できるか")
    can_delete: bool = Field(description="削除できるか")
    can_comment: bool = Field(description="コメントを参照・投稿できるか(閲覧できる ToDo なら常に `true`)")
    can_edit_checklist: bool = Field(description="チェックリスト項目の追加・名前変更・削除・並べ替えができるか(作成者・`tenant_admin`)")
    can_check_checklist: bool = Field(description="チェックリスト項目の完了・未完了を切り替えられるか(作成者・担当者・`tenant_admin`)")


class UserNameRead(BaseModel):
    """ToDo・コメント・チェックリストが参照するユーザーの表示用の情報(無効化されたユーザーも含む)。"""

    id: uuid.UUID = Field(description="ユーザー ID(`GET /api/v1/users` の `id` と同じ値)")
    display_name: str = Field(description="表示名")
    is_active: bool = Field(description="有効か。無効化されたユーザーも残る(画面では「無効」と表示する)")


class TodoChecklistSummary(BaseModel):
    """チェックリストの進捗(項目が無ければ 0 / 0)。"""

    done_count: int = Field(description="完了した項目の数")
    total_count: int = Field(description="項目の数")


class TodoRead(BaseModel):
    """ToDo(一覧の要素。説明は含まない)。`ETag` ヘッダーと `version` は同じ値。"""

    id: uuid.UUID = Field(description="ToDo ID(UUIDv7)")
    title: str = Field(description="タイトル(1〜200 文字)")
    status: TodoStatus = Field(description="ステータス")
    priority: TodoPriority = Field(description="優先度")
    due_date: dt.date | None = Field(description="期限(日付。`YYYY-MM-DD`)。期限なしは `null`")
    visibility: TodoVisibility = Field(description="設定された閲覧範囲")
    effective_visibility: TodoVisibility = Field(
        description="実際の閲覧範囲。`visibility` が `organization` で有効な公開先組織が無い(すべて削除された)場合は `private`。この値が `private` で `visibility` と異なるときは、編集画面で組織の再指定を促す"
    )
    organizations: list[TodoOrganizationRead] = Field(description="有効な公開先組織(組織名順)。削除された組織は含まない")
    assignees: list[TodoAssigneeRead] = Field(description="担当者(割り当て日時順。無効化されたユーザーを含む)")
    created_by: uuid.UUID = Field(description="作成者のユーザー ID")
    updated_by: uuid.UUID = Field(description="最終更新者のユーザー ID")
    creator: UserNameRead = Field(description="作成者(表示名と有効か)")
    updater: UserNameRead = Field(description="最終更新者(表示名と有効か)")
    checklist: TodoChecklistSummary = Field(description="チェックリストの進捗")
    comment_count: int = Field(description="コメント数(削除済みを除く)")
    version: int = Field(description="楽観ロック用のバージョン。更新系の `If-Match` に `\"<version>\"` で指定する。コメント・チェックリストの変更では変わらない")
    created_at: UtcDatetime = Field(description="作成日時(UTC)")
    updated_at: UtcDatetime = Field(description="ToDo 本体の更新日時(UTC)。コメント・チェックリストの変更では変わらない")


class TodoDetail(TodoRead):
    """ToDo の詳細。説明と、操作者の権限を含む。"""

    description: str | None = Field(description="説明(最大 10,000 文字)。無ければ `null`")
    permissions: TodoPermissionsRead = Field(description="操作者がこの ToDo に対して行える操作")


class TodoPage(CursorPage[TodoRead]):
    """ToDo 一覧(カーソル方式。説明は含まない)。"""


class TodoSummaryAssignedRead(BaseModel):
    """自分が担当の ToDo の件数(完了を除く。閲覧できるものだけ)。"""

    open: int = Field(description="ステータスが `open`")
    in_progress: int = Field(description="ステータスが `in_progress`")
    overdue: int = Field(description="期限切れ(`due_date < today`)")
    due_soon: int = Field(description="期限間近(`today <= due_date <= due_soon_until`)")


class TodoSummaryCreatedRead(BaseModel):
    """自分が作成した ToDo の件数(完了を除く)。"""

    open: int = Field(description="ステータスが `open`")
    in_progress: int = Field(description="ステータスが `in_progress`")
    overdue: int = Field(description="期限切れ(`due_date < today`)")


class TodoSummaryRead(BaseModel):
    """ホームの要約(件数)。完了(`done`)と削除済みは数えない。"""

    today: dt.date = Field(description="判定に使った今日(`YYYY-MM-DD`。クライアントのローカル日付。省略時はサーバーの UTC の日付)")
    due_soon_until: dt.date = Field(description="期限間近の終端(`today + due_soon_days`。この日を含む)")
    assigned: TodoSummaryAssignedRead = Field(description="自分が担当の ToDo の件数")
    created: TodoSummaryCreatedRead = Field(description="自分が作成した ToDo の件数")


class TodoActivityRead(BaseModel):
    """アクティビティ(変更履歴。ToDo を閲覧できる人が参照できる)。"""

    id: uuid.UUID = Field(description="アクティビティ ID(UUIDv7)")
    todo_id: uuid.UUID = Field(description="ToDo ID")
    actor_id: uuid.UUID = Field(description="操作者のユーザー ID")
    actor_display_name: str | None = Field(description="操作者の表示名(ユーザーを特定できなければ `null`)")
    action: TodoActivityAction = Field(description="種別(`created` / `updated` / `status_changed` / `assignees_changed` / `visibility_changed` / `deleted` / `checklist_changed`)")
    payload: dict[str, Any] = Field(
        description=(
            "変更の内容(JSON。日付は ISO 8601 の文字列、ID は文字列)。"
            "`created`: `{values: {title, description, status, priority, due_date, visibility, organization_ids, assignee_ids}}`、"
            "`updated`: `{changes: {<title / description / due_date / priority>: {before, after}}}`、"
            "`status_changed`: `{changes: {status: {before, after}}}`、"
            "`visibility_changed`: `{changes: {visibility: {before, after}}, organization_ids: {added, removed}}`(変わった方だけ)、"
            "`assignees_changed`: `{added: [...], removed: [...]}`、"
            "`deleted`: `{title}`、"
            "`checklist_changed`: `{op, item_id, title}`(`op` は `added` / `renamed` / `removed` / `checked` / `unchecked`。`renamed` は `before` / `after` に名前。並べ替えは記録しない)"
        )
    )
    created_at: UtcDatetime = Field(description="記録日時(UTC)。1 回の操作で複数の行を記録したときは同じ値")


class TodoActivityUser(BaseModel):
    """アクティビティが参照するユーザーの表示用の情報。"""

    display_name: str = Field(description="表示名")
    is_active: bool = Field(description="有効か。無効化されたユーザーも含む(画面では「無効」と表示する)")


class TodoActivityPage(CursorPage[TodoActivityRead]):
    """アクティビティ一覧(新しい順。カーソル方式)。"""

    users: dict[uuid.UUID, TodoActivityUser] = Field(
        description=(
            "このページのアクティビティが参照するユーザーの表示名。キーはユーザー ID(UUID の文字列)。"
            "対象は操作者(`actor_id`)と `payload` に含まれるユーザー ID(`created` の `values.assignee_ids`、`assignees_changed` の `added` / `removed`)。"
            "無効化されたユーザー・担当者から外れたユーザーも含む。キーが無い ID(テナント内に存在しないユーザー)は「不明なユーザー」等と表示する"
        )
    )


class TodoCreate(BaseModel):
    """ToDo 作成のリクエスト。作成者は操作者になる。"""

    title: str = Field(min_length=1, max_length=TODO_TITLE_MAX_LENGTH, description="タイトル(前後の空白を除いて 1〜200 文字。制御文字は不可)")
    description: str | None = Field(default=None, max_length=TODO_DESCRIPTION_MAX_LENGTH, description="説明(最大 10,000 文字。空文字は `null` として扱う)")
    due_date: dt.date | None = Field(default=None, description="期限(日付。`YYYY-MM-DD`。時刻は持たない)")
    priority: TodoPriority = Field(default=TodoPriority.MEDIUM, description="優先度。省略時は `medium`")
    status: TodoStatus = Field(default=TodoStatus.OPEN, description="ステータス。省略時は `open`")
    visibility: TodoVisibility = Field(default=TodoVisibility.PRIVATE, description="閲覧範囲。省略時は `private`")
    organization_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=TODO_ORGANIZATIONS_MAX, description="公開先の組織 ID。`visibility` が `organization` のときは有効な組織を 1 つ以上必須、それ以外では指定できない(422)"
    )
    assignee_ids: list[uuid.UUID] = Field(default_factory=list, max_length=TODO_ASSIGNEES_MAX, description=f"担当者のユーザー ID(最大 {TODO_ASSIGNEES_MAX} 人。テナント内の有効なユーザー)")


class TodoUpdate(BaseModel):
    """ToDo 更新のリクエスト(`PATCH`。送った項目だけを更新する。03 §1)。

    `description` と `due_date` の `null` は値を消す。それ以外の項目の `null` は指定できない(422)。
    """

    title: str | SkipJsonSchema[None] = Field(default=None, min_length=1, max_length=TODO_TITLE_MAX_LENGTH, description="タイトル(前後の空白を除いて 1〜200 文字)")
    description: str | None = Field(default=None, max_length=TODO_DESCRIPTION_MAX_LENGTH, description="説明(最大 10,000 文字)。`null` または空文字で消す")
    due_date: dt.date | None = Field(default=None, description="期限(`YYYY-MM-DD`)。`null` で消す")
    priority: TodoPriority | SkipJsonSchema[None] = Field(default=None, description="優先度")
    status: TodoStatus | SkipJsonSchema[None] = Field(default=None, description="ステータス(担当者もこの項目だけは変更できる)")
    visibility: TodoVisibility | SkipJsonSchema[None] = Field(default=None, description="閲覧範囲。`organization` にするときは `organization_ids` も指定する")
    organization_ids: Annotated[list[uuid.UUID], Field(max_length=TODO_ORGANIZATIONS_MAX)] | SkipJsonSchema[None] = Field(
        default=None, description="公開先の組織 ID の全件(置き換え)。`visibility` が `organization` のときは有効な組織を 1 つ以上必須、`organization` 以外にすると公開先は空になる"
    )

    @field_validator("title", "priority", "status", "visibility", "organization_ids", mode="before")
    @classmethod
    def _reject_explicit_null(cls, value: object) -> object:
        """送られた項目が `null` の場合は拒否する(未指定とは区別する。省略時の既定値はこの検証を通らない)。"""
        if value is None:
            raise ValueError("null は指定できません")
        return value


class TodoAssigneesReplace(BaseModel):
    """担当者の置き換えのリクエスト(全置換。03 §1)。"""

    user_ids: list[uuid.UUID] = Field(
        max_length=TODO_ASSIGNEES_MAX, description=f"担当者にするユーザー ID の全件(重複は除く。最大 {TODO_ASSIGNEES_MAX} 人。空配列で全員を外す)。テナント内に存在しないユーザー・無効化されたユーザーの新規の割り当ては 422"
    )
