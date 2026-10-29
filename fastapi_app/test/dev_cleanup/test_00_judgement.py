# -*- coding: utf-8 -*-
"""dev_tools.e2e_cleanup の対象判定(DB・Keycloak に依存しない純粋関数)のテスト。

E2E の命名(``react_app/playwright-test`` の ``uniqueSuffix()`` = 小文字英数字 8 桁)に完全一致するものだけが対象で、
シードのテナント・ユーザー・デフォルト組織は、パターンに一致しても絶対に対象にならないことを確認する。
"""
import datetime as dt

import pytest
import pytest_check as check

from control_plane_app.models.sql_models import TenantStatus
from control_plane_app.services.tenant_lifecycle import STALE_PROVISIONING_THRESHOLD
from dev_tools import e2e_cleanup
from dev_tools.e2e_cleanup import (
    PROTECTED_ORGANIZATION_NAMES,
    PROTECTED_TENANT_CODES,
    PROTECTED_USER_EMAILS,
    PROTECTED_USERNAMES,
    TenantCleanupAction,
    is_e2e_organization_name,
    is_e2e_tenant_code,
    is_e2e_todo_title,
    is_e2e_user,
    plan_tenant_action,
)
from main_app.services.user_sync import DEFAULT_ORGANIZATION_NAME
from modules.auth.dev_profiles import DEV_TENANTS, DEV_USERS


class TestTenantCode:
    """is_e2e_tenant_code: ``e2e-`` + 小文字英数字 8 桁に完全一致するものだけ。"""

    @pytest.mark.parametrize("code", ["e2e-abcd1234", "e2e-00000000", "e2e-zzzzzzzz", "e2e-a1b2c3d4"])
    def test_matches_e2e_names(self, code):
        """E2E の命名(接尾辞が小文字英数字 8 桁)は対象。"""
        check.is_true(is_e2e_tenant_code(code))

    @pytest.mark.parametrize(
        "code",
        [
            None, "", " ", "alpha", "beta", "e2e-", "e2e-abcd123", "e2e-abcd12345", "E2E-abcd1234", "e2e-ABCD1234", "e2e-abcd_234", "e2e-abcd-234",
            "e2e-abcd1234\n", " e2e-abcd1234", "e2e-abcd1234 ", "xe2e-abcd1234", "e2e-abcd1234-x", "e2e-abcd1234e2e-abcd1234", "zt-abcdef1234", "e2e_abcd1234",
            "e2e-あいうえおかきく", "e2e-ａｂｃｄ１２３４", "tenant-e2e-abcd1234",
        ],
    )
    def test_rejects_near_misses(self, code):
        """桁数・大文字・前後の余分な文字・改行・全角・別の接頭辞は対象外(境界の一致は完全一致のみ)。"""
        check.is_false(is_e2e_tenant_code(code))

    @pytest.mark.parametrize("code", sorted(PROTECTED_TENANT_CODES))
    def test_seed_tenants_are_never_targets(self, code):
        """シードのテナント(alpha / beta)は対象にならない。"""
        check.is_false(is_e2e_tenant_code(code))

    def test_protected_codes_are_the_seed_tenants(self):
        """保護対象のテナントコードは DEV_TENANTS(alpha / beta)そのもの。"""
        check.equal(PROTECTED_TENANT_CODES, frozenset(tenant.tenant_code for tenant in DEV_TENANTS))
        check.equal(PROTECTED_TENANT_CODES, frozenset({"alpha", "beta"}))

    def test_protection_wins_over_the_pattern(self, monkeypatch):
        """保護対象は、命名パターンに一致していても対象にならない(除外がパターン判定より先)。"""
        monkeypatch.setattr(e2e_cleanup, "PROTECTED_TENANT_CODES", frozenset({"e2e-abcd1234"}))
        check.is_false(is_e2e_tenant_code("e2e-abcd1234"))
        check.is_true(is_e2e_tenant_code("e2e-abcd1235"))


