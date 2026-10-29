#!/usr/bin/env python
# coding:utf-8
"""組織管理 API(``/api/v1/organizations``)のリクエスト・レスポンスのスキーマ。

DB のテーブルモデル(``TOrganization``)はそのまま返さず、公開してよい項目だけを定義する。日時は UTC(``Z``)の ISO 8601(03 §4)。
メンバーは一覧には含めず、詳細(``GET /organizations/{id}``)とメンバー置き換えの結果にユーザー ID で含める。
"""
import uuid

from pydantic import BaseModel, Field

from main_app.services.organization_service import MAX_ORGANIZATION_MEMBERS, ORGANIZATION_NAME_MAX_LENGTH
from modules.api_common.datetime_types import UtcDatetime
from modules.api_common.pagination import CursorPage


class OrganizationRead(BaseModel):
    """組織。`ETag` ヘッダーと `version` は同じ値。"""

    id: uuid.UUID = Field(description="組織 ID(UUIDv7)")
    name: str = Field(description="組織名(有効な組織の中で一意。大文字小文字を区別しない)")
    version: int = Field(description="楽観ロック用のバージョン。更新系の `If-Match` に `\"<version>\"` で指定する")
    created_at: UtcDatetime = Field(description="作成日時(UTC)")
    updated_at: UtcDatetime = Field(description="更新日時(UTC)")


class OrganizationDetail(OrganizationRead):
    """組織の詳細。メンバーのユーザー ID を含む。"""

    member_ids: list[uuid.UUID] = Field(description="メンバーのユーザー ID(ID 順)。ユーザーの情報は `GET /api/v1/users` で取得する")


class OrganizationPage(CursorPage[OrganizationRead]):
    """組織一覧(カーソル方式。メンバーは含まない)。"""


class OrganizationCreate(BaseModel):
    """組織作成のリクエスト。"""

    name: str = Field(min_length=1, max_length=ORGANIZATION_NAME_MAX_LENGTH, description="組織名(有効な組織の中で一意。重複は 409)")


class OrganizationUpdate(BaseModel):
    """組織更新のリクエスト。"""

    name: str = Field(min_length=1, max_length=ORGANIZATION_NAME_MAX_LENGTH, description="組織名(有効な別の組織と重複すると 409)")


class OrganizationMembersReplace(BaseModel):
    """組織のメンバー置き換えのリクエスト(全置換。03 §1)。"""

    user_ids: list[uuid.UUID] = Field(max_length=MAX_ORGANIZATION_MEMBERS, description=f"メンバーにするユーザー ID の全件(重複は除く。最大 {MAX_ORGANIZATION_MEMBERS} 件。空配列で全員を外す)。テナント内に存在しないユーザーが含まれると 422")
