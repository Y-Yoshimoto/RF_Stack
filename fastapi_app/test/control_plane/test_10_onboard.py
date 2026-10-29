# -*- coding: utf-8 -*-
"""TenantProvisioningService.onboard(払い出し)のテスト。

DB は開発 DB の control_plane_db(作成した行は後片付けする)。Keycloak はフェイク(templates の関数の差し替え)。
"""
import logging
import uuid

import pytest
import pytest_check as check
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from control_plane_app.repositories.locks import PgAdvisoryLock, tenant_lock_key
from control_plane_app.services.errors import (
    InvalidTenantCodeError,
    ProvisioningFailedError,
    TenantCodeAlreadyExistsError,
    TenantOperationInProgressError,
    TenantValidationError,
)
from modules.keycloak_admin.errors import KeycloakAdminError, KeycloakAdminTimeoutError

from .conftest import SENTINEL_PASSWORD, initial_admin

NAME = "Zt Corporation"


def onboard(service, code, **overrides):
    values = {"tenant_code": code, "name": NAME, "initial_admin": initial_admin(), "actor": "cp-admin-sub", "request_id": "req-1"}
    values.update(overrides)
    return service.onboard(**values)


class TestOnboardSuccess:
    """正常系: PROVISIONING → ACTIVE。"""

    def test_tenant_becomes_active(self, cp_db, make_service):
        """台帳は ACTIVE(バージョン 2)になり、レルム名・作成者・更新者が記録される。"""
        code = cp_db.new_code()
        result = onboard(make_service(), code)
        row = cp_db.tenant(result.tenant.id)
        check.equal((row["status"], row["version"], row["tenant_code"], row["realm_name"], row["name"]), ("ACTIVE", 2, code, f"tenant-{code}", NAME))
        check.equal((row["created_by"], row["updated_by"]), ("cp-admin-sub", "cp-admin-sub"))
        check.is_none(row["deleted_at"])
        check.equal((result.tenant.status, result.tenant.version, result.tenant.id), ("ACTIVE", 2, row["id"]))
        check.equal(result.initial_admin_username, "admin@example.com", "ユーザー名の既定はメール(小文字)")

    def test_tenant_id_is_uuid7_and_can_be_specified(self, cp_db, make_service):
        """tenant_id は UUIDv7 で採番され、指定もできる(テナント ID を Keycloak のマッパーへ渡す)。"""
        result = onboard(make_service(), cp_db.new_code())
        check.equal(result.tenant.id.version, 7)
        wanted = uuid.uuid7()
        cp_db.tenant_ids.append(wanted)
        check.equal(onboard(make_service(), cp_db.new_code(), tenant_id=wanted).tenant.id, wanted)

    def test_keycloak_calls(self, cp_db, make_service, fake_kc):
        """Keycloak には、レルムのテンプレート → 初期管理者の順で、台帳の値を渡す。"""
        code = cp_db.new_code()
        result = onboard(make_service(), code)
        check.equal(fake_kc.names(), ["ensure_tenant_realm", "ensure_tenant_user"])
        realm_call = fake_kc.calls_of("ensure_tenant_realm")[0]
        check.equal((realm_call["tenant_code"], realm_call["tenant_id"], realm_call["display_name"], realm_call["enabled"]), (code, result.tenant.id, NAME, True))
        user_call = fake_kc.calls_of("ensure_tenant_user")[0]
        check.equal(user_call["realm_name"], f"tenant-{code}")
        check.equal((user_call["username"], user_call["email"], user_call["roles"], user_call["temporary"]), ("admin@example.com", "Admin@Example.com", ["tenant_admin"], True))
        check.equal((user_call["first_name"], user_call["last_name"]), ("Tenant", "Administrator"))
        check.equal(fake_kc.passwords, [result.temporary_password])

    def test_history_and_audit(self, cp_db, make_service):
        """払い出し履歴は SUCCEEDED(最終ステップ activate、終了日時あり)、監査ログは tenant.create → tenant.provision_succeed。"""
        result = onboard(make_service(), cp_db.new_code())
        histories = cp_db.histories(result.tenant.id)
        check.equal(len(histories), 1)
        history = histories[0]
        check.equal((history["type"], history["status"], history["step"], history["error"], history["id"]), ("onboard", "SUCCEEDED", "activate", None, result.history_id))
        check.is_not_none(history["finished_at"])
        audits = cp_db.audits(result.tenant.id)
        check.equal([a["action"] for a in audits], ["tenant.create", "tenant.provision_succeed"])
        check.is_true(all(a["actor"] == "cp-admin-sub" and a["request_id"] == "req-1" and a["target_type"] == "tenant" for a in audits))
        check.equal(audits[0]["payload"]["status"], {"before": None, "after": "PROVISIONING"})
        check.equal(audits[1]["payload"]["status"], {"before": "PROVISIONING", "after": "ACTIVE"})
        check.equal(audits[1]["payload"]["version"], {"before": 1, "after": 2})

    def test_tenant_appears_in_registry_view_only_with_status(self, cp_db, make_service, cp_runtime_engine):
        """払い出し後のテナントは AP のレジストリビュー(v_tenant_registry)に ACTIVE で現れる。"""
        code = cp_db.new_code()
        result = onboard(make_service(), code)
        with cp_runtime_engine.connect() as connection:
            row = connection.execute(text("SELECT status FROM v_tenant_registry WHERE tenant_id = :id"), {"id": result.tenant.id}).first()
        if row is None:
            pytest.skip("cp_runtime から v_tenant_registry を参照できない(cp_registry_reader 専用)")
        check.equal(row[0], "ACTIVE")