class TestUser:
    """is_e2e_user: ``e2e-<8桁>@example.com``(大文字小文字・前後の空白は無視)。シードのユーザーは対象外。"""

    @pytest.mark.parametrize("email", ["e2e-abcd1234@example.com", "E2E-ABCD1234@EXAMPLE.COM", "  e2e-abcd1234@example.com  ", "e2e-00000000@example.com"])
    def test_matches_e2e_names(self, email):
        """E2E の命名のメールアドレスは対象(大文字小文字を区別せず、前後の空白は除く)。"""
        check.is_true(is_e2e_user(email))

    @pytest.mark.parametrize(
        "email",
        [
            None, "", "   ", "e2e-@example.com", "e2e-abcd123@example.com", "e2e-abcd12345@example.com", "e2e-abcd1234@example.org", "e2e-abcd1234@examplexcom",
            "e2e-abcd1234@example.com.evil", "e2e-abcd1234@sub.example.com", "x-e2e-abcd1234@example.com", "e2e-abcd1234", "e2e-abcd_234@example.com",
            "e2e-abcd1234+x@example.com", "alice@example.com",
        ],
    )
    def test_rejects_near_misses(self, email):
        """桁数・ドメイン・接頭辞・サブアドレスが違うものは対象外。"""
        check.is_false(is_e2e_user(email))

    @pytest.mark.parametrize("user", DEV_USERS, ids=lambda user: user.username)
    def test_seed_users_are_never_targets(self, user):
        """シードのユーザー(CP・alpha・beta の全員)は、メールアドレスだけでもユーザー名を添えても対象にならない。"""
        check.is_false(is_e2e_user(user.email))
        check.is_false(is_e2e_user(user.email.upper()))
        check.is_false(is_e2e_user(user.email, user.username))

    @pytest.mark.parametrize("username", sorted(PROTECTED_USERNAMES))
    def test_protected_username_wins_over_email_pattern(self, username):
        """メールアドレスが E2E の命名でも、ユーザー名がシードのユーザーなら対象にならない(Keycloak のユーザー検索での誤削除の防止)。"""
        check.is_false(is_e2e_user("e2e-abcd1234@example.com", username))
        check.is_false(is_e2e_user("e2e-abcd1234@example.com", f"  {username.upper()} "))

    @pytest.mark.parametrize("username", [None, "", "e2e-abcd1234@example.com", "someone-else"])
    def test_other_usernames_do_not_protect(self, username):
        """シードでないユーザー名(未指定・空を含む)では、メールアドレスの判定がそのまま使われる。"""
        check.is_true(is_e2e_user("e2e-abcd1234@example.com", username))

    def test_protected_emails_are_the_seed_users(self):
        """保護対象のメールアドレス・ユーザー名は DEV_USERS(小文字)そのもの。"""
        check.equal(PROTECTED_USER_EMAILS, frozenset(user.email.lower() for user in DEV_USERS))
        check.equal(PROTECTED_USERNAMES, frozenset(user.username.lower() for user in DEV_USERS))

    def test_protection_wins_over_the_pattern(self, monkeypatch):
        """保護対象のメールアドレスは、命名パターンに一致していても対象にならない。"""
        monkeypatch.setattr(e2e_cleanup, "PROTECTED_USER_EMAILS", frozenset({"e2e-abcd1234@example.com"}))
        check.is_false(is_e2e_user("E2E-ABCD1234@example.com"))
        check.is_true(is_e2e_user("e2e-abcd1235@example.com"))


