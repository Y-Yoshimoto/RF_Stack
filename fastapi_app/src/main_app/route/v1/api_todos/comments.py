#!/usr/bin/env python
# coding:utf-8
"""ToDo のコメント API(``/api/v1/todos/{todo_id}/comments``。docs/spec/ToDoApp.md §6)。

``router.py`` が ``/todos`` 配下に束ねる(依存・ロールは親のルーターで適用済み)。コメントの版(``ETag`` / ``If-Match``)は ToDo 本体の版とは別で、
コメントの操作は ToDo 本体の ``version`` を変えない(§10 #16)。閲覧範囲(404)・コメントの存在(404)・権限(403)の判定は ``TodoCommentService`` が行う。
"""
import uuid

from fastapi import APIRouter, Response

from main_app.route.v1.api_todos.comment_schemas import TodoCommentPage, TodoCommentRead, TodoCommentWrite
from main_app.route.v1.deps import TodoCommentServiceDep
from main_app.route.v1.openapi import success_headers
from main_app.route.v1.paging import decode_after, encode_next_cursor, parse_sort
from modules.api_common.etag import IfMatchVersion, set_etag
from modules.api_common.pagination import CursorQuery, LimitQuery
from modules.errors.openapi import problem_responses

router = APIRouter()

# コメントの並び順は古い順で固定(ToDoApp.md §10 #19)。カーソルには並び替えの指定として含める。
_COMMENT_SORT = parse_sort("created_at", ("created_at",))


@router.get(
    "/{todo_id}/comments",
    summary="コメント一覧",
    responses=problem_responses(404, 422),
)
def list_todo_comments(todo_id: uuid.UUID, service: TodoCommentServiceDep, limit: LimitQuery = 50, cursor: CursorQuery = None) -> TodoCommentPage:
    """ToDo のコメントを古い順に、カーソル方式で返す(ToDo を閲覧できる人。`tenant_admin` / `member`)。

    論理削除されたコメントは含まない。各コメントの `permissions` で、操作者が編集・削除できるかが分かる。`version` は編集・削除の `If-Match` に使える。
    閲覧できない ToDo・存在しない ToDo は同じ 404(`todo_not_found`)。`include_total` は無い(`total` は常に `null`)。
    """
    page = service.list_comments(todo_id, limit=limit, after=decode_after(cursor, _COMMENT_SORT))
    return TodoCommentPage(items=[TodoCommentRead.model_validate(view, from_attributes=True) for view in page.items], next_cursor=encode_next_cursor(_COMMENT_SORT, page.next_after))


@router.post(
    "/{todo_id}/comments",
    status_code=201,
    summary="コメントの投稿",
    responses={**success_headers(201, "投稿したコメント", location=True), **problem_responses(404, 422)},
)
def create_todo_comment(todo_id: uuid.UUID, body: TodoCommentWrite, response: Response, service: TodoCommentServiceDep) -> TodoCommentRead:
    """コメントを投稿する(ToDo を閲覧できる人なら誰でも可。`tenant_admin` / `member`)。

    本文は前後の空白を除いて 1〜4,000 文字のプレーンテキスト(改行・タブ以外の制御文字は不可。不正なら 422 `invalid_todo_input`)。
    `ETag` ヘッダーにコメントの版を返す。ToDo 本体の `version` は変わらない。閲覧できない ToDo は 404。
    """
    view = service.create_comment(todo_id, body=body.body)
    set_etag(response, view.version)
    response.headers["Location"] = f"/api/v1/todos/{todo_id}/comments/{view.id}"
    return TodoCommentRead.model_validate(view, from_attributes=True)


@router.patch(
    "/{todo_id}/comments/{comment_id}",
    summary="コメントの編集",
    responses={**success_headers(200, "編集後のコメント"), **problem_responses(403, 404, 412, 422, 428)},
)
def update_todo_comment(todo_id: uuid.UUID, comment_id: uuid.UUID, body: TodoCommentWrite, version: IfMatchVersion, response: Response, service: TodoCommentServiceDep) -> TodoCommentRead:
    """コメントの本文を編集する(**投稿者のみ**。`tenant_admin` も他人のコメントは編集できない)。

    `If-Match` が必須(コメントの版。無ければ 428、不一致は 412 `todo_comment_version_conflict`)。他人のコメントは 403(`todo_operation_forbidden`。`operation` は `edit_comment`)。
    編集すると `version` が +1 され、`edited_at` が設定される(同じ本文での編集は何もせず、版も変わらない)。新しい `ETag` を返す。
    閲覧できない ToDo は 404(`todo_not_found`)、コメントが無い(別の ToDo のコメント・削除済みを含む)場合は 404(`todo_comment_not_found`)。
    """
    view = service.update_comment(todo_id, comment_id, expected_version=version, body=body.body)
    set_etag(response, view.version)
    return TodoCommentRead.model_validate(view, from_attributes=True)


@router.delete(
    "/{todo_id}/comments/{comment_id}",
    status_code=204,
    summary="コメントの削除",
    responses={204: {"description": "削除した(論理削除。レスポンスの本文は無い)"}, **problem_responses(403, 404, 412, 428)},
)
def delete_todo_comment(todo_id: uuid.UUID, comment_id: uuid.UUID, version: IfMatchVersion, service: TodoCommentServiceDep) -> Response:
    """コメントを削除する(論理削除。**投稿者と `tenant_admin`**)。

    `If-Match` が必須(コメントの版。無ければ 428、不一致は 412 `todo_comment_version_conflict`)。それ以外の人は 403(`todo_operation_forbidden`。`operation` は `delete_comment`)。
    削除後はコメント一覧に出ず、以降の操作は 404(`todo_comment_not_found`)。閲覧できない ToDo は 404(`todo_not_found`)。
    """
    service.delete_comment(todo_id, comment_id, expected_version=version)
    return Response(status_code=204)
