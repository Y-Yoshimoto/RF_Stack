# -*- coding: utf-8 -*-
"""modules.auth.plane(プレーンの定義・ロールの許可リスト・テナントコード形式)のテスト。"""
import re

import pytest
import pytest_check as check

from control_plane_app.models.sql_models import TENANT_CODE_PATTERN as SQL_TENANT_CODE_PATTERN
from modules.auth import dependency, plane
from modules.auth.plane import (
    APP_ROLES,
    CP_REALM_NAME,
    CP_ROLES,
    PLANE_ROLES,
    SESSION_COOKIE_NAMES,
    TENANT_REALM_PREFIX,
    Plane,
    filter_roles,
    is_valid_tenant_code,
    tenant_code_from_realm,
)
from modules.keycloak_admin import templates
from modules.tenancy import tenant_code

# 形式の判定が 4 箇所(plane / tenant_code / keycloak_admin.templates / DB の CHECK 制約)で一致することを確認する入力
CORPUS = [
    "abc", "ab", "a", "", "a" * 32, "a" * 33, "a-b", "-ab", "ab-", "a--b", "ABC", "ab_c", "ab.c", "ab c", "日本語", "ａｂｃ", "0a0", "a-b-c", "a" + "-b" * 15 + "c", "dev-login", "tenant-x",
]


class TestPlaneDefinitions:
    """プレーン・Cookie 名・ロール。"""

    def test_plane_values(self):
        """プレーンの値は URL(/api/auth/{plane}/...)とセッションの plane に使う app / cp。"""
        check.equal({p.value for p in Plane}, {"app", "cp"})

    def test_cookie_names_are_distinct_per_plane(self):
        """Cookie 名はプレーンごとに別で、依存関数が読む Cookie(APIKeyCookie の名前)と一致する。"""
        check.equal(SESSION_COOKIE_NAMES, {Plane.APP: "rf_sid_app", Plane.CP: "rf_sid_cp"})
        check.equal(len(set(SESSION_COOKIE_NAMES.values())), 2)
        check.equal(dependency.app_session_cookie.model.name, SESSION_COOKIE_NAMES[Plane.APP])
        check.equal(dependency.cp_session_cookie.model.name, SESSION_COOKIE_NAMES[Plane.CP])
        check.is_false(dependency.app_session_cookie.auto_error, "Cookie が無い場合の 401 は load_session が決める")
        check.is_false(dependency.cp_session_cookie.auto_error)

    def test_role_allow_lists_are_disjoint(self):
        """AP のロールと CP のロールは重ならない(プレーンをまたいで通用するロールを作らない)。"""
        check.equal(APP_ROLES, {"tenant_admin", "member"})
        check.equal(CP_ROLES, {"saas_admin", "saas_viewer"})
        check.equal(APP_ROLES & CP_ROLES, frozenset())
        check.equal(PLANE_ROLES, {Plane.APP: APP_ROLES, Plane.CP: CP_ROLES})

    def test_realm_naming(self):
        """CP のレルム名は固定、テナントレルムの接頭辞は tenant-。keycloak_admin 側の定数と一致する。"""
        check.equal(CP_REALM_NAME, "control-plane")
        check.equal(TENANT_REALM_PREFIX, "tenant-")
        check.equal(templates.CONTROL_PLANE_REALM_NAME, CP_REALM_NAME)
        check.equal(templates.TENANT_REALM_PREFIX, TENANT_REALM_PREFIX)
        check.equal(templates.TENANT_ROLES, ("tenant_admin", "member"))
        check.equal(set(templates.TENANT_ROLES), set(APP_ROLES))
        check.equal(set(templates.CP_ROLES), set(CP_ROLES))


class TestFilterRoles:
    """filter_roles: プレーンで扱うロールだけを取り出す。"""

    def test_keeps_only_plane_roles_sorted_and_unique(self):
        """既定ロール・テーマ固有のロールは落とし、許可リストのロールだけを重複なし・名前順で返す。"""
        roles = ["offline_access", "uma_authorization", "default-roles-tenant-alpha", "member", "tenant_admin", "member", "todo_editor"]
        check.equal(filter_roles(Plane.APP, roles), ["member", "tenant_admin"])

    def test_other_plane_roles_are_dropped(self):
        """AP のトークンに CP のロール名があっても、AP のセッションには載らない(逆も同じ)。"""
        check.equal(filter_roles(Plane.APP, ["saas_admin", "saas_viewer", "member"]), ["member"])
        check.equal(filter_roles(Plane.CP, ["tenant_admin", "member", "saas_viewer"]), ["saas_viewer"])

    @pytest.mark.parametrize("roles", [None, "member", {"member": 1}, 5, ("member",)])
    def test_non_list_is_empty(self, roles):
        """リスト以外(None・文字列・タプルなど)は空として扱う。"""
        check.equal(filter_roles(Plane.APP, roles), [])

    def test_non_string_items_are_ignored(self):
        """リストの中の文字列以外は無視する。"""
        check.equal(filter_roles(Plane.APP, [None, 1, ["member"], "member"]), ["member"])


class TestTenantCodeHelpers:
    """tenant_code の形式判定とレルム名からの取り出し。"""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("abc", True), ("a-b", True), ("a" * 32, True), ("ab", False), ("a" * 33, False), ("a--b", False), ("abc\n", False), ("ABC", False), (None, False), ("", False)],
    )
    def test_is_valid_tenant_code(self, value, expected):
        """形式判定は末尾の改行・大文字・None を受け付けない。"""
        check.equal(is_valid_tenant_code(value), expected)

    @pytest.mark.parametrize(
        ("realm", "expected"),
        [("tenant-alpha", "alpha"), ("tenant-a-b", "a-b"), ("tenant-", None), ("master", None), ("control-plane", None), ("Tenant-alpha", None), ("", None)],
    )
    def test_tenant_code_from_realm(self, realm, expected):
        """接頭辞 tenant- を外した値を返す。接頭辞が無い・空になる場合は None。"""
        check.equal(tenant_code_from_realm(realm), expected)

    @pytest.mark.parametrize("value", CORPUS)
    def test_all_four_definitions_agree(self, value):
        """形式の定義(plane・tenant_code・keycloak_admin.templates・DB の CHECK 制約)は、同じ入力に同じ判定をする。"""
        expected = tenant_code.TENANT_CODE_PATTERN.fullmatch(value) is not None
        check.equal(plane.TENANT_CODE_PATTERN.fullmatch(value) is not None, expected, "modules.auth.plane")
        check.equal(templates.TENANT_CODE_PATTERN.fullmatch(value) is not None, expected, "keycloak_admin.templates")
        # DB の CHECK 制約は PostgreSQL の正規表現(^...$)。Python の re でも同じ式として評価できる
        check.equal(re.search(SQL_TENANT_CODE_PATTERN, value) is not None, expected, "t_tenant の CHECK 制約")