class TestTodoTitle:
    """is_e2e_todo_title: ``E2E ToDo <8桁>`` に完全一致。"""

    @pytest.mark.parametrize("title", ["E2E ToDo abcd1234", "E2E ToDo 00000000"])
    def test_matches_e2e_names(self, title):
        """E2E の命名のタイトルは対象。"""
        check.is_true(is_e2e_todo_title(title))

    @pytest.mark.parametrize(
        "title",
        [
            None, "", "todo", "e2e todo abcd1234", "E2E todo abcd1234", "E2E ToDo ", "E2E ToDo abcd123", "E2E ToDo abcd12345", "E2E ToDo ABCD1234", "E2E ToDo abcd1234 ",
            " E2E ToDo abcd1234", "E2E  ToDo abcd1234", "E2E ToDo abcd1234\n", "prefix E2E ToDo abcd1234", "E2E ToDo abcd1234 suffix", "E2E Org abcd1234",
        ],
    )
    def test_rejects_near_misses(self, title):
        """通常の ToDo と、桁数・大文字・前後の文字・空白・改行が違うものは対象外。"""
        check.is_false(is_e2e_todo_title(title))

    def test_returns_a_bool(self):
        """未指定でも真偽値(``None`` や空文字を返さない)。"""
        check.is_true(is_e2e_todo_title(None) is False and is_e2e_todo_title("") is False)


class TestOrganizationName:
    """is_e2e_organization_name: ``E2E Org <8桁>`` に完全一致。デフォルト組織は対象外。"""

    @pytest.mark.parametrize("name", ["E2E Org abcd1234", "E2E Org 99999999"])
    def test_matches_e2e_names(self, name):
        """E2E の命名の組織名は対象。"""
        check.is_true(is_e2e_organization_name(name))

    @pytest.mark.parametrize(
        "name",
        [None, "", DEFAULT_ORGANIZATION_NAME, "営業部", "e2e org abcd1234", "E2E Org abcd123", "E2E Org abcd12345", "E2E Org ABCD1234", "E2E Org abcd1234 ", " E2E Org abcd1234", "E2E ToDo abcd1234"],
    )
    def test_rejects_near_misses(self, name):
        """デフォルト組織・通常の組織名と、桁数・大文字・空白が違うものは対象外。"""
        check.is_false(is_e2e_organization_name(name))

    def test_default_organization_is_protected(self):
        """保護対象の組織名はデフォルト組織だけ。"""
        check.equal(PROTECTED_ORGANIZATION_NAMES, frozenset({DEFAULT_ORGANIZATION_NAME}))

    def test_protection_wins_over_the_pattern(self, monkeypatch):
        """保護対象の組織名は、命名パターンに一致していても対象にならない。"""
        monkeypatch.setattr(e2e_cleanup, "PROTECTED_ORGANIZATION_NAMES", frozenset({"E2E Org abcd1234"}))
        check.is_false(is_e2e_organization_name("E2E Org abcd1234"))
        check.is_true(is_e2e_organization_name("E2E Org abcd1235"))