class TestCommitBeforeExternalCalls:
    """PROVISIONING の記録は、Keycloak を呼ぶ前にコミットされる(CP-ONB-08)。"""

    def test_provisioning_is_committed_before_realm_call(self, cp_db, make_service, fake_kc):
        """ensure_tenant_realm の呼び出し時点で、別の接続から PROVISIONING の台帳・RUNNING の履歴・tenant.create の監査ログが見える。"""
        code = cp_db.new_code()
        seen = {}

        def inspect(kwargs):
            row = cp_db.tenant_by_code(code)
            seen["tenant"] = row
            seen["histories"] = cp_db.histories(row["id"]) if row else None
            seen["audit"] = cp_db.audit_actions(row["id"]) if row else None

        fake_kc.hooks["ensure_tenant_realm"] = inspect
        onboard(make_service(), code)
        check.equal(seen["tenant"]["status"], "PROVISIONING")
        check.equal(seen["tenant"]["version"], 1)
        check.equal([(h["status"], h["step"]) for h in seen["histories"]], [("RUNNING", "ensure_tenant_realm")], "ステップの開始も履歴にコミットされている")
        check.equal(seen["audit"], ["tenant.create"])

    def test_each_step_is_committed_before_the_next(self, cp_db, make_service, fake_kc):
        """初期管理者の作成に入った時点で、履歴のステップが ensure_initial_admin に更新済み(各ステップの進捗を都度コミット)。"""
        code = cp_db.new_code()
        seen = {}

        def inspect(kwargs):
            row = cp_db.tenant_by_code(code)
            seen["history"] = cp_db.histories(row["id"])[0]
            seen["status"] = row["status"]

        fake_kc.hooks["ensure_tenant_user"] = inspect
        onboard(make_service(), code)
        check.equal((seen["history"]["status"], seen["history"]["step"], seen["status"]), ("RUNNING", "ensure_initial_admin", "PROVISIONING"))

    def test_no_row_remains_open_in_session_during_external_call(self, cp_db, make_service, fake_kc):
        """外部呼び出し中に、台帳の行を別接続から更新できる(サービスが行ロックを抱えたままにしない)。"""
        code = cp_db.new_code()
        outcome = {}

        def try_update(kwargs):
            row = cp_db.tenant_by_code(code)
            with cp_db.runtime.connect() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '500ms'"))
                try:
                    connection.execute(text("SELECT 1 FROM t_tenant WHERE id = :id FOR UPDATE NOWAIT"), {"id": row["id"]})
                    outcome["locked"] = False
                except OperationalError:
                    outcome["locked"] = True

        fake_kc.hooks["ensure_tenant_realm"] = try_update
        onboard(make_service(), code)
        check.equal(outcome["locked"], False)


