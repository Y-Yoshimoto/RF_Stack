#!/usr/bin/env python
# coding:utf-8
"""``GET /api/v1/me`` のレスポンスのスキーマ。"""
import uuid

from pydantic import BaseModel, Field


class MeTenant(BaseModel):
    """ログイン中のテナント。"""

    id: uuid.UUID = Field(description="テナント ID（UUIDv7）")
    tenant_code: str = Field(description="テナントコード（URL に使う識別子）")


class MeUser(BaseModel):
    """ログイン中のユーザー。"""

    id: uuid.UUID = Field(description="ユーザー ID（AP のユーザー ID。`GET /api/v1/users` の `id`、組織のメンバー ID と同じ値。認証基盤の `sub` ではない）")
    username: str | None = Field(description="ユーザー名")
    email: str | None = Field(description="メールアドレス")
    roles: list[str] = Field(description="テナント内のロール（`tenant_admin` / `member`）")


class MeOrganization(BaseModel):
    """ログイン中のユーザーが所属する組織。"""

    id: uuid.UUID = Field(description="組織 ID(UUIDv7。`GET /api/v1/organizations` の `id` と同じ値)")
    name: str = Field(description="組織名")


class MeRead(BaseModel):
    """ログイン中のテナントとユーザー。"""

    tenant: MeTenant = Field(description="テナント")
    user: MeUser = Field(description="ユーザー")
    organizations: list[MeOrganization] = Field(description="ユーザーが所属する有効な組織(論理削除済みを除く。組織名順。所属が無ければ空配列)")
