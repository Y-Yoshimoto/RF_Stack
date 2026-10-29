# -*- coding: utf-8 -*-
"""E2EDataCleaner の CP 側(E2E のテナントの物理削除)のテスト。

台帳(開発 DB の ``control_plane_db``)に E2E の命名(``e2e-<8桁>``)の使い捨てテナントを作って確認する。走査対象は ``ScopedCleaner`` で
このテストが作ったテナントに絞る(``conftest.py``)ため、開発 DB の本物のテナントには触れない。Keycloak は ``FakeKc``(レルム操作のフェイク)。
"""
import datetime as dt

import pytest
import pytest_check as check

from dev_tools.e2e_cleanup import CLEANUP_ACTOR, CLEANUP_LOCK_KEY, E2ECleanupInProgressError, E2ECleanupNotAllowedError, TenantCleanupCounts
from modules.keycloak_admin.errors import KeycloakAdminError

from .conftest import MemoryLock

DELETABLE = ["ACTIVE", "SUSPENDED", "FAILED", "PENDING_DELETION", "DEPROVISIONING"]


def status_of(cp_db, tenant_id) -> str:
    return cp_db.tenant(tenant_id)["status"]


class TestDeprovision:
    """削除できる状態のテナントは、物理削除(DELETED)まで進む。"""

    @pytest.mark.parametrize("status", DELETABLE)
    def test_every_deletable_status_ends_deleted(self, make_cleaner, e2e_tenant, cp_db, fake_kc, status):
        """ACTIVE / SUSPENDED / FAILED / PENDING_DELETION / DEPROVISIONING の E2E のテナントは DELETED になり、レルムも消える。1 件削除として数える。"""
        tenant_id = e2e_tenant(status)
        realm = cp_db.tenant(tenant_id)["realm_name"]
        result = make_cleaner().run()
        check.equal(status_of(cp_db, tenant_id), "DELETED")
        check.is_not_none(cp_db.tenant(tenant_id)["deleted_at"])
        check.is_not_in(realm, fake_kc.realms)
        check.equal(result.tenants, TenantCleanupCounts(deprovisioned=1))
        check.equal((result.failures, result.ok, result.dry_run), ([], True, False))

    def test_operator_is_the_cleanup_actor(self, make_cleaner, e2e_tenant, cp_db):
        """台帳の監査ログの操作者は後片付けの専用の値(dev:e2e_cleanup)で、実行者が分かる。"""
        tenant_id = e2e_tenant("ACTIVE")
        make_cleaner().run()
        audits = cp_db.audits(tenant_id)
        check.is_true(audits)
        check.equal({row["actor"] for row in audits}, {CLEANUP_ACTOR})
        check.is_in("tenant.request_deletion", [row["action"] for row in audits])
        check.is_in("tenant.delete", [row["action"] for row in audits])

    def test_no_grace_period_is_waited(self, make_cleaner, e2e_tenant, cp_db):
        """削除要求したばかりでも猶予(30 日)を待たずに物理削除する。"""
        tenant_id = e2e_tenant("PENDING_DELETION", deletion_requested_at=dt.datetime.now(dt.UTC))
        make_cleaner().run()
        check.equal(status_of(cp_db, tenant_id), "DELETED")

    def test_admin_client_is_created_per_tenant_and_closed(self, make_cleaner, e2e_tenant, calls):
        """払い出し用の管理クライアントはテナントごとに作り直し、使い終わったら閉じる。"""
        for _ in range(3):
            e2e_tenant("ACTIVE")
        make_cleaner().run()
        check.equal(calls.provisioner, 3)
        check.is_true(all(admin.closed for admin in calls.admins))

    def test_idempotent(self, make_cleaner, e2e_tenant, cp_db, calls):
        """2 回目の実行は何もしない(DELETED は走査しない)。管理クライアントも作らない。"""
        tenant_id = e2e_tenant("ACTIVE")
        make_cleaner().run()
        provisioner_before = calls.provisioner
        second = make_cleaner().run()
        check.equal(second.tenants, TenantCleanupCounts())
        check.equal(calls.provisioner, provisioner_before)
        check.equal(status_of(cp_db, tenant_id), "DELETED")
        check.equal(len([row for row in cp_db.audits(tenant_id) if row["action"] == "tenant.delete"]), 1)

    def test_deleted_rows_are_kept_in_ledger(self, make_cleaner, e2e_tenant, cp_db):
        """台帳の行・払い出し履歴・監査ログは残す(通常の物理削除と同じ)。"""
        tenant_id = e2e_tenant("ACTIVE")
        make_cleaner().run()
        check.is_not_none(cp_db.tenant(tenant_id))
        check.is_true(cp_db.histories(tenant_id))
        check.is_true(cp_db.audits(tenant_id))