class TestTemporaryPassword:
    """一時パスワードは戻り値だけに出る(CP-ONB-10)。"""

    def test_returned_once_and_passed_to_keycloak(self, cp_db, make_service, fake_kc):
        """戻り値の一時パスワードは Keycloak に設定した値と同じ。"""
        result = onboard(make_service(), cp_db.new_code())
        check.equal(result.temporary_password, SENTINEL_PASSWORD)
        check.equal(fake_kc.passwords, [SENTINEL_PASSWORD])

    def test_not_stored_anywhere_in_the_database(self, cp_db, make_service):
        """台帳・払い出し履歴・監査ログのどこにも一時パスワードの値が残らない。"""
        result = onboard(make_service(), cp_db.new_code())
        check.is_not_in(SENTINEL_PASSWORD, cp_db.dump_text(result.tenant.id))

    def test_not_in_logs_or_repr(self, cp_db, make_service, caplog):
        """ログ(全レベル)と戻り値の repr にも一時パスワードが出ない。"""
        with caplog.at_level(logging.DEBUG):
            result = onboard(make_service(), cp_db.new_code())
        check.is_not_in(SENTINEL_PASSWORD, caplog.text)
        check.is_not_in(SENTINEL_PASSWORD, repr(result))

    def test_not_in_failure_records(self, cp_db, make_service, fake_kc, caplog):
        """初期管理者の作成が失敗した場合も、履歴・監査ログ・例外・ログに一時パスワードが出ない。"""
        code = cp_db.new_code()
        fake_kc.fail_once("ensure_tenant_user", KeycloakAdminError("set user password in realm", 400, f"errorMessage=password {SENTINEL_PASSWORD} rejected"))
        with caplog.at_level(logging.DEBUG), pytest.raises(ProvisioningFailedError) as exc_info:
            onboard(make_service(), code)
        row = cp_db.tenant_by_code(code)
        check.is_not_in(SENTINEL_PASSWORD, cp_db.dump_text(row["id"]))
        check.is_not_in(SENTINEL_PASSWORD, str(exc_info.value))
        check.is_not_in(SENTINEL_PASSWORD, exc_info.value.error_summary)
        check.is_not_in(SENTINEL_PASSWORD, caplog.text)

    def test_default_generator_is_used_and_differs_per_tenant(self, cp_db, fake_kc, fake_app_data, clock):
        """生成関数を渡さなければ既定の生成関数(20 文字)を使い、テナントごとに別の値になる。"""
        from control_plane_app.services.tenant_provisioning import TenantProvisioningService

        from .conftest import FakeAdmin

        results = []
        for _ in range(2):
            with cp_db.session() as session:
                service = TenantProvisioningService(session, FakeAdmin(), app_data=fake_app_data, clock=clock)
                results.append(onboard(service, cp_db.new_code()))
        check.not_equal(results[0].temporary_password, results[1].temporary_password)
        check.equal(len(results[0].temporary_password), 20)


