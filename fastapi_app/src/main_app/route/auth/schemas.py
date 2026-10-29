#!/usr/bin/env python
# coding:utf-8
"""``/api/auth`` (BFF) のうち OpenAPI に載せるエンドポイントのレスポンスのスキーマ。

認証領域 (レルム) 名・クライアント ID・``tenant_id`` はフロントに返さない (01 §10.2)。
"""
from typing import Literal

from pydantic import BaseModel, Field


class AuthUser(BaseModel):
    """ログイン中のユーザー (セッションの ``user`` のうちフロントに返す項目)。"""

    sub: str = Field(description="ユーザーの識別子(認証基盤の `sub`)")
    preferred_username: str | None = Field(description="ユーザー名")
    email: str | None = Field(description="メールアドレス")
    roles: list[str] = Field(description="プレーンのロール。AP は `tenant_admin` / `member`、CP は `saas_admin` / `saas_viewer`")


class AppAuthStatus(BaseModel):
    """AP セッションの状態。"""

    authenticated: Literal[True] = Field(description="常に `true`(未認証は 401)")
    plane: Literal["app"] = Field(description="プレーン")
    tenant_code: str = Field(description="ログイン中のテナントコード。ルートガードで URL のテナントコードと照合する")
    user: AuthUser = Field(description="ユーザー")


class CpAuthStatus(BaseModel):
    """CP セッションの状態。"""

    authenticated: Literal[True] = Field(description="常に `true`(未認証は 401)")
    plane: Literal["cp"] = Field(description="プレーン")
    user: AuthUser = Field(description="ユーザー")


class LogoutResult(BaseModel):
    """ログアウトの結果。"""

    logout_url: str = Field(
        description=(
            "ブラウザをトップレベル遷移させる URL。認証基盤の RP-Initiated Logout の URL で、完了後に"
            " AP は `/{tenant_code}/login`、CP は `/cp/login` へ戻る。セッションが無かった場合はそのログイン画面"
            "(AP でテナントが分からなければ `/`)の URL"
        )
    )
