#!/usr/bin/env python
# coding:utf-8
"""テナント存在確認（``/api/v1/public/tenants/{tenant_code}``。01 §10.2）。認証なし。

ログイン画面・フロントのルーティング（予約語以外の第 1 セグメントがテナントか。02 §5.4）が使う。

- 返すのは ``tenant_code`` と ``status`` のみ。認証領域名・クライアント ID・テナント名は返さない。
- 存在しない・削除済み・形式不正・予約語は**区別せず同じ 404**（テナント列挙の抑止）。
- IP 単位の簡易なレート制限を適用する（超過は 429。``main_app.route.public.rate_limit``）。
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field

from main_app.route.public.rate_limit import limit_tenant_lookup
from modules.auth.plane import is_valid_tenant_code
from modules.errors.catalog import text_for_code
from modules.errors.handlers import problem_from_text
from modules.errors.openapi import problem_responses
from modules.tenancy.providers import TenantRegistryDep
from modules.tenancy.registry import TenantStatus

router = APIRouter()

# 404 の文言。存在有無・削除済みの区別を含めない。
_NOT_FOUND_TEXT = text_for_code("not_found", 404)


class PublicTenantRead(BaseModel):
    """テナント存在確認の応答（最小限）。"""

    tenant_code: str = Field(description="テナントコード")
    # CP の TenantStatus(OpenAPI のスキーマ名)と衝突しないよう、列挙値は json_schema_extra で示す
    status: str = Field(description="ライフサイクル状態。ログインできるのは `ACTIVE` のみ", json_schema_extra={"enum": [status.value for status in TenantStatus]})


@router.get(
    "/{tenant_code}",
    summary="テナントの存在確認",
    responses=problem_responses(404, 429),
    dependencies=[Depends(limit_tenant_lookup)],
)
def get_public_tenant(tenant_code: Annotated[str, Path(description="テナントコード。形式不正も存在しない場合と同じ 404 にするため、長さはここで制限せず is_valid_tenant_code に任せる")], registry: TenantRegistryDep) -> PublicTenantRead:
    """テナントの存在と状態を返す（ログイン前に使える）。

    存在しない・削除済み・形式不正・予約語はいずれも同じ 404 を返し、区別できない。
    クライアントの IP 単位で簡易なレート制限があり、超過すると 429（`Retry-After` 付き）を返す。
    """
    record = registry.get_by_code(tenant_code) if is_valid_tenant_code(tenant_code) else None
    if record is None or record.status == TenantStatus.DELETED:
        raise problem_from_text(404, "tenant_not_found", _NOT_FOUND_TEXT)
    return PublicTenantRead(tenant_code=record.tenant_code, status=record.status)