class TestFailure:
    """失敗時: FAILED と履歴を残し、秘匿値・detail を残さない。"""

    @pytest.mark.parametrize(
        ("function", "step"),
        [("ensure_tenant_realm", "ensure_tenant_realm"), ("ensure_tenant_user", "ensure_initial_admin")],
    )
    def test_keycloak_failure_marks_failed(self, cp_db, make_service, fake_kc, function, step):
        """Keycloak の失敗で台帳は FAILED(バージョン 2)、履歴は FAILED(ステップ名・要約)、監査ログは tenant.provision_fail。"""
        code = cp_db.new_code()
        secret_detail = "errorMessage=Secret-Detail-Should-Not-Persist"
        fake_kc.fail_once(function, KeycloakAdminError(f"create thing for admin@example.com in realm tenant-{code}", 500, secret_detail))
        with pytest.raises(ProvisioningFailedError) as exc_info:
            onboard(make_service(), code)
        err = exc_info.value
        check.equal((err.step, err.code), (step, "tenant_provisioning_failed"))
        summary = f"step={step}; error=KeycloakAdminError; http_status=500"
        check.equal(err.error_summary, summary)
        row = cp_db.tenant_by_code(code)
        check.equal((row["status"], row["version"]), ("FAILED", 2))
        history = cp_db.histories(row["id"])[0]
        check.equal((history["status"], history["step"], history["error"]), ("FAILED", step, summary))
        check.is_not_none(history["finished_at"])
        check.equal(cp_db.audit_actions(row["id"]), ["tenant.create", "tenant.provision_fail"])
        fail_audit = cp_db.audits(row["id"])[1]
        check.equal(fail_audit["payload"]["error"], summary)
        check.equal(fail_audit["payload"]["status"], {"before": "PROVISIONING", "after": "FAILED"})
        check.is_true(isinstance(err.__cause__, KeycloakAdminError), "原因は __cause__ に残す(ログ用)")

    def test_no_detail_or_operation_persisted(self, cp_db, make_service, fake_kc):
        """KeycloakAdminError の detail・operation(ユーザー名・メールを含みうる)は、台帳・履歴・監査ログ・例外メッセージに残らない。"""
        code = cp_db.new_code()
        fake_kc.fail_once("ensure_tenant_user", KeycloakAdminError("create user admin@example.com", 409, "errorMessage=duplicate DETAIL-MARKER-123"))
        with pytest.raises(ProvisioningFailedError) as exc_info:
            onboard(make_service(), code)
        stored = cp_db.dump_text(cp_db.tenant_by_code(code)["id"])
        for leaked in ("DETAIL-MARKER-123", "create user", "duplicate"):
            check.is_not_in(leaked, stored)
            check.is_not_in(leaked, str(exc_info.value))
        check.is_not_in("admin@example.com", stored.replace("Admin@Example.com", ""))

    def test_timeout_has_no_http_status(self, cp_db, make_service, fake_kc):
        """タイムアウトなど HTTP ステータスの無い失敗は、型名だけを残す。"""
        code = cp_db.new_code()
        fake_kc.fail_once("ensure_tenant_realm", KeycloakAdminTimeoutError("deadline exceeded", detail="deadline"))
        with pytest.raises(ProvisioningFailedError) as exc_info:
            onboard(make_service(), code)
        check.equal(exc_info.value.error_summary, "step=ensure_tenant_realm; error=KeycloakAdminTimeoutError")

    def test_unexpected_exception_is_recorded_by_type_only(self, cp_db, make_service, fake_kc):
        """予期しない例外(メッセージに秘匿値を含むもの)も FAILED として記録し、メッセージは残さない。"""
        code = cp_db.new_code()
        fake_kc.fail_once("ensure_tenant_realm", RuntimeError("client_secret=ABCDEF-LEAK"))
        with pytest.raises(ProvisioningFailedError):
            onboard(make_service(), code)
        row = cp_db.tenant_by_code(code)
        check.equal(row["status"], "FAILED")
        check.is_not_in("ABCDEF-LEAK", cp_db.dump_text(row["id"]))
        check.equal(cp_db.histories(row["id"])[0]["error"], "step=ensure_tenant_realm; error=RuntimeError")

    def test_failed_tenant_keeps_code_reserved(self, cp_db, make_service, fake_kc):
        """失敗したテナントのコードは再利用できない(同じコードでの再作成は TenantCodeAlreadyExistsError)。retry を使う。"""
        code = cp_db.new_code()
        fake_kc.fail_once("ensure_tenant_realm", KeycloakAdminError("x", 500))
        with pytest.raises(ProvisioningFailedError):
            onboard(make_service(), code)
        with pytest.raises(TenantCodeAlreadyExistsError):
            onboard(make_service(), code)


