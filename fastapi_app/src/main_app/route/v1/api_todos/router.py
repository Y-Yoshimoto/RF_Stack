#!/usr/bin/env python
# coding:utf-8
"""ToDo API(``/api/v1/todos``。docs/spec/ToDoApp.md §6)。

認証・テナント判定・CSRF 対策・「セッションのユーザーが AP で有効か」は ``main_app.route.v1.apiapp`` のルーターで適用済み。
ここでは ``tenant_admin`` / ``member`` のどちらも使える(ルーターの依存)とし、ToDo ごとの閲覧範囲(見えなければ 404)と
操作の権限(403)の判定は ``TodoService`` が行う。業務ロジックは持たず、サービスの呼び出しとレスポンスの組み立てだけを行う。
"""
import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from main_app.route.v1.api_todos.checklist import router as checklist_router
from main_app.route.v1.api_todos.comments import router as comments_router
from main_app.route.v1.api_todos.schemas import (
    TodoActivityPage,
    TodoActivityRead,
    TodoActivityUser,
    TodoAssigneesReplace,
    TodoCreate,
    TodoDetail,
    TodoPage,
    TodoRead,
    TodoSummaryAssignedRead,
    TodoSummaryCreatedRead,
    TodoSummaryRead,
    TodoUpdate,
)
from main_app.route.v1.deps import TodoServiceDep, require_tenant_member
from main_app.route.v1.openapi import success_headers
from main_app.route.v1.paging import decode_after, encode_next_cursor, parse_sort
from main_app.services.common import UNSET
from main_app.services.todo_policy import TodoScope
from main_app.services.todo_service import DEFAULT_DUE_SOON_DAYS, DEFAULT_TODO_SORT, TODO_SORT_KEYS
from modules.api_common.etag import IfMatchVersion, set_etag
from modules.api_common.pagination import CursorQuery, IncludeTotalQuery, LimitQuery
from modules.errors.openapi import problem_responses

router = APIRouter(dependencies=[Depends(require_tenant_member)])
# コメント・チェックリストは別ファイル。パスは ``/{todo_id}/comments``・``/{todo_id}/checklist`` 以下(``/summary`` は下で ``/{todo_id}`` より先に宣言する)
router.include_router(comments_router)
router.include_router(checklist_router)

# アクティビティの並び順は新しい順で固定(ToDoApp.md §10 #15)。カーソルには並び替えの指定として含める。
_ACTIVITY_SORT = parse_sort("-created_at", ("created_at",))


def _split_values(raw: str | None) -> list[str] | None:
    """カンマ区切りの複数値(03 §3)を分ける。空の要素は除き、値の検証はサービスが行う(不正なら 422)。"""
    if raw is None:
        return None
    return [value.strip() for value in raw.split(",") if value.strip()]


@router.get(
    "",
    summary="ToDo 一覧",
    responses=problem_responses(422),
)
def list_todos(
    service: TodoServiceDep,
    limit: LimitQuery = 50,
    cursor: CursorQuery = None,
    scope: Annotated[
        TodoScope,
        Query(description="表示範囲。`mine`(自分が作成)/ `assigned`(自分が担当)/ `shared`(閲覧できるが作成者でも担当者でもない)/ `all`(閲覧できるすべて)。いずれも閲覧できるものに限る"),
    ] = TodoScope.ALL,
    status: Annotated[str | None, Query(description="ステータスで絞り込む。`open` / `in_progress` / `done`。複数はカンマ区切り(例: `open,in_progress`)")] = None,
    priority: Annotated[str | None, Query(description="優先度で絞り込む。`low` / `medium` / `high`。複数はカンマ区切り(例: `medium,high`)")] = None,
    q: Annotated[str | None, Query(max_length=200, description="タイトルの部分一致(大文字小文字を区別しない)")] = None,
    organization_id: Annotated[uuid.UUID | None, Query(description="公開先に含まれる(有効な)組織で絞り込む")] = None,
    assignee_id: Annotated[uuid.UUID | None, Query(description="担当者に含まれるユーザーで絞り込む")] = None,
    due_before: Annotated[dt.date | None, Query(description="期限がこの日以前(この日を含む。`YYYY-MM-DD`)。期限なしは除く")] = None,
    due_after: Annotated[dt.date | None, Query(description="期限がこの日以降(この日を含む。`YYYY-MM-DD`)。期限なしは除く")] = None,
    sort: Annotated[
        str,
        Query(
            description=(
                "並び順。`due_date` / `priority` / `created_at` / `updated_at`。先頭に `-` を付けると降順。同順位は `id` で安定させる。"
                "**キーは 1 つだけ**で、03 §3 の複数キー(`due_date,-priority`)には未対応(指定すると 422)。"
                "`due_date` の期限なしは昇順で末尾・降順で先頭、`priority` は `low < medium < high`"
            )
        ),
    ] = DEFAULT_TODO_SORT,
    include_total: IncludeTotalQuery = False,
) -> TodoPage:
    """閲覧できる ToDo(論理削除済みを除く)の一覧をカーソル方式で返す(`tenant_admin` / `member`)。

    `tenant_admin` はテナント内の全件、`member` は閲覧範囲のルール(`private` は作成者と担当者のみ、`organization` は公開先組織の所属メンバーなど)で見えるものだけ。
    説明(`description`)は含まない(`GET /todos/{todo_id}` で取得する)。各要素の `version` は更新系の `If-Match` に使える。
    各要素に作成者・最終更新者(`creator` / `updater`)、チェックリストの進捗(`checklist`)、コメント数(`comment_count`)を含む。
    `include_total=true` のときだけ、表示範囲・絞り込みを適用した総件数(カーソルに依存しない)を `total` に入れる(件数を数える分だけ重くなるため、先頭ページだけで指定する)。省略時の `total` は `null`。
    `status` / `priority` / `sort` / `scope` が不正、またはカーソルが壊れている場合は 422。
    """
    list_sort = parse_sort(sort, TODO_SORT_KEYS)
    page = service.list_todos(
        scope=scope,
        status=_split_values(status),
        priority=_split_values(priority),
        q=q,
        organization_id=organization_id,
        assignee_id=assignee_id,
        due_before=due_before,
        due_after=due_after,
        sort=str(list_sort),
        limit=limit,
        after=decode_after(cursor, list_sort),
        include_total=include_total,
    )
    return TodoPage(items=[TodoRead.model_validate(view, from_attributes=True) for view in page.items], next_cursor=encode_next_cursor(list_sort, page.next_after), total=page.total)


