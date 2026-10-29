#!/usr/bin/env python
# coding:utf-8
"""テナントのライフサイクル（状態遷移）の定義（01 §6.1）。DB・Keycloak・FastAPI に依存しない。

```
[*] --> PROVISIONING
PROVISIONING --> ACTIVE / FAILED
FAILED --> PROVISIONING（再実行） / PENDING_DELETION（削除要求）
ACTIVE --> SUSPENDED（停止） / PENDING_DELETION（削除要求）
SUSPENDED --> ACTIVE（再開） / PENDING_DELETION（削除要求）
PENDING_DELETION --> DEPROVISIONING（猶予期間経過。定期ジョブ）
DEPROVISIONING --> DEPROVISIONING（失敗時は次回ジョブで再試行） / DELETED
```

操作（:class:`TenantOperation`）ごとに、実行できる現在の状態と遷移先を :data:`OPERATION_RULES` に定める。
許されない操作はサービス層が :class:`~control_plane_app.services.errors.InvalidTenantTransitionError` にする。

01 の図に無い扱い:
    ``retry`` は ``PROVISIONING`` のまま中断したテナント（実行中の処理が無い = テナントのロックが取れるもの）
    にも許可し、状態は ``PROVISIONING`` のまま払い出しをやり直す。定期ジョブ（``provisioning_reaper``）が
    ``FAILED`` にするのを待たずに再実行できるようにするため。
"""
import datetime as dt
from dataclasses import dataclass
from enum import StrEnum

from control_plane_app.models.sql_models import TenantStatus

# 削除要求から物理削除までの猶予期間（01 CP-OPS-07）
DELETION_GRACE_PERIOD = dt.timedelta(days=30)

# これより長く PROVISIONING のままの払い出しは中断したとみなす（01 CP-ONB-09）
STALE_PROVISIONING_THRESHOLD = dt.timedelta(minutes=10)

# 01 §6.1 の状態遷移（遷移元 → 遷移先の集合）
ALLOWED_TRANSITIONS: dict[TenantStatus, frozenset[TenantStatus]] = {
    TenantStatus.PROVISIONING: frozenset({TenantStatus.ACTIVE, TenantStatus.FAILED}),
    TenantStatus.FAILED: frozenset({TenantStatus.PROVISIONING, TenantStatus.PENDING_DELETION}),
    TenantStatus.ACTIVE: frozenset({TenantStatus.SUSPENDED, TenantStatus.PENDING_DELETION}),
    TenantStatus.SUSPENDED: frozenset({TenantStatus.ACTIVE, TenantStatus.PENDING_DELETION}),
    TenantStatus.PENDING_DELETION: frozenset({TenantStatus.DEPROVISIONING}),
    TenantStatus.DEPROVISIONING: frozenset({TenantStatus.DEPROVISIONING, TenantStatus.DELETED}),
    TenantStatus.DELETED: frozenset(),
}


class TenantOperation(StrEnum):
    """テナントに対する操作（サービスの公開メソッドに対応）。"""

    RETRY = "retry"
    SUSPEND = "suspend"
    RESUME = "resume"
    REQUEST_DELETION = "request_deletion"
    DEPROVISION = "deprovision"
    # 中断した払い出しの回収（定期ジョブ）
    REAP = "reap"


@dataclass(frozen=True, kw_only=True)
class OperationRule:
    """操作を実行できる現在の状態と遷移先。

    Attributes:
        sources: 操作を実行できる現在の状態。
        target: 操作後の状態（操作の途中で別の状態を経由する場合は最初の遷移先）。
    """

    sources: frozenset[TenantStatus]
    target: TenantStatus


OPERATION_RULES: dict[TenantOperation, OperationRule] = {
    TenantOperation.RETRY: OperationRule(sources=frozenset({TenantStatus.FAILED, TenantStatus.PROVISIONING}), target=TenantStatus.PROVISIONING),
    TenantOperation.SUSPEND: OperationRule(sources=frozenset({TenantStatus.ACTIVE}), target=TenantStatus.SUSPENDED),
    TenantOperation.RESUME: OperationRule(sources=frozenset({TenantStatus.SUSPENDED}), target=TenantStatus.ACTIVE),
    TenantOperation.REQUEST_DELETION: OperationRule(
        sources=frozenset({TenantStatus.ACTIVE, TenantStatus.SUSPENDED, TenantStatus.FAILED}), target=TenantStatus.PENDING_DELETION),
    TenantOperation.DEPROVISION: OperationRule(sources=frozenset({TenantStatus.PENDING_DELETION, TenantStatus.DEPROVISIONING}), target=TenantStatus.DEPROVISIONING),
    TenantOperation.REAP: OperationRule(sources=frozenset({TenantStatus.PROVISIONING}), target=TenantStatus.FAILED),
}


def can_transition(current: str, target: TenantStatus) -> bool:
    """01 §6.1 の状態遷移として許されるかを返す（同じ状態のままの再実行は ``retry`` の特例のみ）。

    Args:
        current: 現在の状態（未知の値は不可）。
        target: 遷移先。

    Returns:
        bool: 許されるなら ``True``。
    """
    try:
        status = TenantStatus(current)
    except ValueError:
        return False
    return target in ALLOWED_TRANSITIONS[status]


def is_operation_allowed(operation: TenantOperation, current: str) -> bool:
    """現在の状態で操作を実行できるかを返す。

    Args:
        operation: 操作。
        current: 現在の状態（未知の値は不可）。

    Returns:
        bool: 実行できるなら ``True``。
    """
    try:
        status = TenantStatus(current)
    except ValueError:
        return False
    return status in OPERATION_RULES[operation].sources


def available_operations(current: str) -> list[TenantOperation]:
    """現在の状態で実行できる操作の一覧を返す（画面でボタンを出し分ける等に使う）。

    ``deprovision`` / ``reap`` は定期ジョブの操作のため含めない。

    Args:
        current: 現在の状態。

    Returns:
        list[TenantOperation]: 実行できる操作。
    """
    user_operations = (TenantOperation.RETRY, TenantOperation.SUSPEND, TenantOperation.RESUME, TenantOperation.REQUEST_DELETION)
    return [operation for operation in user_operations if is_operation_allowed(operation, current)]
