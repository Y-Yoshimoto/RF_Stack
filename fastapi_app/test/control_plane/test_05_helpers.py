# -*- coding: utf-8 -*-
"""tenant_provisioning の純粋な補助(一時パスワード・エラー要約・初期管理者・例外のコード)のテスト。DB・Keycloak は不要。"""
import datetime as dt
import uuid

import pytest
import pytest_check as check

from control_plane_app.services import errors
from control_plane_app.services.tenant_provisioning import (
    TEMPORARY_PASSWORD_LENGTH,
    InitialAdminSpec,
    OnboardResult,
    TenantView,
    bump_version,
    generate_temporary_password,
    status_change_payload,
    summarize_error,
    validate_new_tenant_code,
)
from modules.keycloak_admin.errors import KeycloakAdminAuthError, KeycloakAdminError, KeycloakAdminTimeoutError

SYMBOLS = "!@#$%^&*-_=+"


class TestGenerateTemporaryPassword:
    """generate_temporary_password。"""

    def test_default_length_and_character_classes(self):
        """既定は 20 文字で、英大文字・小文字・数字・記号をそれぞれ 1 文字以上含む(100 回試行)。"""
        for _ in range(100):
            password = generate_temporary_password()
            check.equal(len(password), TEMPORARY_PASSWORD_LENGTH)
            check.is_true(any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password) and any(c in SYMBOLS for c in password), "文字種が足りない")

    def test_values_are_not_repeated(self):
        """毎回異なる値を返す(暗号論的乱数)。"""
        check.equal(len({generate_temporary_password() for _ in range(50)}), 50)

    @pytest.mark.parametrize("length", [8, 12, 64])
    def test_custom_length(self, length):
        """長さを指定できる。"""
        check.equal(len(generate_temporary_password(length)), length)

    @pytest.mark.parametrize("length", [0, 7, -1])
    def test_too_short_is_rejected(self, length):
        """8 文字未満は ValueError。"""
        with pytest.raises(ValueError):
            generate_temporary_password(length)


class TestSummarizeError:
    """summarize_error: 履歴・監査ログに残す要約には、ステップ名・例外の型・HTTP ステータスだけを含める。"""

    def test_keycloak_error_with_status(self):
        """KeycloakAdminError は型と HTTP ステータスだけ。operation と detail は含めない。"""
        exc = KeycloakAdminError("create user alice@example.com in realm tenant-x", 409, "errorMessage=User exists with password Secret123")
        summary = summarize_error("ensure_initial_admin", exc)
        check.equal(summary, "step=ensure_initial_admin; error=KeycloakAdminError; http_status=409")
        for leaked in ("alice", "example.com", "Secret123", "tenant-x", "User exists"):
            check.is_not_in(leaked, summary)

    def test_subclass_name_and_no_status(self):
        """派生クラスは型名を残す。ステータスが無い(タイムアウトなど)場合は http_status を付けない。"""
        check.equal(summarize_error("ensure_tenant_realm", KeycloakAdminTimeoutError("op", detail="ReadTimeout")), "step=ensure_tenant_realm; error=KeycloakAdminTimeoutError")
        check.equal(summarize_error("x", KeycloakAdminAuthError("get token", 401, "invalid_grant")), "step=x; error=KeycloakAdminAuthError; http_status=401")

    def test_arbitrary_exception_message_is_not_included(self):
        """一般の例外はメッセージを含めず型名だけ(メッセージに秘匿値が入っていても残さない)。"""
        summary = summarize_error("activate", RuntimeError("password=Hunter2 token=abc"))
        check.equal(summary, "step=activate; error=RuntimeError")


class TestInitialAdminSpec:
    """InitialAdminSpec。"""

    def test_login_username_defaults_to_lowercased_email(self):
        """ユーザー名の既定はメールアドレス(小文字)。前後の空白は除く。"""
        check.equal(InitialAdminSpec(email=" Admin@Example.COM ").login_username, "admin@example.com")

    def test_explicit_username(self):
        """ユーザー名を指定するとそれを使う(小文字化)。"""
        check.equal(InitialAdminSpec(email="a@example.com", username="Root").login_username, "root")

    def test_default_names(self):
        """姓・名の既定値は Keycloak の必須項目を満たす。"""
        spec = InitialAdminSpec(email="a@example.com")
        check.equal((spec.first_name, spec.last_name), ("Tenant", "Administrator"))


