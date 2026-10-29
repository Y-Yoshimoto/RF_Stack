#!/usr/bin/env python
# coding:utf-8
"""ToDo のコメント API(``/api/v1/todos/{todo_id}/comments``)のリクエスト・レスポンスのスキーマ。"""
import uuid

from pydantic import BaseModel, Field

from main_app.models.todo import TODO_COMMENT_BODY_MAX_LENGTH
from main_app.route.v1.api_todos.schemas import UserNameRead
from modules.api_common.datetime_types import UtcDatetime
from modules.api_common.pagination import CursorPage


class TodoCommentPermissionsRead(BaseModel):
    """操作者がそのコメントに対して行える操作(画面のボタンの出し分け用。判定はサーバーが更新時にも行う)。"""

    can_edit: bool = Field(description="編集できるか(投稿者のみ。`tenant_admin` も他人のコメントは編集できない)")
    can_delete: bool = Field(description="削除できるか(投稿者と `tenant_admin`)")


class TodoCommentRead(BaseModel):
    """コメント。`version` はコメントの版(`ETag` ヘッダーと同じ値。ToDo 本体の版とは別)。"""

    id: uuid.UUID = Field(description="コメント ID(UUIDv7)")
    todo_id: uuid.UUID = Field(description="ToDo ID")
    author: UserNameRead = Field(description="投稿者(無効化されたユーザーも残る)")
    body: str = Field(description=f"本文(プレーンテキスト。1〜{TODO_COMMENT_BODY_MAX_LENGTH:,} 文字)")
    version: int = Field(description="コメントの楽観ロック用のバージョン。編集・削除の `If-Match` に `\"<version>\"` で指定する")
    created_at: UtcDatetime = Field(description="投稿日時(UTC)")
    updated_at: UtcDatetime = Field(description="更新日時(UTC)")
    edited_at: UtcDatetime | None = Field(description="本文を編集した日時(UTC)。編集していなければ `null`(`null` でなければ「編集済み」と表示する)")
    permissions: TodoCommentPermissionsRead = Field(description="操作者がこのコメントに対して行える操作")


class TodoCommentPage(CursorPage[TodoCommentRead]):
    """コメント一覧(古い順。カーソル方式)。"""


class TodoCommentWrite(BaseModel):
    """コメントの投稿・編集のリクエスト。"""

    body: str = Field(min_length=1, max_length=TODO_COMMENT_BODY_MAX_LENGTH, description=f"本文(前後の空白を除いて 1〜{TODO_COMMENT_BODY_MAX_LENGTH:,} 文字のプレーンテキスト。改行・タブ以外の制御文字は不可)")