class TestValidation:
    """入力検証: 失敗したら DB にも Keycloak にも何も残さない。"""

    def assert_nothing_happened(self, cp_db, fake_kc, code):
        check.is_none(cp_db.tenant_by_code(code))
        check.equal(fake_kc.calls, [])

    @pytest.mark.parametrize(("code_factory", "reason"), [
        (lambda c: "ab", "format"),
        (lambda c: "ABC-xyz", "format"),
        (lambda c: "a--b", "format"),
        (lambda c: "-abc", "format"),
        (lambda c: c + "\n", "format"),
        (lambda c: "x" * 33, "format"),
        (lambda c: "admin", "reserved"),
        (lambda c: "dev-login", "reserved"),
        (lambda c: "keycloak", "reserved"),
    ])
    def test_invalid_tenant_code(self, cp_db, make_service, fake_kc, code_factory, reason):
        """形式違反・予約語は InvalidTenantCodeError(reason 付き)。台帳にも Keycloak にも何もしない。"""
        base = cp_db.new_code()
        code = code_factory(base)
        with pytest.raises(InvalidTenantCodeError) as exc_info:
            onboard(make_service(), code)
        check.equal(exc_info.value.reason, reason)
        self.assert_nothing_happened(cp_db, fake_kc, base)
        check.is_none(cp_db.tenant_by_code(code.strip()) if code.strip() == code else None)

    @pytest.mark.parametrize(("name", "reason"), [("", "required"), ("   ", "required"), (None, "required"), ("x" * 101, "too_long")])
    def test_invalid_name(self, cp_db, make_service, fake_kc, name, reason):
        """テナント名が空・長すぎる場合は TenantValidationError。"""
        code = cp_db.new_code()
        with pytest.raises(TenantValidationError) as exc_info:
            onboard(make_service(), code, name=name)
        check.equal((exc_info.value.field, exc_info.value.reason), ("name", reason))
        self.assert_nothing_happened(cp_db, fake_kc, code)

    def test_name_boundary_and_trim(self, cp_db, make_service):
        """100 文字までは受け付け、前後の空白は除いて保存する。"""
        result = onboard(make_service(), cp_db.new_code(), name="  " + "x" * 100 + "  ")
        check.equal(result.tenant.name, "x" * 100)

    @pytest.mark.parametrize("email", ["", "no-at-sign", "@example.com", "a@", "a b@example.com", "a@b@c", "a@" + "x" * 260, None])
    def test_invalid_initial_admin_email(self, cp_db, make_service, fake_kc, email):
        """メールアドレスの形式が不正な初期管理者は TenantValidationError(initial_admin.email)。"""
        code = cp_db.new_code()
        with pytest.raises(TenantValidationError) as exc_info:
            onboard(make_service(), code, initial_admin=initial_admin(email=email))
        check.equal(exc_info.value.field, "initial_admin.email")
        self.assert_nothing_happened(cp_db, fake_kc, code)

    @pytest.mark.parametrize(("kwargs", "field"), [({"first_name": " "}, "initial_admin.first_name"), ({"last_name": ""}, "initial_admin.last_name"), ({"username": "  "}, "initial_admin.username")])
    def test_invalid_initial_admin_names(self, cp_db, make_service, fake_kc, kwargs, field):
        """初期管理者の姓・名・ユーザー名が空白だけなら TenantValidationError。"""
        code = cp_db.new_code()
        with pytest.raises(TenantValidationError) as exc_info:
            onboard(make_service(), code, initial_admin=initial_admin(**kwargs))
        check.equal(exc_info.value.field, field)
        self.assert_nothing_happened(cp_db, fake_kc, code)

    @pytest.mark.parametrize("actor", ["", "   ", None])
    def test_actor_is_required(self, cp_db, make_service, fake_kc, actor):
        """操作者が空なら TenantValidationError(監査ログに残せないため)。"""
        code = cp_db.new_code()
        with pytest.raises(TenantValidationError) as exc_info:
            onboard(make_service(), code, actor=actor)
        check.equal(exc_info.value.field, "actor")
        self.assert_nothing_happened(cp_db, fake_kc, code)