@router.get(
    "/summary",
    summary="ホームの要約",
    responses=problem_responses(422),
)
def get_todo_summary(
    service: TodoServiceDep,
    today: Annotated[dt.date | None, Query(description="今日の日付(`YYYY-MM-DD`。クライアントのローカル日付)。省略時はサーバーの UTC の日付")] = None,
    due_soon_days: Annotated[int, Query(ge=1, le=30, description="期限間近とみなす日数(1〜30)。`today` から数えて、この日数後の日を含む")] = DEFAULT_DUE_SOON_DAYS,
) -> TodoSummaryRead:
    """ホームに出す ToDo の件数の要約を返す(`tenant_admin` / `member`)。閲覧できる ToDo だけを数え、完了(`done`)と削除済みは含まない。

    `assigned`(自分が担当)は `open` / `in_progress` / `overdue`(`due_date < today`)/ `due_soon`(`today <= due_date <= due_soon_until`)、
    `created`(自分が作成)は `open` / `in_progress` / `overdue`。`due_soon_until` は `today + due_soon_days`。`today` / `due_soon_days` が不正な場合は 422。
    `/{todo_id}` より前に宣言している(`summary` を ToDo の ID と解釈しない)。
    """
    view = service.summarize(today=today, due_soon_days=due_soon_days)
    return TodoSummaryRead(
        today=view.today,
        due_soon_until=view.due_soon_until,
        assigned=TodoSummaryAssignedRead.model_validate(view.assigned, from_attributes=True),
        created=TodoSummaryCreatedRead.model_validate(view.created, from_attributes=True),
    )


@router.post(
    "",
    status_code=201,
    summary="ToDo の作成",
    responses={**success_headers(201, "作成した ToDo", location=True), **problem_responses(422)},
)
def create_todo(body: TodoCreate, response: Response, service: TodoServiceDep) -> TodoDetail:
    """ToDo を作成する(`tenant_admin` / `member`)。作成者は操作者になる。

    `visibility` が `organization` のときは `organization_ids` に有効な組織を 1 つ以上指定する(それ以外では指定できない)。
    担当者(`assignee_ids`)はテナント内の有効なユーザーで最大 20 人。不正な入力は 422(`invalid_todo_input` / `invalid_todo_assignees` / `invalid_todo_organizations`)。
    """
    view = service.create_todo(
        title=body.title,
        description=body.description,
        due_date=body.due_date,
        priority=body.priority,
        status=body.status,
        visibility=body.visibility,
        organization_ids=body.organization_ids,
        assignee_ids=body.assignee_ids,
    )
    set_etag(response, view.version)
    response.headers["Location"] = f"/api/v1/todos/{view.id}"
    return TodoDetail.model_validate(view, from_attributes=True)


@router.get(
    "/{todo_id}",
    summary="ToDo 詳細",
    responses={**success_headers(200, "ToDo(説明と操作者の権限を含む)"), **problem_responses(404, 422)},
)
def get_todo(todo_id: uuid.UUID, response: Response, service: TodoServiceDep) -> TodoDetail:
    """ToDo の詳細を返す(`tenant_admin` / `member`)。

    説明と、操作者の権限(`permissions`。画面のボタンの出し分け用)を含む。`ETag` ヘッダーにバージョンを返す。
    他テナントの ToDo・存在しない ToDo・削除済みの ToDo・閲覧範囲外の ToDo は同じ 404(`todo_not_found`)。
    """
    view = service.get_todo(todo_id)
    set_etag(response, view.version)
    return TodoDetail.model_validate(view, from_attributes=True)


