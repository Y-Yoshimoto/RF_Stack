#!/usr/bin/env python
# coding:utf-8
"""テナントコード（``tenant_code``）の形式と予約語。

仕様の正は ``docs/architecture/01-platform-concepts.md`` §5.1（形式）と §5.2（予約語）。
予約語の一覧はバックエンドの **この 1 箇所** を正とする（02 §5.4）。フロントは ``react_app/src/shared/tenant_code.ts``
に写しを持ち、無駄なリクエストを省くための事前判定にだけ使う。最終的な判定は常にこちら（公開のテナント存在確認 API は予約語も 404）。

本モジュールは FastAPI・DB に依存しない。

使用例::

    from modules.tenancy.tenant_code import validate_tenant_code

    tenant_code = validate_tenant_code(raw)  # 形式違反・予約語は InvalidTenantCodeFormatError

Note:
    形式の正規表現は ``control_plane_app.models.sql_models.TENANT_CODE_PATTERN``（DB の CHECK 制約）と
    ``modules.auth.plane.TENANT_CODE_PATTERN`` にも同じものがある。変更する場合は 3 箇所を揃えること。
"""
import re
from enum import StrEnum

# tenant_code の形式（01 §5.1）。3〜32 文字、英小文字・数字・ハイフン。先頭・末尾・連続のハイフンは不可。
# fullmatch で使う（"$" は末尾の改行 1 つを許してしまうため、アンカーには頼らない）。
TENANT_CODE_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){2,31}")

# 予約語（01 §5.2）。URL の第 1 セグメントがこれらの場合はテナントとして解釈せず、テナント作成時も拒否する。
# 追加する場合は、既存テナントと衝突しないことを確認すること（01 §5.2）。
# 形式上テナントコードになり得ない語（2 文字の "cp" 等）も、一覧の正として含めておく。
RESERVED_TENANT_CODES: frozenset[str] = frozenset({
    "cp", "api", "auth", "login", "logout", "callback", "dev-login", "link",
    "assets", "static", "public", "health", "admin", "keycloak",
    "www", "app", "docs", "help", "support", "status", "signup", "settings",
})


class TenantCodeViolation(StrEnum):
    """テナントコードが受け付けられない理由。"""

    # 01 §5.1 の形式に合わない（文字種・長さ・ハイフンの位置）
    FORMAT = "format"
    # 01 §5.2 の予約語
    RESERVED = "reserved"


class InvalidTenantCodeFormatError(ValueError):
    """テナントコードが形式違反、または予約語であることを表す例外。

    メッセージに入力値そのものは含めない（ログに外部入力をそのまま出さないため）。

    Attributes:
        violation: 受け付けられない理由。
    """

    def __init__(self, violation: TenantCodeViolation):
        """例外を初期化する。

        Args:
            violation: 受け付けられない理由。
        """
        self.violation = violation
        super().__init__(f"tenant_code is not acceptable ({violation.value})")


def is_reserved_tenant_code(tenant_code: str) -> bool:
    """予約語かどうかを返す（大文字小文字を区別しない）。

    Args:
        tenant_code: 判定対象。

    Returns:
        bool: 予約語なら ``True``。
    """
    return tenant_code.lower() in RESERVED_TENANT_CODES


def tenant_code_violation(tenant_code: object) -> TenantCodeViolation | None:
    """テナントコードとして受け付けられない理由を返す。

    形式（01 §5.1）を先に、予約語（01 §5.2）を後に判定する。

    Args:
        tenant_code: 判定対象（外部入力）。

    Returns:
        TenantCodeViolation | None: 受け付けられない理由。受け付けられる場合は ``None``。
    """
    if not isinstance(tenant_code, str) or TENANT_CODE_PATTERN.fullmatch(tenant_code) is None:
        return TenantCodeViolation.FORMAT
    if is_reserved_tenant_code(tenant_code):
        return TenantCodeViolation.RESERVED
    return None


def validate_tenant_code(tenant_code: object) -> str:
    """テナントコードを検証し、そのまま返す（正規化はしない。大文字は形式違反）。

    Args:
        tenant_code: 検証対象（外部入力）。

    Returns:
        str: 検証済みのテナントコード。

    Raises:
        InvalidTenantCodeFormatError: 形式違反、または予約語の場合。
    """
    violation = tenant_code_violation(tenant_code)
    if violation is not None:
        raise InvalidTenantCodeFormatError(violation)
    assert isinstance(tenant_code, str)
    return tenant_code
