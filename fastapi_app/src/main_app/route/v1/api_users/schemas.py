#!/usr/bin/env python
# coding:utf-8
"""ユーザー管理 API(``/api/v1/users``)のリクエスト・レスポンスのスキーマ。

DB のテーブルモデル(``TUser``)はそのまま返さず、公開してよい項目だけを定義する。
IdP の利用者 ID(``idp_subject``)・``created_by`` / ``updated_by`` は返さない。日時は UTC(``Z``)の ISO 8601(03 §4)。
ロールは AP の DB に持たず IdP が正のため、一覧には含めず、詳細(``GET /users/{id}``)と作成の結果に含める。
"""
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from main_app.services.user_service import EMAIL_MAX_LENGTH, NAME_MAX_LENGTH, USERNAME_MAX_LENGTH
from modules.api_common.datetime_types import UtcDatetime
from modules.api_common.pagination import CursorPage

# テナント内で付与できるロール(01 §7.5)
AppRole = Literal["tenant_admin", "member"]


class UserRead(BaseModel):
    """テナント内のユーザー。`ETag` ヘッダーと `version` は同じ値。"""

    id: uuid.UUID = Field(description="ユーザー ID(UUIDv7)。`/api/v1/me` の `user.id`、組織のメンバー ID と同じ値")
    email: str | None = Field(description="メールアドレス(テナント内で一意)")
    display_name: str = Field(description="表示名(`\"{名} {姓}\"`)")
    is_active: bool = Field(description="有効か。無効化されたユーザーはログインできず、既存のセッションも次のリクエストで失効する")
    last_login_at: UtcDatetime | None = Field(description="最終ログイン日時(UTC)。一度もログインしていなければ `null`")
    version: int = Field(description="楽観ロック用のバージョン。更新系の `If-Match` に `\"<version>\"` で指定する")
    created_at: UtcDatetime = Field(description="作成日時(UTC)")
    updated_at: UtcDatetime = Field(description="更新日時(UTC)")


class UserDetail(UserRead):
    """ユーザーの詳細。IdP から取得したロールを含む。"""

    roles: list[AppRole] = Field(description="テナントのロール(`tenant_admin` / `member`)")


class UserPage(CursorPage[UserRead]):
    """ユーザー一覧(カーソル方式。ロールは含まない)。"""


class UserCreate(BaseModel):
    """ユーザー作成のリクエスト。"""

    email: str = Field(min_length=1, max_length=EMAIL_MAX_LENGTH, description="メールアドレス(テナント内で一意。重複は 409)")
    first_name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH, description="名")
    last_name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH, description="姓")
    roles: list[AppRole] = Field(default_factory=lambda: ["member"], min_length=1, description="付与するロール。省略時は `member`")
    username: str | None = Field(default=None, min_length=1, max_length=USERNAME_MAX_LENGTH, description="ログインに使うユーザー名(英数字と `. _ @ + -` の 3 文字以上)。省略時はメールアドレス")


class UserCredentials(BaseModel):
    """作成したユーザーのログイン情報。**一度だけ返す**。"""

    username: str = Field(description="ログインに使うユーザー名")
    temporary_password: str = Field(repr=False, description="一時パスワード。初回ログイン時に変更が必要。**このレスポンスでのみ返し、どこにも保存されない**(メールも送らない)")


class UserCreated(BaseModel):
    """ユーザー作成の結果。レスポンスは `Cache-Control: no-store`。"""

    user: UserDetail = Field(description="作成したユーザー")
    credentials: UserCredentials = Field(description="ログイン情報(一時パスワードを含む)")


class UserUpdate(BaseModel):
    """ユーザー更新のリクエスト(`PATCH`。送った項目だけを更新する。03 §1)。

    いずれの項目も `null` は指定できない(422)。姓・名は両方を指定する。
    """

    first_name: str | SkipJsonSchema[None] = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH, description="名。`last_name` と一緒に指定する")
    last_name: str | SkipJsonSchema[None] = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH, description="姓。`first_name` と一緒に指定する")
    roles: Annotated[list[AppRole], Field(min_length=1)] | SkipJsonSchema[None] = Field(default=None, description="直接付与するロールの集合(置き換え)。自分自身の `tenant_admin` は外せない(409)")
    is_active: bool | SkipJsonSchema[None] = Field(default=None, description="`false` で無効化、`true` で再有効化。自分自身は無効化できない(409)")

    @field_validator("first_name", "last_name", "roles", "is_active", mode="before")
    @classmethod
    def _reject_explicit_null(cls, value: object) -> object:
        """送られた項目が `null` の場合は拒否する(未指定とは区別する。省略時の既定値はこの検証を通らない)。"""
        if value is None:
            raise ValueError("null は指定できません")
        return value