class TestTargetSelection:
    """E2E の命名に一致しないテナントは、状態に依らず何もしない。"""

    @pytest.mark.parametrize("code", ["e2e-x", "e2e-abcd123", "e2e-abcd12345", "e2e-abcd-123", "e2e-ab-cdefg"])
    def test_non_matching_names_are_untouched(self, make_cleaner, e2e_tenant, cp_db, fake_kc, calls, code):
        """接尾辞が 8 桁の小文字英数字でない ``e2e-`` のテナントは対象外。レルムも残り、Keycloak にも触れない(大文字はテナントコードの CHECK で作れない)。"""
        tenant_id = e2e_tenant("ACTIVE", code=code)
        result = make_cleaner().run()
        check.equal(status_of(cp_db, tenant_id), "ACTIVE")
        check.is_in(f"tenant-{code}", fake_kc.realms)
        check.equal(result.tenants, TenantCleanupCounts())
        check.equal(calls.provisioner, 0)

    def test_ordinary_tenant_is_untouched(self, make_cleaner, cp_db, fake_kc):
        """通常のテナント(zt-*)は対象外。E2E のテナントと一緒にあっても、E2E のテナントだけが削除される。"""
        ordinary = cp_db.insert_tenant(status="ACTIVE")
        fake_kc.realms[cp_db.tenant(ordinary)["realm_name"]] = True
        result = make_cleaner().run()
        check.equal((status_of(cp_db, ordinary), result.tenants), ("ACTIVE", TenantCleanupCounts()))

    def test_mixed(self, make_cleaner, e2e_tenant, cp_db, fake_kc):
        """対象と対象外が混在しても、対象だけが削除される。"""
        target = e2e_tenant("ACTIVE")
        near_miss = e2e_tenant("ACTIVE", code="e2e-abcd12345")
        ordinary = cp_db.insert_tenant(status="SUSPENDED")
        result = make_cleaner().run()
        check.equal(
            (status_of(cp_db, target), status_of(cp_db, near_miss), status_of(cp_db, ordinary)),
            ("DELETED", "ACTIVE", "SUSPENDED"),
        )
        check.equal(result.tenants.deprovisioned, 1)

    def test_deleted_tenant_is_not_listed(self, make_cleaner, e2e_tenant, cp_db, calls):
        """DELETED のテナントは一覧に含めず、数えない・処理しない。"""
        e2e_tenant("DELETED")
        result = make_cleaner().run()
        check.equal((result.tenants, calls.provisioner), (TenantCleanupCounts(), 0))