class TestPlanTenantAction:
    """plan_tenant_action: テナントの状態から処理を決める。"""

    NOW = dt.datetime(2026, 10, 29, 12, 0, 0, tzinfo=dt.UTC)

    @pytest.mark.parametrize("status", [TenantStatus.ACTIVE, TenantStatus.SUSPENDED, TenantStatus.FAILED])
    def test_live_states_request_then_deprovision(self, status):
        """ACTIVE / SUSPENDED / FAILED は、削除要求 → 物理削除。更新日時に依らない。"""
        for updated_at in (self.NOW, self.NOW - dt.timedelta(days=365)):
            check.equal(plan_tenant_action(status, updated_at, self.NOW), TenantCleanupAction.REQUEST_AND_DEPROVISION)
        check.equal(plan_tenant_action(status.value, self.NOW, self.NOW), TenantCleanupAction.REQUEST_AND_DEPROVISION)

    @pytest.mark.parametrize("status", [TenantStatus.PENDING_DELETION, TenantStatus.DEPROVISIONING])
    def test_deletion_states_deprovision_directly(self, status):
        """PENDING_DELETION / DEPROVISIONING は物理削除(失敗した物理削除の再試行を含む)。"""
        check.equal(plan_tenant_action(status, self.NOW, self.NOW), TenantCleanupAction.DEPROVISION)
        check.equal(plan_tenant_action(status.value, self.NOW, self.NOW), TenantCleanupAction.DEPROVISION)

    def test_deleted_is_skipped(self):
        """DELETED は何もしない。"""
        check.equal(plan_tenant_action(TenantStatus.DELETED, self.NOW, self.NOW), TenantCleanupAction.SKIP)

    @pytest.mark.parametrize("status", ["", "UNKNOWN", "active", None])
    def test_unknown_status_is_skipped(self, status):
        """未知の状態(小文字・空・未指定)は何もしない(安全側)。"""
        check.equal(plan_tenant_action(status, self.NOW, self.NOW), TenantCleanupAction.SKIP)

    def test_provisioning_boundary(self):
        """PROVISIONING は、更新から閾値(10 分)ちょうどで中断とみなす(以内は処理中の可能性があるのでスキップ)。"""
        threshold = STALE_PROVISIONING_THRESHOLD
        check.equal(threshold, dt.timedelta(minutes=10))
        just_in = self.NOW - threshold + dt.timedelta(microseconds=1)
        exactly = self.NOW - threshold
        older = self.NOW - threshold - dt.timedelta(microseconds=1)
        check.equal(plan_tenant_action(TenantStatus.PROVISIONING, just_in, self.NOW), TenantCleanupAction.SKIP)
        check.equal(plan_tenant_action(TenantStatus.PROVISIONING, exactly, self.NOW), TenantCleanupAction.REAP_AND_DEPROVISION)
        check.equal(plan_tenant_action(TenantStatus.PROVISIONING, older, self.NOW), TenantCleanupAction.REAP_AND_DEPROVISION)
        check.equal(plan_tenant_action(TenantStatus.PROVISIONING, self.NOW, self.NOW), TenantCleanupAction.SKIP)
        check.equal(plan_tenant_action("PROVISIONING", self.NOW + dt.timedelta(minutes=1), self.NOW), TenantCleanupAction.SKIP)

    def test_custom_stale_threshold(self):
        """閾値は引数で変えられる。"""
        updated_at = self.NOW - dt.timedelta(minutes=3)
        check.equal(plan_tenant_action(TenantStatus.PROVISIONING, updated_at, self.NOW, stale_threshold=dt.timedelta(minutes=5)), TenantCleanupAction.SKIP)
        check.equal(plan_tenant_action(TenantStatus.PROVISIONING, updated_at, self.NOW, stale_threshold=dt.timedelta(minutes=3)), TenantCleanupAction.REAP_AND_DEPROVISION)
        check.equal(plan_tenant_action(TenantStatus.PROVISIONING, updated_at, self.NOW, stale_threshold=dt.timedelta(0)), TenantCleanupAction.REAP_AND_DEPROVISION)


class TestPatternDefinitions:
    """対象のパターン定数は、E2E の接尾辞(小文字英数字 8 桁)に固定されている。"""

    def test_patterns_are_anchored_by_fullmatch_usage(self):
        """4 つのパターンは E2E 以外の文字列に一致しない(部分一致で誤爆しない)。"""
        for pattern, ok, bad in (
            (e2e_cleanup.E2E_TENANT_CODE_PATTERN, "e2e-abcd1234", "xe2e-abcd1234"),
            (e2e_cleanup.E2E_USER_EMAIL_PATTERN, "e2e-abcd1234@example.com", "e2e-abcd1234@example.com.x"),
            (e2e_cleanup.E2E_TODO_TITLE_PATTERN, "E2E ToDo abcd1234", "E2E ToDo abcd1234 x"),
            (e2e_cleanup.E2E_ORGANIZATION_NAME_PATTERN, "E2E Org abcd1234", "x E2E Org abcd1234"),
        ):
            check.is_not_none(pattern.fullmatch(ok))
            check.is_none(pattern.fullmatch(bad))