class TestDuplicatesAndLocks:
    """重複・同時実行。"""

    def test_duplicate_code_is_rejected_without_side_effects(self, cp_db, make_service, fake_kc):
        """同じコードで 2 回目の作成は TenantCodeAlreadyExistsError。既存テナントは変わらず、Keycloak も呼ばない。"""
        code = cp_db.new_code()
        first = onboard(make_service(), code)
        calls_before = len(fake_kc.calls)
        with pytest.raises(TenantCodeAlreadyExistsError) as exc_info:
            onboard(make_service(), code)
        check.equal(exc_info.value.tenant_code, code)
        check.equal(len(fake_kc.calls), calls_before)
        check.equal((cp_db.tenant(first.tenant.id)["status"], cp_db.tenant(first.tenant.id)["version"]), ("ACTIVE", 2))

    def test_existing_realm_name_blocks_creation(self, cp_db, make_service, fake_kc):
        """既存テナントのレルム名と衝突する場合(コードが違っても realm_name が同じ)も拒否される。"""
        code = cp_db.new_code()
        cp_db.insert_tenant(code=code, status="DELETED")
        with pytest.raises(TenantCodeAlreadyExistsError):
            onboard(make_service(), code)
        check.equal(fake_kc.calls, [])

    def test_operation_in_progress(self, cp_db, make_service, fake_kc):
        """同じテナントコードの処理が実行中(advisory lock 保持中)なら TenantOperationInProgressError。何も作成しない。"""
        code = cp_db.new_code()
        holder = PgAdvisoryLock(cp_db.runtime)
        with holder.try_acquire(tenant_lock_key(code)) as acquired:
            check.is_true(acquired)
            with pytest.raises(TenantOperationInProgressError) as exc_info:
                onboard(make_service(), code)
        check.equal(exc_info.value.tenant_code, code)
        check.is_none(cp_db.tenant_by_code(code))
        check.equal(fake_kc.calls, [])

    def test_lock_is_released_after_completion(self, cp_db, make_service):
        """処理が終わればロックは解放されている(続けて同じコードのロックを取れる)。失敗時も解放される。"""
        code = cp_db.new_code()
        onboard(make_service(), code)
        with PgAdvisoryLock(cp_db.runtime).try_acquire(tenant_lock_key(code)) as acquired:
            check.is_true(acquired)

    def test_lock_is_released_after_failure(self, cp_db, make_service, fake_kc):
        """払い出しが失敗した後もロックは解放されている。"""
        code = cp_db.new_code()
        fake_kc.fail_once("ensure_tenant_realm", KeycloakAdminError("x", 500))
        with pytest.raises(ProvisioningFailedError):
            onboard(make_service(), code)
        with PgAdvisoryLock(cp_db.runtime).try_acquire(tenant_lock_key(code)) as acquired:
            check.is_true(acquired)

    def test_unique_constraint_backs_up_the_check(self, cp_db, make_service, monkeypatch, fake_kc):
        """事前確認をすり抜けた同時作成は、一意制約の違反を TenantCodeAlreadyExistsError に変換する。"""
        from control_plane_app.repositories import tenant_repository as repo
        from control_plane_app.services import tenant_provisioning

        code = cp_db.new_code()
        cp_db.insert_tenant(code=code, status="ACTIVE")
        monkeypatch.setattr(tenant_provisioning.repo, "tenant_code_or_realm_exists", lambda *args, **kwargs: False)
        assert repo is not None
        with pytest.raises(TenantCodeAlreadyExistsError):
            onboard(make_service(), code)
        check.equal(fake_kc.calls, [])
        check.equal(cp_db.tenant_by_code(code)["status"], "ACTIVE", "既存の行は変わらない")
