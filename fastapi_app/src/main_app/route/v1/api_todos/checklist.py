#!/usr/bin/env python
# coding:utf-8
"""ToDo のチェックリスト API(``/api/v1/todos/{todo_id}/checklist``。docs/spec/ToDoApp.md §6)。

``router.py`` が ``/todos`` 配下に束ねる(依存・ロールは親のルーターで適用済み)。変更系の応答はすべてチェックリスト全体(``TodoChecklistRead``)と、
``ETag``(チェックリスト全体の版)。``If-Match`` の対象は、項目の名前変更・完了の切り替え・削除が**項目の版**、並べ替えが**チェックリストの版**、項目の追加は不要(§10 #17)。
ToDo 本体の ``version`` は変わらない(§10 #16)。閲覧範囲(404)・項目の存在(404)・権限(403)の判定は ``TodoChecklistService`` が行う。
"""
import uuid

from fastapi import APIRouter, Response

from main_app.route.v1.api_todos.checklist_schemas import TodoChecklistItemCreate, TodoChecklistItemUpdate, TodoChecklistOrder, TodoChecklistRead
from main_app.route.v1.deps import TodoChecklistServiceDep
from main_app.route.v1.openapi import success_headers
from main_app.services.common import UNSET
from main_app.services.todo_checklist_service import TodoChecklistView
from modules.api_common.etag import IfMatchVersion, set_etag
from modules.errors.openapi import problem_responses

router = APIRouter()


def _checklist_response(view: TodoChecklistView, response: Response) -> TodoChecklistRead:
    """チェックリスト全体のレスポンスを作り、``ETag`` にチェックリストの版を付ける。"""
    set_etag(response, view.version)
    return TodoChecklistRead.model_validate(view, from_attributes=True)


@router.get(
    "/{todo_id}/checklist",
    summary="チェックリストの取得",
    responses={**success_headers(200, "チェックリスト(項目は `position` の順。操作者の権限付き)"), **problem_responses(404)},
)
def get_todo_checklist(todo_id: uuid.UUID, response: Response, service: TodoChecklistServiceDep) -> TodoChecklistRead:
    """ToDo のチェックリスト全体を返す(ToDo を閲覧できる人。`tenant_admin` / `member`)。

    `ETag` ヘッダーに**チェックリスト全体の版**(ToDo 本体の版ではない)を返す。項目の版は各項目の `version`。
    閲覧できない ToDo・存在しない ToDo は同じ 404(`todo_not_found`)。
    """
    return _checklist_response(service.get_checklist(todo_id), response)


@router.post(
    "/{todo_id}/checklist/items",
    status_code=201,
    summary="チェックリスト項目の追加",
    responses={**success_headers(201, "追加後のチェックリスト全体"), **problem_responses(403, 404, 422)},
)
def add_todo_checklist_item(todo_id: uuid.UUID, body: TodoChecklistItemCreate, response: Response, service: TodoChecklistServiceDep) -> TodoChecklistRead:
    """チェックリストに項目を追加する(作成者・`tenant_admin`)。`If-Match` は不要。

    `position` の位置(省略・末尾より後は末尾)に挿入し、チェックリスト全体の版が +1 される。応答はチェックリスト全体と新しい `ETag`。
    1 件の ToDo につき項目は 100 件まで(超えると 422 `invalid_todo_input`。`errors[]` は `field=items` / `code=too_many`)。権限が無ければ 403(`operation` は `edit_checklist`)。
    """
    return _checklist_response(service.add_item(todo_id, title=body.title, position=body.position), response)


@router.patch(
    "/{todo_id}/checklist/items/{item_id}",
    summary="チェックリスト項目の更新",
    responses={**success_headers(200, "更新後のチェックリスト全体"), **problem_responses(403, 404, 412, 422, 428)},
)
def update_todo_checklist_item(
    todo_id: uuid.UUID, item_id: uuid.UUID, body: TodoChecklistItemUpdate, version: IfMatchVersion, response: Response, service: TodoChecklistServiceDep
) -> TodoChecklistRead:
    """項目の名前変更・完了の切り替えを行う(送った項目だけ)。

    `If-Match` が必須(**項目の版**。無ければ 428、不一致は 412 `todo_checklist_version_conflict`。拡張メンバー `target` は `item`)。
    権限は**実際に値が変わる項目**で判定する: 名前の変更は作成者・`tenant_admin`(`edit_checklist`)、完了の切り替えは担当者も可(`check_checklist_item`)。権限が無ければ 403。
    値が変わらない更新は何もせず、版も変わらない。応答はチェックリスト全体で、`ETag` はチェックリスト全体の版(項目の追加・削除・並べ替え以外では変わらない)。
    ToDo が閲覧できなければ 404(`todo_not_found`)、項目が無ければ 404(`todo_checklist_item_not_found`)。
    """
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    view = service.update_item(todo_id, item_id, expected_version=version, title=changes.get("title", UNSET), is_done=changes.get("is_done", UNSET))
    return _checklist_response(view, response)


@router.delete(
    "/{todo_id}/checklist/items/{item_id}",
    summary="チェックリスト項目の削除",
    responses={**success_headers(200, "削除後のチェックリスト全体(物理削除。残りの項目の `position` は詰め直す)"), **problem_responses(403, 404, 412, 428)},
)
def delete_todo_checklist_item(todo_id: uuid.UUID, item_id: uuid.UUID, version: IfMatchVersion, response: Response, service: TodoChecklistServiceDep) -> TodoChecklistRead:
    """項目を削除する(物理削除。作成者・`tenant_admin`)。

    `If-Match` が必須(**項目の版**。無ければ 428、不一致は 412 `todo_checklist_version_conflict`。拡張メンバー `target` は `item`)。
    **200** で削除後のチェックリスト全体と新しい `ETag`(チェックリストの版が +1)を返す。権限が無ければ 403(`operation` は `edit_checklist`)。
    """
    return _checklist_response(service.delete_item(todo_id, item_id, expected_version=version), response)


@router.put(
    "/{todo_id}/checklist/order",
    summary="チェックリストの並べ替え",
    responses={**success_headers(200, "並べ替え後のチェックリスト全体"), **problem_responses(403, 404, 412, 422, 428)},
)
def reorder_todo_checklist(todo_id: uuid.UUID, body: TodoChecklistOrder, version: IfMatchVersion, response: Response, service: TodoChecklistServiceDep) -> TodoChecklistRead:
    """項目を `item_ids` の順に並べ替える(全置換。作成者・`tenant_admin`)。

    `If-Match` が必須(**チェックリスト全体の版**。無ければ 428、不一致は 412 `todo_checklist_version_conflict`。拡張メンバー `target` は `checklist`)。
    `item_ids` が現在の項目の集合と一致しない(重複・過不足を含む)場合は 422(`invalid_todo_input`。`errors[]` は `field=item_ids` / `code=mismatch`)。
    並べ替えでチェックリストの版が +1 される。応答はチェックリスト全体と新しい `ETag`。権限が無ければ 403(`operation` は `edit_checklist`)。
    """
    return _checklist_response(service.reorder_items(todo_id, expected_version=version, item_ids=body.item_ids), response)
