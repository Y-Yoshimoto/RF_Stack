#!/usr/bin/env python
# coding:utf-8
"""認証済みユーザー情報からテナントコンテキストを導出するモジュール（フレームワーク非依存）。

テナントは **認証済みセッション（BFF の Redis セッション）に保持されたユーザー情報からのみ**
決定する。リクエストボディやクエリの ``tenant_id`` は信用しない。

判定ルール（:class:`RegistryTenantResolver`）:
    1. ユーザー情報の ``realm`` と ``tenant_id``（Keycloak のカスタムクレーム）を取り出す。
    2. レジストリでレルムを検索する。未登録なら拒否。
    3. レジストリ上のテナント ID とクレームの ``tenant_id`` が一致しなければ拒否。
    4. テナントが ACTIVE でなければ拒否（停止中など）。
    5. 以上を満たせば :class:`~modules.tenancy.context.TenantContext` を返す。

拒否は :class:`TenantResolutionError` で表し、HTTP ステータスへの変換は
:mod:`modules.tenancy.dependency` が行う。
"""
import uuid
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any

from .context import TenantContext
from .registry import TenantRegistry, is_active

# 認証済みユーザー情報 → テナントコンテキストの変換関数の型。
# 拒否する場合は TenantResolutionError を送出する。
type TenantResolver = Callable[[Mapping[str, Any]], TenantContext]


class TenantErrorCode(StrEnum):
    """テナント解決の失敗理由。HTTP レスポンスの ``detail`` にそのまま使う短いコード。"""

    # ユーザー情報に realm / tenant_id が無い
    CLAIM_MISSING = "tenant_claim_missing"
    # tenant_id が UUID として解釈できない
    CLAIM_INVALID = "tenant_claim_invalid"
    # レルムがレジストリに登録されていない
    NOT_FOUND = "tenant_not_found"
    # レルムとクレームの tenant_id が一致しない
    MISMATCH = "tenant_mismatch"
    # テナントが ACTIVE でない（停止中・削除要求中など）
    INACTIVE = "tenant_inactive"


class TenantResolutionError(Exception):
    """テナントコンテキストを導出できない（アクセスを拒否すべき）場合の例外。

    Attributes:
        code: 失敗理由のコード。
    """

    def __init__(self, code: TenantErrorCode) -> None:
        """失敗理由のコードを保持する。

        Args:
            code: 失敗理由のコード。
        """
        super().__init__(code.value)
        self.code = code


def _parse_uuid(value: Any) -> uuid.UUID | None:
    """値を UUID に変換する。変換できなければ ``None`` を返す。

    Args:
        value: 変換対象（``uuid.UUID`` または文字列を想定）。

    Returns:
        uuid.UUID | None: 変換結果。
    """
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


class RegistryTenantResolver:
    """テナントレジストリと突き合わせてテナントコンテキストを導出するリゾルバ。

    :data:`TenantResolver` として呼び出せる。レジストリには通常
    :class:`~modules.tenancy.registry.CachedTenantRegistry` を渡す。

    想定するユーザー情報（``modules.auth.get_current_user`` の戻り値）::

        {"sub": "<Keycloak の sub>", "realm": "tenant-acme", "tenant_id": "<UUID>", ...}

    Args:
        registry: テナントレジストリ。
        realm_key: ユーザー情報のレルム名のキー。
        tenant_id_key: ユーザー情報のテナント ID（カスタムクレーム）のキー。
        user_id_key: ユーザー情報の認証主体 ID のキー。
    """

    def __init__(self, registry: TenantRegistry, realm_key: str = "realm", tenant_id_key: str = "tenant_id", user_id_key: str = "sub") -> None:
        """レジストリとキー名を保持する。"""
        self._registry = registry
        self._realm_key = realm_key
        self._tenant_id_key = tenant_id_key
        self._user_id_key = user_id_key

    def __call__(self, user: Mapping[str, Any]) -> TenantContext:
        """ユーザー情報からテナントコンテキストを導出する。

        Args:
            user: 認証済みユーザー情報。

        Returns:
            TenantContext: ``plane="app"`` のテナントコンテキスト。

        Raises:
            TenantResolutionError: 判定ルールのいずれかを満たさない場合。
        """
        realm = user.get(self._realm_key)
        raw_tenant_id = user.get(self._tenant_id_key)
        if not isinstance(realm, str) or not realm or raw_tenant_id in (None, ""):
            raise TenantResolutionError(TenantErrorCode.CLAIM_MISSING)

        claimed_tenant_id = _parse_uuid(raw_tenant_id)
        if claimed_tenant_id is None:
            raise TenantResolutionError(TenantErrorCode.CLAIM_INVALID)

        record = self._registry.get_by_realm(realm)
        if record is None:
            raise TenantResolutionError(TenantErrorCode.NOT_FOUND)
        # 状態より先に一致を確認し、他テナントのセッションに状態を漏らさない
        if record.tenant_id != claimed_tenant_id:
            raise TenantResolutionError(TenantErrorCode.MISMATCH)
        if not is_active(record):
            raise TenantResolutionError(TenantErrorCode.INACTIVE)

        return TenantContext(tenant_id=record.tenant_id, tenant_code=record.tenant_code, user_id=_parse_uuid(user.get(self._user_id_key)), plane="app")