class TestResultsDoNotExposePassword:
    """OnboardResult の表現。"""

    def test_repr_hides_temporary_password(self):
        """一時パスワードは repr に出ない(ログに出さないため)。"""
        view = TenantView(id=uuid.uuid4(), tenant_code="x", name="X", status="ACTIVE", realm_name="tenant-x", tier=None, version=2, created_by="a", updated_by="a",
                          created_at=dt.datetime.now(dt.UTC), updated_at=dt.datetime.now(dt.UTC), deletion_requested_at=None, deleted_at=None)
        result = OnboardResult(tenant=view, history_id=uuid.uuid4(), initial_admin_username="admin", temporary_password="Very-Secret-Pw1!")
        check.is_not_in("Very-Secret-Pw1!", repr(result))
        check.is_not_in("Very-Secret-Pw1!", str(result))


class TestSmallHelpers:
    """bump_version / status_change_payload / validate_new_tenant_code。"""

    def test_bump_version(self):
        """バージョンを +1 し、更新者を記録する。"""
        from types import SimpleNamespace

        tenant = SimpleNamespace(version=3, updated_by="old")
        bump_version(tenant, "new")
        check.equal((tenant.version, tenant.updated_by), (4, "new"))

    def test_status_change_payload(self):
        """監査ログの payload は状態とバージョンの変更前後。"""
        check.equal(status_change_payload("ACTIVE", "SUSPENDED", 2, 3), {"status": {"before": "ACTIVE", "after": "SUSPENDED"}, "version": {"before": 2, "after": 3}})
        check.equal(status_change_payload(None, "PROVISIONING", None, 1)["status"], {"before": None, "after": "PROVISIONING"})

    @pytest.mark.parametrize(("code", "reason"), [("ab", "format"), ("ABC", "format"), ("admin", "reserved"), ("dev-login", "reserved"), ("cp", "format"), (None, "format")])
    def test_validate_new_tenant_code_raises_with_reason(self, code, reason):
        """形式違反・予約語は InvalidTenantCodeError(reason 付き、422 相当)。"""
        with pytest.raises(errors.InvalidTenantCodeError) as exc_info:
            validate_new_tenant_code(code)
        check.equal((exc_info.value.field, exc_info.value.reason, exc_info.value.code), ("tenant_code", reason, "invalid_tenant_code"))

    def test_validate_new_tenant_code_accepts(self):
        """正しいコードはそのまま返る。"""
        check.equal(validate_new_tenant_code("acme-1"), "acme-1")


class TestErrorCodes:
    """例外の code は errors.py の表どおりで、重複しない。"""

    def test_codes_match_documented_table(self):
        """各例外の code。API 層はこの値で Problem Details に変換する。"""
        expected = {
            errors.TenantValidationError: "invalid_tenant_input",
            errors.InvalidTenantCodeError: "invalid_tenant_code",
            errors.TenantNotFoundError: "tenant_not_found",
            errors.TenantCodeAlreadyExistsError: "tenant_code_already_exists",
            errors.InvalidTenantTransitionError: "invalid_tenant_transition",
            errors.TenantOperationInProgressError: "tenant_operation_in_progress",
            errors.DeletionGracePeriodNotElapsedError: "deletion_grace_period_not_elapsed",
            errors.TenantVersionConflictError: "tenant_version_conflict",
            errors.ProvisioningFailedError: "tenant_provisioning_failed",
            errors.TenantRealmOperationError: "tenant_realm_operation_failed",
            errors.DeprovisioningFailedError: "tenant_deprovisioning_failed",
        }
        for exception_class, code in expected.items():
            check.equal(exception_class.code, code, exception_class.__name__)
        check.equal(len(set(expected.values())), len(expected))

    def test_hierarchy(self):
        """API 層が基底クラスで一括して扱えるよう、すべて TenantServiceError の派生であり、猶予期間の例外は遷移エラーの派生。"""
        for name in ("TenantValidationError", "TenantNotFoundError", "TenantCodeAlreadyExistsError", "InvalidTenantTransitionError", "TenantOperationInProgressError", "TenantVersionConflictError", "ProvisioningFailedError"):
            check.is_true(issubclass(getattr(errors, name), errors.TenantServiceError), name)
        check.is_true(issubclass(errors.DeletionGracePeriodNotElapsedError, errors.InvalidTenantTransitionError))
        check.is_true(issubclass(errors.InvalidTenantCodeError, errors.TenantValidationError))
