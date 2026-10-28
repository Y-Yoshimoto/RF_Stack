#!/usr/bin/env python
# coding:utf-8
"""テナント管理 API（``/api/v1/cp/tenants``。01 §10.2）。

認証・認可（CP セッション、``saas_admin`` / ``saas_viewer``）と CSRF 対策は ``control_plane_app.apiapp`` のルーターで
適用済み。ここでは変更系のエンドポイントに ``saas_admin`` を要求する。業務ロジックは持たず、
``TenantProvisioningService`` と読み取り用リポジトリの呼び出しだけを行う。
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from control_plane_app.api_tenants.deps import CpAdminDep, ProvisioningServiceDep, require_saas_admin
from control_plane_app.api_tenants.paging import build_tenant_page
from control_plane_app.api_tenants.schemas import (
    InitialAdminInput,
    ProvisioningHistoryRead,
    ProvisioningRetryRequest,
    TenantCreate,
    TenantDetail,
    TenantPage,
    TenantProvisioned,
    TenantRead,
)
from control_plane_app.repositories import tenant_query
from control_plane_app.repositories import tenant_repository as repo
from control_plane_app.services.errors import TenantNotFoundError
from control_plane_app.services.tenant_provisioning import InitialAdminSpec, OnboardResult, TenantView
from modules.api_common.etag import IfMatchVersion, OptionalIfMatchVersion, set_etag
from modules.api_common.pagination import CursorQuery, IncludeTotalQuery, LimitQuery
from modules.errors.openapi import problem_responses
from modules.errors.request_id import get_request_id
from modules.tenancy.providers import CpSessionDep

router = APIRouter()

# 認証情報を含むレスポンスをキャッシュさせない。
_NO_STORE = "no-store"


def _admin_spec(initial_admin: InitialAdminInput) -> InitialAdminSpec:
    """リクエストの初期管理者を、サービスの入力にする（省略された項目はサービスの既定値）。"""
    optional = {name: value for name, value in (("username", initial_admin.username), ("first_name", initial_admin.first_name), ("last_name", initial_admin.last_name)) if value is not None}
    return InitialAdminSpec(email=initial_admin.email, **optional)


def _provisioned(result: OnboardResult, response: Response) -> TenantProvisioned:
    """払い出し結果をレスポンスにする。一時パスワードを含むためキャッシュを禁止する。"""
    set_etag(response, result.tenant.version)
    response.headers["Cache-Control"] = _NO_STORE
    return TenantProvisioned.model_validate(
        {
            "tenant": TenantRead.model_validate(result.tenant, from_attributes=True),
            "initial_admin": {"username": result.initial_admin_username, "temporary_password": result.temporary_password},
            "provisioning_history_id": result.history_id,
        }
    )


def _tenant_response(view: TenantView, response: Response) -> TenantRead:
    """テナントをレスポンスにする（`ETag` 付き）。"""
    set_etag(response, view.version)
    return TenantRead.model_validate(view, from_attributes=True)


@router.get(
    "",
    summary="テナント一覧",
    responses=problem_responses(422),
)
def list_tenants(
    session: CpSessionDep,
    limit: LimitQuery = 50,
    cursor: CursorQuery = None,
    include_total: IncludeTotalQuery = False,
    sort: Annotated[str, Query(description="並び順。`created_at` / `tenant_code` / `name`。先頭に `-` を付けると降順。同順位は `id` で安定させる")] = tenant_query.DEFAULT_SORT,
    status_filter: Annotated[str | None, Query(alias="status", description="状態で絞り込む。複数はカンマ区切り（例: `ACTIVE,SUSPENDED`）。省略時は削除済みを含む全件")] = None,
) -> TenantPage:
    """テナントの一覧をカーソル方式で返す（`saas_admin` / `saas_viewer`）。

    名前・テナントコード・状態・作成日時に加え、直近の日次メトリクスのユーザー数（総数・有効数）を含む。
    メトリクスの集計前は `null`。総件数は `include_total=true` のときだけ `total` に入る。
    """
    return build_tenant_page(session, limit=limit, cursor=cursor, include_total=include_total, sort=sort, status_filter=status_filter)


@router.post(
    "",
    status_code=201,
    summary="テナントの作成（払い出し）",
    responses=problem_responses(409, 422, 502),
    dependencies=[Depends(require_saas_admin)],
)
def create_tenant(body: TenantCreate, response: Response, user: CpAdminDep, service: ProvisioningServiceDep) -> TenantProvisioned:
    """テナントを作成し、払い出しを**同期実行**する（`saas_admin` のみ）。

    台帳登録、認証領域の作成、初期管理者の作成、`ACTIVE` 化までをこのリクエスト内で行う（目安 30 秒以内）。
    初期管理者の**一時パスワードはこのレスポンスでのみ返す**（保存しない。ログにも出さない）。

    途中で失敗した場合はテナントを `FAILED` として記録し、502（`tenant_provisioning_failed`）を返す。
    本文の `tenant_id` を使って `POST /tenants/{tenant_id}/provisioning/retry` で再実行できる。
    """
    result = service.onboard(
        tenant_code=body.tenant_code,
        name=body.name,
        initial_admin=_admin_spec(body.initial_admin),
        actor=user["sub"],
        request_id=get_request_id(),
    )
    response.headers["Location"] = f"/api/v1/cp/tenants/{result.tenant.id}"
    return _provisioned(result, response)


@router.get(
    "/{tenant_id}",
    summary="テナント詳細",
    responses=problem_responses(404, 422),
)
def get_tenant(tenant_id: uuid.UUID, session: CpSessionDep, response: Response) -> TenantDetail:
    """テナントの詳細と払い出し履歴（新しい順）を返す（`saas_admin` / `saas_viewer`）。

    `ETag` ヘッダーにバージョンを返す。更新系（停止・再開・削除）の `If-Match` に使う。
    メトリクスの推移は `GET /tenants/{tenant_id}/metrics`。
    """
    tenant = repo.get_tenant(session, tenant_id)
    if tenant is None:
        raise TenantNotFoundError(tenant_id)
    histories = repo.list_provisioning_histories(session, tenant_id)
    set_etag(response, tenant.version)
    return TenantDetail(
        **TenantRead.model_validate(tenant, from_attributes=True).model_dump(),
        provisioning_history=[ProvisioningHistoryRead.model_validate(history, from_attributes=True) for history in histories],
    )


@router.post(
    "/{tenant_id}/suspend",
    summary="テナントの停止",
    responses=problem_responses(404, 409, 412, 422, 428, 502),
    dependencies=[Depends(require_saas_admin)],
)
def suspend_tenant(tenant_id: uuid.UUID, version: IfMatchVersion, response: Response, user: CpAdminDep, service: ProvisioningServiceDep) -> TenantRead:
    """テナントを停止する（`ACTIVE` → `SUSPENDED`。`saas_admin` のみ）。

    認証領域を無効化し、AP の API は 403 になる（レジストリのキャッシュ期間 30 秒以内に反映される）。
    `If-Match` が必須（無ければ 428、不一致は 412）。
    """
    view = service.suspend(tenant_id, actor=user["sub"], expected_version=version, request_id=get_request_id())
    return _tenant_response(view, response)


@router.post(
    "/{tenant_id}/resume",
    summary="テナントの再開",
    responses=problem_responses(404, 409, 412, 422, 428, 502),
    dependencies=[Depends(require_saas_admin)],
)
def resume_tenant(tenant_id: uuid.UUID, version: IfMatchVersion, response: Response, user: CpAdminDep, service: ProvisioningServiceDep) -> TenantRead:
    """停止中のテナントを再開する（`SUSPENDED` → `ACTIVE`。`saas_admin` のみ）。

    `If-Match` が必須（無ければ 428、不一致は 412）。
    """
    view = service.resume(tenant_id, actor=user["sub"], expected_version=version, request_id=get_request_id())
    return _tenant_response(view, response)


@router.delete(
    "/{tenant_id}",
    summary="テナントの削除要求",
    responses=problem_responses(404, 409, 412, 422, 428, 502),
    dependencies=[Depends(require_saas_admin)],
)
def request_tenant_deletion(tenant_id: uuid.UUID, version: IfMatchVersion, response: Response, user: CpAdminDep, service: ProvisioningServiceDep) -> TenantRead:
    """テナントの削除を要求する（`ACTIVE` / `SUSPENDED` / `FAILED` → `PENDING_DELETION`。`saas_admin` のみ）。

    認証領域を無効化し、AP の API は 403 になる。データは猶予期間（30 日）保持され、経過後に定期ジョブが物理削除する
    （復元 API は提供しない）。このリクエストでは物理削除しない。`If-Match` が必須（無ければ 428、不一致は 412）。
    """
    view = service.request_deletion(tenant_id, actor=user["sub"], expected_version=version, request_id=get_request_id())
    return _tenant_response(view, response)


@router.post(
    "/{tenant_id}/provisioning/retry",
    summary="払い出しの再実行",
    responses=problem_responses(404, 409, 412, 422, 502),
    dependencies=[Depends(require_saas_admin)],
)
def retry_provisioning(
    tenant_id: uuid.UUID,
    body: ProvisioningRetryRequest,
    version: OptionalIfMatchVersion,
    response: Response,
    user: CpAdminDep,
    service: ProvisioningServiceDep,
) -> TenantProvisioned:
    """失敗（`FAILED`）または中断した払い出しを再実行する（`saas_admin` のみ）。

    初期管理者の情報は台帳に保存していないため、本文で再度指定する。各ステップは冪等で、作成済みの認証領域・ユーザーは再利用する。
    初期管理者の一時パスワードは**新しいものに設定し直し、このレスポンスでのみ返す**。
    `If-Match` は任意（指定した場合は不一致で 412）。
    """
    result = service.retry(tenant_id, initial_admin=_admin_spec(body.initial_admin), actor=user["sub"], expected_version=version, request_id=get_request_id())
    return _provisioned(result, response)