class TestProvisioning:
    """PROVISIONING は、最終更新からの経過時間とテナントのロックで扱いを決める。"""

    def test_fresh_provisioning_is_skipped(self, make_cleaner, e2e_tenant, cp_db, calls):
        """更新から 10 分以内の PROVISIONING は、払い出しが実行中の可能性があるのでスキップ(状態を変えず、Keycloak にも触れない)。"""
        tenant_id = e2e_tenant("PROVISIONING", updated_at_ago=dt.timedelta(minutes=9))
        result = make_cleaner().run()
        check.equal(status_of(cp_db, tenant_id), "PROVISIONING")
        check.equal(result.tenants, TenantCleanupCounts(skipped=1))
        check.equal(calls.provisioner, 0)
        check.is_true(result.ok)

    def test_stale_provisioning_is_reaped_then_deleted(self, make_cleaner, e2e_tenant, cp_db):
        """10 分以上更新の無い PROVISIONING は、FAILED にして(中断として履歴も閉じ)から削除する。回収と削除の両方で数える。"""
        tenant_id = e2e_tenant("PROVISIONING", updated_at_ago=dt.timedelta(minutes=11), with_running_history=True)
        result = make_cleaner().run()
        check.equal(status_of(cp_db, tenant_id), "DELETED")
        check.equal(result.tenants, TenantCleanupCounts(deprovisioned=1, reaped=1))
        check.is_in("tenant.provision_reap", cp_db.audit_actions(tenant_id))
        onboard = [history for history in cp_db.histories(tenant_id) if history["type"] == "onboard"]
        check.equal([history["status"] for history in onboard], ["FAILED"])

    def test_boundary_uses_injected_clock_and_threshold(self, make_cleaner, e2e_tenant, cp_db, clock):
        """経過時間は差し替えた時計と閾値で判定する(時計を進めると同じテナントが回収の対象になる)。"""
        tenant_id = e2e_tenant("PROVISIONING", updated_at_ago=dt.timedelta(seconds=1))
        first = make_cleaner(stale_provisioning_threshold=dt.timedelta(minutes=5), clock=clock).run()
        check.equal((status_of(cp_db, tenant_id), first.tenants), ("PROVISIONING", TenantCleanupCounts(skipped=1)))
        clock.advance(minutes=5, seconds=2)
        second = make_cleaner(stale_provisioning_threshold=dt.timedelta(minutes=5), clock=clock).run()
        check.equal((status_of(cp_db, tenant_id), second.tenants), ("DELETED", TenantCleanupCounts(deprovisioned=1, reaped=1)))

    def test_locked_tenant_is_skipped(self, make_cleaner, e2e_tenant, cp_db):
        """中断とみなせる PROVISIONING でも、テナントのロックが取れなければ(払い出し中)FAILED にせずスキップする。"""
        from control_plane_app.repositories.locks import tenant_lock_key

        tenant_id = e2e_tenant("PROVISIONING", updated_at_ago=dt.timedelta(minutes=30))
        code = cp_db.tenant(tenant_id)["tenant_code"]
        result = make_cleaner(lock=MemoryLock({tenant_lock_key(code)})).run()
        check.equal(status_of(cp_db, tenant_id), "PROVISIONING")
        check.equal(result.tenants, TenantCleanupCounts(skipped=1))
        check.is_true(result.ok)

    def test_operation_in_progress_during_deprovision_is_skipped(self, make_cleaner, e2e_tenant, cp_db):
        """物理削除のテナントのロックが取れなければ(別の処理が実行中)、失敗ではなくスキップとして数える。

        削除要求(ACTIVE -> PENDING_DELETION)までは進み、物理削除だけが次回に持ち越される。ロックが解ければ次の実行で DELETED になる。
        """
        from control_plane_app.repositories.locks import tenant_lock_key

        tenant_id = e2e_tenant("ACTIVE")
        code = cp_db.tenant(tenant_id)["tenant_code"]
        result = make_cleaner(lock=MemoryLock({tenant_lock_key(code)})).run()
        check.equal(status_of(cp_db, tenant_id), "PENDING_DELETION")
        check.equal(result.tenants, TenantCleanupCounts(skipped=1))
        check.equal(result.failures, [])
        make_cleaner().run()
        check.equal(status_of(cp_db, tenant_id), "DELETED")


