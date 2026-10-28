# -*- coding: utf-8 -*-
"""TenantStatus の定義が CP(control_plane_app.models)と AP(modules.tenancy.registry)で一致することのテスト。

AP はレジストリのビュー ``v_tenant_registry`` の ``status`` を文字列で受け取って ACTIVE かどうかを判定する。
CP 側に状態を足したのに AP 側が追従しないと、状態の取り扱いが静かにずれるため、値の集合を突き合わせる。
"""
import uuid

import pytest
import pytest_check as check

from control_plane_app.models.sql_models import TenantStatus as CpTenantStatus
from control_plane_app.models.sql_models import TTenant
from control_plane_app.services.tenant_lifecycle import ALLOWED_TRANSITIONS, OPERATION_RULES
from modules.tenancy.registry import TenantRecord, is_active
from modules.tenancy.registry import TenantStatus as ApTenantStatus

# 01 §6.1 の状態一覧
SPEC_STATUSES = {"PROVISIONING", "ACTIVE", "FAILED", "SUSPENDED", "PENDING_DELETION", "DEPROVISIONING", "DELETED"}


def test_member_names_and_values_are_identical():
    """CP と AP の TenantStatus は、メンバー名と値の対応が完全に一致する。"""
    cp_members = {member.name: member.value for member in CpTenantStatus}
    ap_members = {member.name: member.value for member in ApTenantStatus}
    check.equal(cp_members, ap_members)


def test_values_match_the_spec():
    """両者の値は 01 §6.1 の状態一覧と一致する(名前と値が同一であること)。"""
    check.equal({member.value for member in CpTenantStatus}, SPEC_STATUSES)
    check.equal({member.value for member in ApTenantStatus}, SPEC_STATUSES)
    check.is_true(all(member.name == member.value for member in CpTenantStatus))


def test_ap_active_check_follows_the_cp_enum():
    """AP の ACTIVE 判定は、CP の列挙の ACTIVE だけを真とする。"""
    for status in CpTenantStatus:
        record = TenantRecord(tenant_id=uuid.uuid4(), tenant_code="abc", realm_name="tenant-abc", status=status.value)
        check.equal(is_active(record), status is CpTenantStatus.ACTIVE, f"status={status.value}")


def test_t_tenant_check_constraint_lists_all_statuses():
    """t_tenant.status の CHECK 制約は、列挙のすべての値を含み、それ以外を含まない。"""
    constraints = {c.name: str(c.sqltext) for c in TTenant.__table__.constraints if getattr(c, "sqltext", None) is not None}
    status_check = next(text for name, text in constraints.items() if name and "status" in name)
    values = {part.strip().strip("'") for part in status_check.split("(", 1)[1].rstrip(")").split(",")}
    check.equal(values, SPEC_STATUSES)


def test_lifecycle_table_covers_every_status():
    """状態遷移表(ALLOWED_TRANSITIONS)は全ての状態を遷移元として定義している(定義漏れで KeyError にならない)。"""
    check.equal(set(ALLOWED_TRANSITIONS), set(CpTenantStatus))
    for targets in ALLOWED_TRANSITIONS.values():
        check.is_true(targets <= set(CpTenantStatus))


@pytest.mark.parametrize("operation", list(OPERATION_RULES))
def test_operation_rules_use_known_statuses(operation):
    """操作ごとの遷移元・遷移先は、既知の状態だけで構成される。"""
    rule = OPERATION_RULES[operation]
    check.is_true(rule.sources <= set(CpTenantStatus))
    check.is_in(rule.target, set(CpTenantStatus))
