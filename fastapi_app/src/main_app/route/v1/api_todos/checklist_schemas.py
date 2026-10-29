#!/usr/bin/env python
# coding:utf-8
"""ToDo のチェックリスト API(``/api/v1/todos/{todo_id}/checklist``)のリクエスト・レスポンスのスキーマ。"""
import uuid

from pydantic import BaseModel, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from main_app.models.todo import TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH, TODO_CHECKLIST_ITEMS_MAX
from main_app.route.v1.api_todos.schemas import UserNameRead
from modules.api_common.datetime_types import UtcDatetime


class TodoChecklistPermissionsRead(BaseModel):
    """操作者がチェックリストに対して行える操作(ToDo 詳細の `permissions.can_edit_checklist` / `can_check_checklist` と同じ値)。"""

    can_edit: bool = Field(description="項目の追加・名前変更・削除・並べ替えができるか(作成者・`tenant_admin`)")
    can_check: bool = Field(description="項目の完了・未完了を切り替えられるか(作成者・担当者・`tenant_admin`)")


class TodoChecklistItemRead(BaseModel):
    """チェックリスト項目。`version` は項目の版(名前変更・完了の切り替え・削除の `If-Match` に使う)。"""

    id: uuid.UUID = Field(description="項目 ID(UUIDv7)")
    title: str = Field(description=f"項目名(1〜{TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH} 文字)")
    position: int = Field(description="並び(0 からの連番)")
    is_done: bool = Field(description="完了しているか")
    done_at: UtcDatetime | None = Field(description="完了した日時(UTC)。未完了は `null`")
    done_by: UserNameRead | None = Field(description="完了した人。未完了は `null`")
    version: int = Field(description="項目の楽観ロック用のバージョン。名前変更・完了の切り替え・削除の `If-Match` に `\"<version>\"` で指定する")
    created_at: UtcDatetime = Field(description="作成日時(UTC)")
    updated_at: UtcDatetime = Field(description="更新日時(UTC)")


class TodoChecklistRead(BaseModel):
    """チェックリスト全体(取得と、変更系すべての応答)。`ETag` ヘッダーと `version` は同じ値(チェックリストの版)。"""

    todo_id: uuid.UUID = Field(description="ToDo ID")
    version: int = Field(description="チェックリスト全体の版。項目の追加・削除・並べ替えで上がり、並べ替え(`PUT .../checklist/order`)の `If-Match` に使う。ToDo 本体の `version` とは別")
    items: list[TodoChecklistItemRead] = Field(description="項目(`position` の順)")
    done_count: int = Field(description="完了した項目の数")
    total_count: int = Field(description="項目の数")
    permissions: TodoChecklistPermissionsRead = Field(description="操作者の権限")


class TodoChecklistItemCreate(BaseModel):
    """項目の追加のリクエスト。"""

    title: str = Field(min_length=1, max_length=TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH, description=f"項目名(前後の空白を除いて 1〜{TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH} 文字。制御文字は不可)")
    position: int | None = Field(default=None, ge=0, description="挿入する位置(0 からの連番)。省略時・項目数以上の値は末尾")


class TodoChecklistItemUpdate(BaseModel):
    """項目の部分更新のリクエスト(送った項目だけを更新する。`null` は指定できない)。"""

    title: str | SkipJsonSchema[None] = Field(default=None, min_length=1, max_length=TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH, description="項目名(作成者・`tenant_admin`)")
    is_done: bool | SkipJsonSchema[None] = Field(default=None, description="完了か(作成者・担当者・`tenant_admin`)")

    @field_validator("title", "is_done", mode="before")
    @classmethod
    def _reject_explicit_null(cls, value: object) -> object:
        """送られた項目が `null` の場合は拒否する(未指定とは区別する。省略時の既定値はこの検証を通らない)。"""
        if value is None:
            raise ValueError("null は指定できません")
        return value


class TodoChecklistOrder(BaseModel):
    """並べ替えのリクエスト(全置換)。"""

    item_ids: list[uuid.UUID] = Field(
        description=f"並べ替え後の項目 ID の全件。現在の項目の集合と一致しなければ 422(`field=item_ids` / `code=mismatch`。重複・過不足・{TODO_CHECKLIST_ITEMS_MAX} 件超を含む)"
    )