class TestDryRun:
    """dry_run は何も変更せず、実行した場合と同じ件数を返す。"""

    def build_mixture(self, e2e_tenant, cp_db):
        ids = {
            "active": e2e_tenant("ACTIVE"),
            "failed": e2e_tenant("FAILED"),
            "pending": e2e_tenant("PENDING_DELETION"),
            "stale": e2e_tenant("PROVISIONING", updated_at_ago=dt.timedelta(minutes=20)),
            "fresh": e2e_tenant("PROVISIONING", updated_at_ago=dt.timedelta(minutes=1)),
            "near_miss": e2e_tenant("ACTIVE", code="e2e-abcd12345"),
            "ordinary": cp_db.insert_tenant(status="ACTIVE"),
        }
        return ids

    def test_counts_match_the_real_run_and_nothing_changes(self, make_cleaner, e2e_tenant, cp_db, fake_kc, calls):
        """dry_run の件数は実行後の件数と一致し(削除 4・回収 1・スキップ 1)、dry_run では台帳も Keycloak も変わらない。"""
        ids = self.build_mixture(e2e_tenant, cp_db)
        before = {name: cp_db.tenant(tenant_id) for name, tenant_id in ids.items()}
        realms_before = dict(fake_kc.realms)
        dry = make_cleaner().run(dry_run=True)
        check.is_true(dry.dry_run)
        check.equal({name: cp_db.tenant(tenant_id) for name, tenant_id in ids.items()}, before)
        check.equal(fake_kc.realms, realms_before)
        check.equal((calls.provisioner, fake_kc.calls), (0, []))
        check.equal(dry.tenants, TenantCleanupCounts(deprovisioned=4, reaped=1, skipped=1))

        real = make_cleaner().run()
        check.equal(real.tenants, dry.tenants)
        check.equal({name: status_of(cp_db, tenant_id) for name, tenant_id in ids.items()},
                    {"active": "DELETED", "failed": "DELETED", "pending": "DELETED", "stale": "DELETED", "fresh": "PROVISIONING", "near_miss": "ACTIVE", "ordinary": "ACTIVE"})

    def test_second_run_converges(self, make_cleaner, e2e_tenant, cp_db):
        """実行後の dry_run は削除 0(スキップ中の PROVISIONING だけが残る)。何度実行しても同じ状態に収束する。"""
        self.build_mixture(e2e_tenant, cp_db)
        make_cleaner().run()
        after = make_cleaner().run(dry_run=True)
        check.equal(after.tenants, TenantCleanupCounts(skipped=1))
        again = make_cleaner().run()
        check.equal(again.tenants, TenantCleanupCounts(skipped=1))

    def test_dry_run_does_not_open_provisioner_admin(self, make_cleaner, e2e_tenant, calls):
        """dry_run では払い出し用の管理クライアントを作らない。"""
        e2e_tenant("ACTIVE")
        make_cleaner().run(dry_run=True)
        check.equal(calls.provisioner, 0)


class TestFailure:
    """1 つのテナントの失敗が他のテナントを止めない。失敗は結果に記録する。"""

    def test_failure_is_recorded_and_others_continue(self, make_cleaner, e2e_tenant, cp_db, fake_kc):
        """レルムの削除に失敗したテナントは DEPROVISIONING のまま failures に記録し、他のテナントは削除する。次の実行で再試行して収束する。"""
        first, second = e2e_tenant("ACTIVE"), e2e_tenant("ACTIVE")
        fake_kc.fail_once("delete_realm_if_exists", KeycloakAdminError("delete realm", 500, "boom-detail-SECRET"))
        result = make_cleaner().run()
        statuses = sorted([status_of(cp_db, first), status_of(cp_db, second)])
        check.equal(statuses, ["DELETED", "DEPROVISIONING"])
        check.equal(result.tenants, TenantCleanupCounts(deprovisioned=1, failed=1))
        check.is_false(result.ok)
        check.equal(len(result.failures), 1)
        failure = result.failures[0]
        check.equal(failure.scope, "cp")
        check.is_in(failure.tenant_code, {cp_db.tenant(first)["tenant_code"], cp_db.tenant(second)["tenant_code"]})
        check.is_not_in("SECRET", repr(result.to_dict()))

        retry = make_cleaner().run()
        check.equal((status_of(cp_db, first), status_of(cp_db, second)), ("DELETED", "DELETED"))
        check.equal((retry.tenants, retry.ok), (TenantCleanupCounts(deprovisioned=1), True))

    def test_realm_disable_failure_keeps_status(self, make_cleaner, e2e_tenant, cp_db, fake_kc):
        """削除要求でのレルムの無効化に失敗したら状態は ACTIVE のまま(失敗として記録)。"""
        tenant_id = e2e_tenant("ACTIVE")
        fake_kc.fail_once("set_realm_enabled", KeycloakAdminError("disable realm", 503, "unavailable"))
        result = make_cleaner().run()
        check.equal(status_of(cp_db, tenant_id), "ACTIVE")
        check.equal((result.tenants.failed, result.ok), (1, False))
        check.equal(result.failures[0].scope, "cp")

    def test_to_dict_is_json_ready(self, make_cleaner, e2e_tenant):
        """結果は JSON にできる辞書で、ok を含む。"""
        import json

        e2e_tenant("ACTIVE")
        payload = make_cleaner().run().to_dict()
        json.dumps(payload)
        check.equal(set(payload), {"dry_run", "tenants", "app_tenants", "failures", "ok"})
        check.equal(set(payload["tenants"]), {"deprovisioned", "reaped", "skipped", "failed"})


