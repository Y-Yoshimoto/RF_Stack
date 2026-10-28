# -*- coding: utf-8 -*-
"""control_plane_app.services.tenant_lifecycle(状態遷移表。01 §6.1)のテスト。DB・Keycloak は不要。"""
import datetime as dt

import pytest
import pytest_check as check

from control_plane_app.models.sql_models import TenantStatus
from control_plane_app.services.tenant_lifecycle import (
    ALLOWED_TRANSITIONS,
    DELETION_GRACE_PERIOD,
    OPERATION_RULES,
    STALE_PROVISIONING_THRESHOLD,
    TenantOperation,
    available_operations,
    can_transition,
    is_operation_allowed,
)

S = TenantStatus
ALL_STATUSES = [s.value for s in TenantStatus]

# 01 §6.1 の状態遷移図を、実装とは別にそのまま書き下したもの(遷移元 → 遷移先)
SPEC_TRANSITIONS = {
    "PROVISIONING": {"ACTIVE", "FAILED"},
    "FAILED": {"PROVISIONING", "PENDING_DELETION"},
    "ACTIVE": {"SUSPENDED", "PENDING_DELETION"},
    "SUSPENDED": {"ACTIVE", "PENDING_DELETION"},
    "PENDING_DELETION": {"DEPROVISIONING"},
    "DEPROVISIONING": {"DEPROVISIONING", "DELETED"},
    "DELETED": set(),
}

# 操作ごとに実行できる状態(01 §6.1 と CP-OPS-03..08 から)
SPEC_OPERATION_SOURCES = {
    TenantOperation.RETRY: {"FAILED", "PROVISIONING"},
    TenantOperation.SUSPEND: {"ACTIVE"},
    TenantOperation.RESUME: {"SUSPENDED"},
    TenantOperation.REQUEST_DELETION: {"ACTIVE", "SUSPENDED", "FAILED"},
    TenantOperation.DEPROVISION: {"PENDING_DELETION", "DEPROVISIONING"},
    TenantOperation.REAP: {"PROVISIONING"},
}


def test_constants():
    """猶予期間は 30 日、PROVISIONING の中断判定は 10 分(01 CP-OPS-07 / CP-ONB-09)。"""
    check.equal(DELETION_GRACE_PERIOD, dt.timedelta(days=30))
    check.equal(STALE_PROVISIONING_THRESHOLD, dt.timedelta(minutes=10))


@pytest.mark.parametrize(("source", "target"), [(s, t) for s in ALL_STATUSES for t in ALL_STATUSES])
def test_transition_table_matches_spec(source, target):
    """全ての (遷移元, 遷移先) の組で、can_transition は仕様の遷移図と一致する(図にある遷移だけ許可)。"""
    check.equal(can_transition(source, TenantStatus(target)), target in SPEC_TRANSITIONS[source], f"{source} -> {target}")


def test_deleted_is_terminal():
    """DELETED からはどこへも遷移できない。"""
    check.equal(ALLOWED_TRANSITIONS[S.DELETED], frozenset())


@pytest.mark.parametrize("current", ["", "active", "UNKNOWN", "Active", "DELETED ", None])
def test_unknown_status_is_never_allowed(current):
    """未知の状態(大文字小文字違い・空・None を含む)からは、どの遷移も操作も許可しない。"""
    check.is_false(any(can_transition(current, target) for target in TenantStatus))
    check.is_false(any(is_operation_allowed(operation, current) for operation in TenantOperation))
    check.equal(available_operations(current), [])


@pytest.mark.parametrize("operation", list(TenantOperation))
@pytest.mark.parametrize("status", ALL_STATUSES)
def test_operation_sources_match_spec(operation, status):
    """各操作を実行できる状態は仕様どおり(それ以外では拒否)。"""
    check.equal(is_operation_allowed(operation, status), status in SPEC_OPERATION_SOURCES[operation], f"{operation} @ {status}")


@pytest.mark.parametrize("operation", list(TenantOperation))
def test_operation_rules_agree_with_the_transition_table(operation):
    """操作の遷移先は、遷移表で許された遷移(retry は PROVISIONING のままの再実行を含む特例)である。"""
    rule = OPERATION_RULES[operation]
    for source in rule.sources:
        if operation == TenantOperation.RETRY and source == S.PROVISIONING:
            continue  # 中断した PROVISIONING の再実行(状態は PROVISIONING のまま)は遷移表にない特例
        check.is_true(can_transition(source.value, rule.target), f"{operation}: {source} -> {rule.target}")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("PROVISIONING", ["retry"]),
        ("ACTIVE", ["suspend", "request_deletion"]),
        ("FAILED", ["retry", "request_deletion"]),
        ("SUSPENDED", ["resume", "request_deletion"]),
        ("PENDING_DELETION", []),
        ("DEPROVISIONING", []),
        ("DELETED", []),
    ],
)
def test_available_operations_for_ui(status, expected):
    """画面に出す操作の一覧は、定期ジョブの操作(deprovision / reap)を含まない。"""
    check.equal([operation.value for operation in available_operations(status)], expected)