@router.patch(
    "/{todo_id}",
    summary="ToDo の更新",
    responses={**success_headers(200, "更新後の ToDo"), **problem_responses(403, 404, 412, 422, 428)},
)
def update_todo(todo_id: uuid.UUID, body: TodoUpdate, version: IfMatchVersion, response: Response, service: TodoServiceDep) -> TodoDetail:
    """ToDo を部分更新する(送った項目だけ。`tenant_admin` / `member`)。閲覧範囲(`visibility`)と公開先組織(`organization_ids`)もここで変更する。

    `If-Match` が必須(無ければ 428、不一致は 412)。権限は**実際に値が変わる項目**で判定する(同じ値を送った項目は変更とみなさない)。
    項目(タイトル・説明・期限・優先度)と閲覧範囲の変更は作成者と `tenant_admin`、ステータスの変更は担当者も可。権限が無い項目が変わる場合は 403(`todo_operation_forbidden`。`operation` に拒否した操作)。
    値が変わらない更新は何も記録せず、`version` も変わらない。`description` / `due_date` の `null` は値を消す。閲覧できない ToDo は 404。
    """
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    view = service.update_todo(
        todo_id,
        expected_version=version,
        title=changes.get("title", UNSET),
        description=changes.get("description", UNSET),
        due_date=changes.get("due_date", UNSET),
        priority=changes.get("priority", UNSET),
        status=changes.get("status", UNSET),
        visibility=changes.get("visibility", UNSET),
        organization_ids=changes.get("organization_ids", UNSET),
    )
    set_etag(response, view.version)
    return TodoDetail.model_validate(view, from_attributes=True)


@router.delete(
    "/{todo_id}",
    status_code=204,
    summary="ToDo の削除",
    responses={204: {"description": "削除した(論理削除。レスポンスの本文は無い)"}, **problem_responses(403, 404, 412, 428)},
)
def delete_todo(todo_id: uuid.UUID, version: IfMatchVersion, service: TodoServiceDep) -> Response:
    """ToDo を削除する(論理削除。作成者と `tenant_admin` のみ。担当者は 403)。

    `If-Match` が必須(無ければ 428、不一致は 412)。削除後は誰も参照できず、以降の操作は 404 になる。
    """
    service.delete_todo(todo_id, expected_version=version)
    return Response(status_code=204)


@router.put(
    "/{todo_id}/assignees",
    summary="担当者の置き換え",
    responses={**success_headers(200, "置き換え後の ToDo"), **problem_responses(403, 404, 412, 422, 428)},
)
def replace_todo_assignees(todo_id: uuid.UUID, body: TodoAssigneesReplace, version: IfMatchVersion, response: Response, service: TodoServiceDep) -> TodoDetail:
    """ToDo の担当者を `user_ids` に置き換える(全置換。作成者・担当者・`tenant_admin`)。

    `If-Match` が必須(無ければ 428、不一致は 412)。変更があれば `version` が +1 される(変更が無ければそのまま)。残る担当者の割り当て日時・割り当てた人は保たれる。
    テナント内に存在しないユーザー(他テナントを含む)、無効化されたユーザーの**新規**の割り当ては 422(`invalid_todo_assignees`。`reason` は `not_found` / `inactive`)。
    既に担当者の無効化されたユーザーを外すことはできる。
    """
    view = service.set_assignees(todo_id, expected_version=version, user_ids=body.user_ids)
    set_etag(response, view.version)
    return TodoDetail.model_validate(view, from_attributes=True)


@router.get(
    "/{todo_id}/activities",
    summary="アクティビティ一覧",
    responses=problem_responses(404, 422),
)
def list_todo_activities(todo_id: uuid.UUID, service: TodoServiceDep, limit: LimitQuery = 50, cursor: CursorQuery = None) -> TodoActivityPage:
    """ToDo のアクティビティ(変更履歴)を新しい順に、カーソル方式で返す(ToDo を閲覧できる人。`tenant_admin` / `member`)。

    同じ操作で記録した行は記録順の逆。`payload` の形は `action` ごとに異なる(`TodoActivityRead.payload` を参照)。
    `users` に、このページが参照するユーザー(操作者と `payload` のユーザー ID)の表示名と有効かを、ユーザー ID をキーにして返す(画面で名前を引くため)。
    閲覧できない ToDo・存在しない ToDo は同じ 404(`todo_not_found`)。
    """
    page = service.list_activities(todo_id, limit=limit, after=decode_after(cursor, _ACTIVITY_SORT))
    return TodoActivityPage(
        items=[TodoActivityRead.model_validate(view, from_attributes=True) for view in page.items],
        next_cursor=encode_next_cursor(_ACTIVITY_SORT, page.next_after),
        users={user_id: TodoActivityUser(display_name=name.display_name, is_active=name.is_active) for user_id, name in page.users.items()},
    )
