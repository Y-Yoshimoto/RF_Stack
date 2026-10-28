#!/usr/bin/env python
# coding:utf-8
"""組織管理 API(``/api/v1/organizations``。01 §8 PF-ORG-01..03、§10.2)。

認証・テナント判定・CSRF 対策・「セッションのユーザーが AP で有効か」は ``main_app.route.v1.apiapp`` のルーターで適用済み。
参照は全メンバー(``tenant_admin`` / ``member``)、変更は ``tenant_admin`` のみ。
業務ロジックは持たず、``OrganizationService`` の呼び出しとレスポンスの組み立てだけを行う。
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from main_app.repositories import organizations as org_repo
from main_app.route.v1.api_organizations.schemas import (
    OrganizationCreate,
    OrganizationDetail,
    OrganizationMembersReplace,
    OrganizationPage,
    OrganizationRead,
    OrganizationUpdate,
)
from main_app.route.v1.deps import OrganizationServiceDep, require_tenant_admin, require_tenant_member
from main_app.route.v1.openapi import success_headers
from main_app.route.v1.paging import decode_after, encode_next_cursor, parse_sort
from main_app.services.common import OrganizationView
from main_app.services.organization_service import ORGANIZATION_SORT_KEYS
from modules.api_common.etag import IfMatchVersion, set_etag
from modules.api_common.pagination import CursorQuery, LimitQuery
from modules.errors.openapi import problem_responses

router = APIRouter(dependencies=[Depends(require_tenant_member)])


def _detail(view: OrganizationView, member_ids: list[uuid.UUID]) -> OrganizationDetail:
    """組織とメンバー ID から詳細のレスポンスを作る。"""
    return OrganizationDetail.model_validate({**OrganizationRead.model_validate(view, from_attributes=True).model_dump(), "member_ids": member_ids})


@router.get("", summary="組織一覧", responses=problem_responses(422))
def list_organizations(
    service: OrganizationServiceDep,
    limit: LimitQuery = 50,
    cursor: CursorQuery = None,
    sort: Annotated[str, Query(description="並び順。`name` / `created_at`。先頭に `-` を付けると降順。同順位は `id` で安定させる")] = org_repo.DEFAULT_ORGANIZATION_SORT,
) -> OrganizationPage:
    """有効な組織(論理削除済みを除く)の一覧をカーソル方式で返す(`tenant_admin` / `member`)。

    メンバーは含まない(`GET /organizations/{organization_id}` で取得する)。各要素の `version` は更新系の `If-Match` に使える。
    """
    list_sort = parse_sort(sort, ORGANIZATION_SORT_KEYS)
    page = service.list_organizations(limit=limit, sort=str(list_sort), after=decode_after(cursor, list_sort))
    return OrganizationPage(items=[OrganizationRead.model_validate(view, from_attributes=True) for view in page.items], next_cursor=encode_next_cursor(list_sort, page.next_after))


@router.post(
    "",
    status_code=201,
    summary="組織の作成",
    responses={**success_headers(201, "作成した組織", location=True), **problem_responses(403, 409, 422)},
    dependencies=[Depends(require_tenant_admin)],
)
def create_organization(body: OrganizationCreate, response: Response, service: OrganizationServiceDep) -> OrganizationDetail:
    """組織を作成する(`tenant_admin` のみ)。メンバーは空で、`PUT /organizations/{organization_id}/members` で設定する。

    有効な組織に同じ名前(大文字小文字を区別しない)があれば 409(`organization_name_already_exists`)。
    """
    view = service.create_organization(name=body.name)
    set_etag(response, view.version)
    response.headers["Location"] = f"/api/v1/organizations/{view.id}"
    return _detail(view, [])


@router.get(
    "/{organization_id}",
    summary="組織詳細",
    responses={**success_headers(200, "組織(メンバーのユーザー ID を含む)"), **problem_responses(404, 422)},
)
def get_organization(organization_id: uuid.UUID, response: Response, service: OrganizationServiceDep) -> OrganizationDetail:
    """組織の詳細をメンバーのユーザー ID 付きで返す(`tenant_admin` / `member`)。

    他テナントの組織・存在しない組織・削除済みの組織は同じ 404。`ETag` ヘッダーにバージョンを返す。
    """
    view = service.get_organization(organization_id)
    member_ids = service.list_member_ids(organization_id)
    set_etag(response, view.version)
    return _detail(view, member_ids)


@router.patch(
    "/{organization_id}",
    summary="組織の更新",
    responses={**success_headers(200, "更新後の組織"), **problem_responses(403, 404, 409, 412, 422, 428)},
    dependencies=[Depends(require_tenant_admin)],
)
def update_organization(organization_id: uuid.UUID, body: OrganizationUpdate, version: IfMatchVersion, response: Response, service: OrganizationServiceDep) -> OrganizationRead:
    """組織名を変更する(`tenant_admin` のみ)。

    `If-Match` が必須(無ければ 428、不一致は 412)。同じ名前なら何もせず、`version` も変わらない。
    メンバーの変更は `PUT /organizations/{organization_id}/members`。
    """
    view = service.update_organization(organization_id, expected_version=version, name=body.name)
    set_etag(response, view.version)
    return OrganizationRead.model_validate(view, from_attributes=True)


@router.delete(
    "/{organization_id}",
    status_code=204,
    summary="組織の削除",
    responses={204: {"description": "削除した(論理削除。レスポンスの本文は無い)"}, **problem_responses(403, 404, 412, 428)},
    dependencies=[Depends(require_tenant_admin)],
)
def delete_organization(organization_id: uuid.UUID, version: IfMatchVersion, service: OrganizationServiceDep) -> Response:
    """組織を削除する(`tenant_admin` のみ。論理削除)。

    `If-Match` が必須(無ければ 428、不一致は 412)。削除後はこの組織を返す API は無く、以降の操作は 404 になる。
    メンバーの所属は残る(削除済みの組織は閲覧範囲の判定から除外される)。
    """
    service.delete_organization(organization_id, expected_version=version)
    return Response(status_code=204)


@router.put(
    "/{organization_id}/members",
    summary="組織のメンバーの置き換え",
    responses={**success_headers(200, "置き換え後の組織(メンバーのユーザー ID を含む)"), **problem_responses(403, 404, 412, 422, 428)},
    dependencies=[Depends(require_tenant_admin)],
)
def replace_organization_members(organization_id: uuid.UUID, body: OrganizationMembersReplace, version: IfMatchVersion, response: Response, service: OrganizationServiceDep) -> OrganizationDetail:
    """組織のメンバーを `user_ids` に置き換える(全置換。`tenant_admin` のみ)。

    `If-Match` が必須(無ければ 428、不一致は 412)。変更があれば組織の `version` が +1 される(変更が無ければそのまま)。
    テナント内に存在しないユーザー(他テナントのユーザーを含む)が含まれる場合は 422(`invalid_organization_members`)。
    無効化されたユーザーも指定できる。
    """
    view = service.set_members(organization_id, expected_version=version, user_ids=body.user_ids)
    member_ids = service.list_member_ids(organization_id)
    set_etag(response, view.version)
    return _detail(view, member_ids)
