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

    id: str = Field(description="ユーザーの識別子（認証基盤の `sub`）")
    username: str | None = Field(description="ユーザー名")
    email: str | None = Field(description="メールアドレス")
    roles: list[str] = Field(description="テナント内のロール（`tenant_admin` / `member`）")


class MeRead(BaseModel):
    """ログイン中のテナントとユーザー。"""

    tenant: MeTenant = Field(description="テナント")
    user: MeUser = Field(description="ユーザー")