class TestConcurrency:
    """後片付け全体の排他。"""

    def test_second_cleanup_is_rejected_while_running(self, make_cleaner, e2e_tenant, cp_db, calls):
        """全体のロックが取れなければ E2ECleanupInProgressError。何も処理せず、Keycloak にも触れない。"""
        tenant_id = e2e_tenant("ACTIVE")
        with pytest.raises(E2ECleanupInProgressError):
            make_cleaner(lock=MemoryLock({CLEANUP_LOCK_KEY})).run()
        check.equal((status_of(cp_db, tenant_id), calls.provisioner), ("ACTIVE", 0))

    def test_lock_is_released_after_run(self, make_cleaner, e2e_tenant):
        """実行が終わればロックを解放する(続けて実行できる)。例外でも解放する。"""
        lock = MemoryLock()
        e2e_tenant("ACTIVE")
        make_cleaner(lock=lock).run()
        check.equal(lock.held, set())
        check.equal(lock.acquired[0], CLEANUP_LOCK_KEY)
        make_cleaner(lock=lock).run(dry_run=True)

    def test_real_advisory_lock_rejects_concurrent_run(self, make_cleaner, e2e_tenant, cp_db, cp_runtime_engine, monkeypatch):
        """実際の advisory lock(既定の実装)でも、別の接続が保持している間は E2ECleanupInProgressError になり、解放後は実行できる。"""
        import uuid

        from control_plane_app.repositories.locks import PgAdvisoryLock
        from dev_tools import e2e_cleanup

        key = f"dev:e2e_cleanup:test:{uuid.uuid4().hex}"
        monkeypatch.setattr(e2e_cleanup, "CLEANUP_LOCK_KEY", key)
        tenant_id = e2e_tenant("ACTIVE")
        holder = PgAdvisoryLock(cp_runtime_engine)
        with holder.try_acquire(key) as acquired:
            check.is_true(acquired)
            with pytest.raises(E2ECleanupInProgressError):
                make_cleaner(lock=None).run()
            check.equal(status_of(cp_db, tenant_id), "ACTIVE")
        result = make_cleaner(lock=None).run()
        check.equal((status_of(cp_db, tenant_id), result.tenants), ("DELETED", TenantCleanupCounts(deprovisioned=1)))


class TestNotAllowed:
    """開発環境でなければ、DB・Keycloak に接続せず拒否する。"""

    @pytest.mark.parametrize(
        ("app_env", "dev_login"),
        [("production", "true"), ("staging", "true"), ("", "true"), ("development", "false"), ("development", ""), ("development", "0")],
    )
    def test_refused_without_touching_anything(self, make_cleaner, e2e_tenant, cp_db, calls, monkeypatch, app_env, dev_login):
        """APP_ENV が development でない、または開発用ログインが無効なら E2ECleanupNotAllowedError。セッション・管理クライアントを一切作らず、台帳も変えない。"""
        tenant_id = e2e_tenant("ACTIVE")
        monkeypatch.setenv("APP_ENV", app_env)
        monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", dev_login)

        def forbidden():
            raise AssertionError("開発環境以外で依存が使われた")

        cleaner = make_cleaner(cp_session_factory=forbidden, app_engine_factory=forbidden, provisioner_admin_factory=forbidden, tenant_user_admin_factory=lambda realm: forbidden())
        for dry_run in (True, False):
            with pytest.raises(E2ECleanupNotAllowedError):
                cleaner.run(dry_run=dry_run)
        check.equal((status_of(cp_db, tenant_id), calls.provisioner), ("ACTIVE", 0))

