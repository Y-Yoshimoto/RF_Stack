#!/usr/bin/env python
# coding:utf-8
"""ユーザー管理 API(``/api/v1/users``。01 §8 PF-USR-01..03、§10.2)。

認証・テナント判定・CSRF 対策・「セッションのユーザーが AP で有効か」は ``main_app.route.v1.apiapp`` のルーターで適用済み。
参照は全メンバー(``tenant_admin`` / ``member``)、変更は ``tenant_admin`` のみ。
業務ロジックは持たず、``UserService`` の呼び出しとレスポンスの組み立てだけを行う。
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from main_app.repositories import users as user_repo
from main_app.route.v1.api_users.schemas import UserCreate, UserCreated, UserCredentials, UserDetail, UserPage, UserRead, UserUpdate
from main_app.route.v1.deps import UserServiceDep, require_tenant_admin, require_tenant_member
from main_app.route.v1.openapi import success_headers
from main_app.route.v1.paging import decode_after, encode_next_cursor, parse_sort
from main_app.services.common import UNSET, UserView
from main_app.services.errors import UserValidationError
from main_app.services.user_service import USER_SORT_KEYS
from modules.api_common.etag import IfMatchVersion, set_etag
from modules.api_common.pagination import CursorQuery, LimitQuery
from modules.errors.openapi import problem_responses

router = APIRouter(dependencies=[Depends(require_tenant_member)])

# 一時パスワードを含むレスポンスをキャッシュさせない。
_NO_STORE = "no-store"


def _parse_ids(raw: str | None) -> list[uuid.UUID] | None:
    """`ids` クエリ(カンマ区切りのユーザー ID)を解釈する。指定が無ければ `None`、空文字は空のリスト(0 件)。

    Raises:
        UserValidationError: UUID でない値を含む(422)。件数の上限(重複を除いて 100)の検証はサービスが行う。
    """
    if raw is None:
        return None
    try:
        return [uuid.UUID(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise UserValidationError("ids", "format") from None


@router.get("", summary="ユーザー一覧", responses=problem_responses(422))
def list_users(
    service: UserServiceDep,
    limit: LimitQuery = 50,
    cursor: CursorQuery = None,
    sort: Annotated[str, Query(description="並び順。`display_name` / `created_at`。先頭に `-` を付けると降順。同順位は `id` で安定させる")] = user_repo.DEFAULT_USER_SORT,
    is_active: Annotated[bool | None, Query(description="`true` で有効なユーザーのみ、`false` で無効化されたユーザーのみ。省略時は両方")] = None,
    ids: Annotated[
        str | None,
        Query(
            description=(
                "ユーザー ID で絞り込む(カンマ区切りの UUID。重複を除いて最大 100 件。組織のメンバー・ToDo の担当者の表示名の解決用)。"
                "存在しない ID・他テナントの ID は結果に含まれない。空文字は 0 件。UUID でない値・100 件超は 422"
            )
        ),
    ] = None,
) -> UserPage:
    """テナント内のユーザーの一覧をカーソル方式で返す(`tenant_admin` / `member`)。

    無効化されたユーザーも含む(`is_active` で絞り込める)。`ids` で ID を指定して取得できる(`limit` を超える場合は `next_cursor` で続きを取得する)。
    姓・名・ロールは AP の DB の写し(最後に同期した時点の値。IdP には問い合わせない。最新の値は `GET /users/{user_id}` で取得する)。
    各要素の `version` は更新系の `If-Match` に使える。
    """
    list_sort = parse_sort(sort, USER_SORT_KEYS)
    page = service.list_users(limit=limit, sort=str(list_sort), after=decode_after(cursor, list_sort), is_active=is_active, ids=_parse_ids(ids))
    return UserPage(items=[UserRead.model_validate(view, from_attributes=True) for view in page.items], next_cursor=encode_next_cursor(list_sort, page.next_after))


@router.post(
    "",
    status_code=201,
    summary="ユーザーの作成",
    responses={**success_headers(201, "作成したユーザーと一時パスワード", location=True, no_store=True), **problem_responses(403, 409, 422, 502)},
    dependencies=[Depends(require_tenant_admin)],
)
def create_user(body: UserCreate, response: Response, service: UserServiceDep) -> UserCreated:
    """ユーザーを作成する(`tenant_admin` のみ)。

    認証基盤(Keycloak)のテナント認証領域と AP の両方にユーザーを作る。メールは送らない。
    **一時パスワードはこのレスポンスでのみ返す**(保存しない。ログにも出さない)。初回ログイン時にパスワードの変更が必要。

    メールアドレス・ユーザー名がテナント内で重複する場合は 409(`user_already_exists`)。
    認証基盤の操作に失敗した場合は 502(`identity_provider_operation_failed`)で、AP にはユーザーを作らない。
    """
    result = service.create_user(email=body.email, first_name=body.first_name, last_name=body.last_name, roles=body.roles, username=body.username)
    set_etag(response, result.user.version)
    response.headers["Location"] = f"/api/v1/users/{result.user.id}"
    response.headers["Cache-Control"] = _NO_STORE
    # roles は写し(実効ロール。一覧・詳細と同じ)を返す。result.roles(直接付与したロール)で上書きしない
    detail = UserDetail.model_validate(result.user, from_attributes=True)
    return UserCreated(user=detail, credentials=UserCredentials(username=result.username, temporary_password=result.temporary_password))


@router.get(
    "/{user_id}",
    summary="ユーザー詳細",
    responses={**success_headers(200, "ユーザー(ロールを含む)"), **problem_responses(404, 422, 502)},
)
def get_user(user_id: uuid.UUID, response: Response, service: UserServiceDep) -> UserDetail:
    """ユーザーの詳細を返す(`tenant_admin` / `member`)。

    姓・名・メール・ロールは認証基盤から取り直す(失敗は 502)。AP の DB の写しと違えば写しも更新する。他テナントのユーザーも存在しないユーザーも同じ 404。
    `ETag` ヘッダーにバージョンを返す。更新(`PATCH`)の `If-Match` に使う。
    """
    view = service.get_user(user_id)
    set_etag(response, view.version)
    return UserDetail.model_validate(view, from_attributes=True)


@router.patch(
    "/{user_id}",
    summary="ユーザーの更新",
    responses={**success_headers(200, "更新後のユーザー"), **problem_responses(403, 404, 409, 412, 422, 428, 502)},
    dependencies=[Depends(require_tenant_admin)],
)
def update_user(user_id: uuid.UUID, body: UserUpdate, version: IfMatchVersion, response: Response, service: UserServiceDep) -> UserDetail:
    """ユーザーの姓・名(表示名)・ロール・有効/無効を更新する(`tenant_admin` のみ。送った項目だけ)。

    `If-Match` が必須(無ければ 428、不一致は 412)。変更が無ければ何もせず、`version` も変わらない。
    `is_active=false` で無効化すると、認証基盤のユーザーも無効化し、そのユーザーのセッションは次のリクエストで失効する。
    自分自身の無効化・`tenant_admin` の解除は 409(`user_self_modification_forbidden`)。
    応答の姓・名・ロールは AP の DB の写し(姓・名・ロールを変えた場合は更新後の値。それ以外で未同期なら `null` / 空配列のことがある)。最新の値は `GET /users/{user_id}` で取得する。
    """
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    view: UserView = service.update_user(
        user_id,
        expected_version=version,
        first_name=changes.get("first_name", UNSET),
        last_name=changes.get("last_name", UNSET),
        roles=changes.get("roles", UNSET),
        is_active=changes.get("is_active", UNSET),
    )
    set_etag(response, view.version)
    return UserDetail.model_validate(view, from_attributes=True)
