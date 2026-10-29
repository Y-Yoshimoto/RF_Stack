# -*- coding: utf-8 -*-
"""E2EDataCleaner の AP 側(E2E のユーザー・組織・ToDo の物理削除と Keycloak のユーザー削除)のテスト。

**使い捨てのテナント**(台帳の ``zt-*`` + AP のデータ)の中に、E2E の命名のデータと対象外のデータを作って確認する。AP の走査対象は
alpha / beta のうち ACTIVE なものだけなので、``scan_as_seed`` でこのテナントを走査対象に加える(``conftest.py``)。alpha / beta のデータには触れない。
Keycloak は ``TenantRealmIdp``(ユーザー管理のフェイク)。
"""
import uuid
from dataclasses import dataclass

import pytest
import pytest_check as check
from todos.conftest import TodoFactory

from dev_tools.e2e_cleanup import AppTenantCleanupCounts, CleanupFailure
from main_app.models import TTodoActivity, TUser
from main_app.repositories.audit_log import add_ap_audit_log
from main_app.services.user_sync import DEFAULT_ORGANIZATION_NAME
from modules.tenancy.context import TenantContext

# E2E の命名(接尾辞は小文字英数字 8 桁)
U_EMAIL = "e2e-aaaa1111@example.com"
KC_ONLY_EMAIL = "e2e-bbbb2222@example.com"
ORG_NAME = "E2E Org dddd4444"
TODO_TITLE = "E2E ToDo eeee5555"
DELETED_TODO_TITLE = "E2E ToDo ffff6666"
# 対象外(桁数が違う・大文字・余分な文字)
NEAR_ORG = "E2E Org dddd44445"
NEAR_TODO = "E2E ToDo eeee55556"
NEAR_EMAIL = "e2e-aaaa11112@example.com"


@dataclass
class SeedUser:
    id: uuid.UUID
    sub: str
    email: str


class ApSeed:
    """使い捨てテナントの AP のデータと、テナントレルムの Keycloak のユーザーを作る補助。"""

    def __init__(self, ap_db, idp, ctx: TenantContext, code: str) -> None:
        self.ap_db, self.idp, self.ctx, self.code = ap_db, idp, ctx, code
        self.realm = f"tenant-{code}"
        self.factory = TodoFactory(ap_db)
        idp.ensure_realm(self.realm)

    def user(self, email: str, *, username: str | None = None, in_idp: bool = True, created_by: uuid.UUID | None = None, active: bool = True) -> SeedUser:
        """AP のユーザー(と、``in_idp`` なら Keycloak のユーザー)を作る。"""
        sub = self.idp.seed_user(self.realm, username=username or email, email=email) if in_idp else str(uuid.uuid4())
        with self.ap_db.session(self.ctx) as session:
            row = TUser(tenant_id=self.ctx.tenant_id, idp_subject=sub, email=email, display_name=email, is_active=active, created_by=created_by, updated_by=created_by)
            session.add(row)
            session.commit()
            return SeedUser(id=row.id, sub=sub, email=email)

    def kc_only(self, email: str, *, username: str | None = None) -> str:
        """Keycloak にだけ存在するユーザー(AP の行が無い)を作る。"""
        return self.idp.seed_user(self.realm, username=username or email, email=email)

    def org(self, name: str, *, created_by: uuid.UUID | None = None, deleted: bool = False, members: tuple[uuid.UUID, ...] = ()) -> uuid.UUID:
        from main_app.models import TOrganization, TOrganizationMember

        with self.ap_db.session(self.ctx) as session:
            org = TOrganization(tenant_id=self.ctx.tenant_id, name=name, created_by=created_by, updated_by=created_by)
            if deleted:
                import datetime as dt

                org.deleted_at = dt.datetime.now(dt.UTC)
            session.add(org)
            session.flush()
            for user_id in members:
                session.add(TOrganizationMember(tenant_id=self.ctx.tenant_id, organization_id=org.id, user_id=user_id))
            session.commit()
            return org.id

    def todo(self, title: str, creator: uuid.UUID, **kwargs) -> uuid.UUID:
        return self.factory.add(self.ctx, creator, title=title, **kwargs)

    def activity(self, todo_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        with self.ap_db.session(self.ctx) as session:
            session.add(TTodoActivity(tenant_id=self.ctx.tenant_id, todo_id=todo_id, actor_id=actor_id, action="updated", payload={}))
            session.commit()

    def audit(self, *, actor_id: uuid.UUID | None, target_type: str, target_id: uuid.UUID, action: str = "x.update") -> None:
        with self.ap_db.session(self.ctx) as session:
            add_ap_audit_log(session, tenant_id=self.ctx.tenant_id, actor_id=actor_id, action=action, target_type=target_type, target_id=target_id, payload=None, request_id=None)
            session.commit()

    # -- 参照 -------------------------------------------------------------------
    def names(self, sql: str) -> set[str]:
        return {row["v"] for row in self.ap_db.rows(self.ctx, sql)}

    def remaining(self) -> dict[str, object]:
        """残っているデータ(識別できる値)。"""
        return {
            "users": self.names("SELECT email AS v FROM t_user"),
            "orgs": self.names("SELECT name AS v FROM t_organization"),
            "todos": self.names("SELECT title AS v FROM t_todo"),
            "members": len(self.ap_db.rows(self.ctx, "SELECT 1 FROM t_organization_member")),
            "assignees": len(self.ap_db.rows(self.ctx, "SELECT 1 FROM t_todo_assignee")),
            "todo_orgs": len(self.ap_db.rows(self.ctx, "SELECT 1 FROM t_todo_organization")),
            "activities": len(self.ap_db.rows(self.ctx, "SELECT 1 FROM t_todo_activity")),
            "audits": len(self.ap_db.rows(self.ctx, "SELECT 1 FROM t_ap_audit_log")),
            "kc": {user["email"] for user in self.idp.users(self.realm).values()},
        }


@pytest.fixture
def tenant(cp_db, ap_db, idp, scan_as_seed) -> ApSeed:
    """AP の走査対象にした使い捨てテナント(台帳に ACTIVE の ``zt-*``)。"""
    tenant_id = cp_db.insert_tenant(status="ACTIVE")
    code = cp_db.tenant(tenant_id)["tenant_code"]
    ap_db.track(tenant_id)
    scan_as_seed(code)
    ctx = TenantContext(tenant_id=tenant_id, tenant_code=code, plane="app")
    return ApSeed(ap_db, idp, ctx, code)


@pytest.fixture
def world(tenant: ApSeed):
    """対象と対象外が混在する AP のデータ(``World``)。"""

    class World:
        pass

    w = World()
    w.alice = tenant.user("alice@example.com")
    w.u = tenant.user(U_EMAIL)
    w.near_user = tenant.user(NEAR_EMAIL)
    w.kc_only_sub = tenant.kc_only(KC_ONLY_EMAIL)
    # Keycloak にだけ存在する、保護対象・対象外のユーザー
    tenant.kc_only("e2e-cccc3333@example.com", username="alpha-member")  # ユーザー名がシードのユーザー
    tenant.kc_only("alpha-member2@example.com", username="someone")  # メールアドレスがシードのユーザー
    tenant.kc_only("bob@example.com", username="bob")
    w.default_org = tenant.org(DEFAULT_ORGANIZATION_NAME)
    w.sales = tenant.org("営業部", members=(w.u.id, w.alice.id))
    w.near_org = tenant.org(NEAR_ORG)
    w.org = tenant.org(ORG_NAME, created_by=w.u.id, members=(w.u.id, w.alice.id))
    w.todo = tenant.todo(TODO_TITLE, w.alice.id, assignees=[w.u.id, w.alice.id], orgs=[w.org])
    w.deleted_todo = tenant.todo(DELETED_TODO_TITLE, w.alice.id, deleted=True)
    w.near_todo = tenant.todo(NEAR_TODO, w.alice.id, assignees=[w.u.id], orgs=[w.sales])
    w.ordinary_todo = tenant.todo("買い物", w.alice.id, assignees=[w.alice.id])
    tenant.activity(w.todo, w.u.id)
    tenant.activity(w.todo, w.alice.id)
    tenant.activity(w.near_todo, w.alice.id)
    # 監査ログ: 対象が削除する行(target)のもの 4 件と、残す 3 件(対象外の行への操作。操作者が E2E のユーザーでも消さない)
    tenant.audit(actor_id=w.alice.id, target_type="user", target_id=w.u.id)
    tenant.audit(actor_id=None, target_type="organization", target_id=w.org)
    tenant.audit(actor_id=w.alice.id, target_type="todo", target_id=w.todo)
    tenant.audit(actor_id=w.alice.id, target_type="todo", target_id=w.deleted_todo)
    tenant.audit(actor_id=w.u.id, target_type="organization", target_id=w.sales)
    tenant.audit(actor_id=w.alice.id, target_type="user", target_id=w.alice.id)
    tenant.audit(actor_id=w.alice.id, target_type="todo", target_id=w.near_todo)
    w.tenant = tenant
    return w


EXPECTED = AppTenantCleanupCounts(
    tenant_code="",
    users=1, keycloak_users=2, skipped_users=0, organizations=1, organization_members=3, todos=2, todo_activities=2, todo_assignees=3, todo_organizations=1, audit_logs=4,
)


def expected_counts(code: str, **overrides) -> AppTenantCleanupCounts:
    values = {name: getattr(EXPECTED, name) for name in EXPECTED.__slots__}
    values.update(overrides, tenant_code=code)
    return AppTenantCleanupCounts(**values)


class TestPurge:
    """対象のデータだけが削除され、対象外は残る。"""

    def test_removes_only_the_targets(self, make_cleaner, world, idp):
        """E2E のユーザー・組織・ToDo(論理削除済みを含む)と、その子の行・Keycloak のユーザーを削除する。対象外(通常のデータ・桁数違い・デフォルト組織・シードのユーザー)は残る。"""
        tenant = world.tenant
        result = make_cleaner().run()
        check.equal(result.failures, [])
        check.equal(result.app_tenants, [expected_counts(tenant.code)])
        remaining = tenant.remaining()
        check.equal(remaining["users"], {"alice@example.com", NEAR_EMAIL})
        check.equal(remaining["orgs"], {DEFAULT_ORGANIZATION_NAME, "営業部", NEAR_ORG})
        check.equal(remaining["todos"], {NEAR_TODO, "買い物"})
        # 残る行: メンバー(営業部の alice)、担当者(near_todo の U は削除され ordinary の alice のみ)、公開先(near_todo → 営業部)、アクティビティ(near_todo)、監査ログ 3 件
        check.equal((remaining["members"], remaining["assignees"], remaining["todo_orgs"], remaining["activities"], remaining["audits"]), (1, 1, 1, 1, 3))
        check.equal(remaining["kc"], {"alice@example.com", NEAR_EMAIL, "e2e-cccc3333@example.com", "alpha-member2@example.com", "bob@example.com"})
        check.equal(sorted(realm for realm, _ in idp.deleted), [tenant.realm, tenant.realm])

    def test_dry_run_counts_match_the_real_run_and_change_nothing(self, make_cleaner, world, idp):
        """dry_run の件数は実際に削除した件数と同じで、dry_run では AP も Keycloak も変わらない。"""
        tenant = world.tenant
        before = tenant.remaining()
        dry = make_cleaner().run(dry_run=True)
        check.equal(tenant.remaining(), before)
        check.equal(idp.deleted, [])
        real = make_cleaner().run()
        check.equal(dry.app_tenants, real.app_tenants)
        check.equal(dry.app_tenants, [expected_counts(tenant.code)])
        check.is_true(dry.dry_run and not real.dry_run)

    def test_idempotent(self, make_cleaner, world, idp):
        """2 回目は何も削除せず(件数 0)、状態は変わらない。"""
        tenant = world.tenant
        make_cleaner().run()
        after_first = tenant.remaining()
        second = make_cleaner().run()
        check.equal(second.app_tenants, [AppTenantCleanupCounts(tenant_code=tenant.code)])
        check.equal(tenant.remaining(), after_first)
        check.equal(len(idp.deleted), 2)

    def test_tenant_user_admin_uses_tenant_realm(self, make_cleaner, world, calls):
        """Keycloak はテナントのレルム(``tenant-<コード>``)に対して、テナントごとに管理クライアントを作って操作する。"""
        make_cleaner().run()
        check.equal(calls.tenant_user_admin, [world.tenant.realm])

    def test_audit_log_is_removed_by_target_not_actor(self, make_cleaner, world):
        """監査ログは対象(target)が削除した行のものだけ消す。操作者(actor)が E2E のユーザーの行は、対象が残っていれば残す。"""
        tenant = world.tenant
        make_cleaner().run()
        rows = tenant.ap_db.audits(tenant.ctx)
        check.equal(sorted((row["target_type"], row["actor_id"] == world.u.id) for row in rows), [("organization", True), ("todo", False), ("user", False)])

    def test_keycloak_only_users_follow_the_same_rules(self, make_cleaner, world):
        """AP の行が無い Keycloak のユーザーも、メールアドレスが E2E の命名なら削除する。ただしユーザー名またはメールアドレスがシードのユーザーのものは削除しない。"""
        tenant = world.tenant
        make_cleaner().run()
        emails = {user["email"] for user in tenant.idp.users(tenant.realm).values()}
        check.is_not_in(KC_ONLY_EMAIL, emails)
        check.is_in("e2e-cccc3333@example.com", emails)
        check.is_in("alpha-member2@example.com", emails)
        check.is_in("bob@example.com", emails)

    def test_user_already_missing_in_keycloak(self, make_cleaner, world, idp):
        """Keycloak から既に消えている対象のユーザーでも AP の行は削除する(Keycloak の削除は数えない)。"""
        tenant = world.tenant
        idp.users(tenant.realm).pop(world.u.sub)
        result = make_cleaner().run()
        check.equal(result.failures, [])
        counts = result.app_tenants[0]
        check.equal((counts.users, counts.keycloak_users), (1, 1))
        check.is_not_in(U_EMAIL, tenant.remaining()["users"])


class TestReferencedUsers:
    """削除しない行から参照されているユーザーは、外部キーを壊さないよう削除しない。"""

    def test_user_referenced_by_a_kept_row_is_skipped(self, make_cleaner, tenant, idp):
        """E2E のユーザーが、対象外の組織の作成者なら削除せずスキップする(AP の行も Keycloak のユーザーも残る)。他のユーザーは削除する。"""
        blocked = tenant.user(U_EMAIL)
        free = tenant.user("e2e-gggg7777@example.com")
        tenant.org("営業部", created_by=blocked.id)
        result = make_cleaner().run()
        counts = result.app_tenants[0]
        check.equal((counts.users, counts.skipped_users, counts.keycloak_users), (1, 1, 1))
        check.equal(tenant.remaining()["users"], {U_EMAIL})
        check.is_in(U_EMAIL, tenant.remaining()["kc"])
        check.is_not_in(free.email, tenant.remaining()["kc"])
        check.is_true(result.ok)

    def test_skipped_user_is_stable_across_runs(self, make_cleaner, tenant):
        """スキップされたユーザーは、dry_run でも実行でも、何度実行しても同じ件数でスキップされ続ける。"""
        blocked = tenant.user(U_EMAIL)
        tenant.todo("通常の ToDo", blocked.id)
        dry = make_cleaner().run(dry_run=True)
        first = make_cleaner().run()
        second = make_cleaner().run()
        check.equal((dry.app_tenants[0].skipped_users, first.app_tenants[0].skipped_users, second.app_tenants[0].skipped_users), (1, 1, 1))
        check.equal(tenant.remaining()["users"], {U_EMAIL})

    def test_reference_chain_is_followed(self, make_cleaner, tenant):
        """スキップしたユーザーに参照されている別の E2E のユーザーも、連鎖してスキップする(変わらなくなるまで繰り返す)。"""
        base = tenant.user("e2e-hhhh8888@example.com")
        child = tenant.user(U_EMAIL, created_by=base.id)  # child -> base を参照
        tenant.user("alice@example.com", created_by=child.id)  # 対象外の alice が child を参照
        result = make_cleaner().run()
        counts = result.app_tenants[0]
        check.equal((counts.users, counts.skipped_users), (0, 2))
        check.equal(tenant.remaining()["users"], {"e2e-hhhh8888@example.com", U_EMAIL, "alice@example.com"})

    def test_references_from_deleted_rows_do_not_block(self, make_cleaner, tenant):
        """削除する行(対象の組織・ToDo・ユーザー)からの参照では止まらない。対象のユーザー同士の参照もまとめて削除できる。"""
        base = tenant.user("e2e-hhhh8888@example.com")
        child = tenant.user(U_EMAIL, created_by=base.id)
        tenant.org(ORG_NAME, created_by=child.id)
        tenant.todo(TODO_TITLE, base.id)
        result = make_cleaner().run()
        counts = result.app_tenants[0]
        check.equal((counts.users, counts.skipped_users, counts.organizations, counts.todos), (2, 0, 1, 1))
        check.equal(tenant.remaining()["users"], set())

    def test_assignee_row_of_target_user_is_removed_without_blocking(self, make_cleaner, tenant):
        """E2E のユーザーが対象外の ToDo の担当者になっているだけなら、担当者の行を消してユーザーも削除する。"""
        user = tenant.user(U_EMAIL)
        alice = tenant.user("alice@example.com")
        tenant.todo("通常の ToDo", alice.id, assignees=[user.id])
        result = make_cleaner().run()
        counts = result.app_tenants[0]
        check.equal((counts.users, counts.skipped_users, counts.todo_assignees), (1, 0, 1))
        check.equal(tenant.names("SELECT title AS v FROM t_todo"), {"通常の ToDo"})

    def test_assigned_by_target_user_blocks(self, make_cleaner, tenant):
        """E2E のユーザーが対象外の担当者を割り当てた(``assigned_by``)行が残るなら、そのユーザーは削除しない。"""
        user = tenant.user(U_EMAIL)
        alice = tenant.user("alice@example.com")
        todo = tenant.todo("通常の ToDo", alice.id)
        with tenant.ap_db.session(tenant.ctx) as session:
            from main_app.models import TTodoAssignee

            session.add(TTodoAssignee(tenant_id=tenant.ctx.tenant_id, todo_id=todo, user_id=alice.id, assigned_by=user.id))
            session.commit()
        counts = make_cleaner().run().app_tenants[0]
        check.equal((counts.users, counts.skipped_users), (0, 1))


class TestKeycloakFailure:
    """Keycloak の削除が失敗したら、AP の行は変更しない(ロールバック)。"""

    def test_failure_rolls_back_ap_and_is_recorded(self, make_cleaner, world, idp):
        """Keycloak のユーザー削除が 500 で失敗したら、そのテナントの AP の行は 1 件も削除されず、失敗として記録される(エラー詳細は含めない)。"""
        tenant = world.tenant
        before = tenant.remaining()
        idp.fail("DELETE", r"/users/[^/]+$", 500, times=1)
        result = make_cleaner().run()
        check.equal(result.app_tenants, [])
        check.equal(result.failures, [CleanupFailure(scope="app", tenant_code=tenant.code, error="KeycloakAdminError; http_status=500")])
        check.is_false(result.ok)
        check.equal(tenant.remaining(), before)

    def test_next_run_converges(self, make_cleaner, world, idp):
        """失敗の後の再実行で、全て削除されて収束する(Keycloak 側の一部が削除済みでも、AP の行は削除される)。"""
        tenant = world.tenant
        idp.fail("DELETE", r"/users/[^/]+$", 500, times=1)
        make_cleaner().run()
        retry = make_cleaner().run()
        check.equal((retry.ok, retry.failures), (True, []))
        remaining = tenant.remaining()
        check.equal((remaining["users"], remaining["orgs"], remaining["todos"]), ({"alice@example.com", NEAR_EMAIL}, {DEFAULT_ORGANIZATION_NAME, "営業部", NEAR_ORG}, {NEAR_TODO, "買い物"}))

    def test_search_failure_is_recorded(self, make_cleaner, world, idp):
        """ユーザー検索に失敗したテナントも失敗として記録する(AP は変更しない)。"""
        tenant = world.tenant
        before = tenant.remaining()
        idp.fail("GET", r"/users$", 503, times=1)
        result = make_cleaner().run()
        check.equal([(f.scope, f.tenant_code) for f in result.failures], [("app", tenant.code)])
        check.equal(tenant.remaining(), before)

    def test_dry_run_failure_does_not_change_anything(self, make_cleaner, world, idp):
        """dry_run は Keycloak のユーザーを削除しない(削除の API を呼ばない)。"""
        idp.fail("DELETE", r"/users/[^/]+$", 500)
        result = make_cleaner().run(dry_run=True)
        check.equal(result.failures, [])
        check.equal(idp.deleted, [])


class TestScanRange:
    """AP 側の走査対象は、シードのテナント(alpha / beta)のうち ACTIVE なものだけ。"""

    def test_ordinary_tenant_is_not_scanned(self, make_cleaner, cp_db, ap_db, idp, calls):
        """シードでない ACTIVE のテナント(使い捨てのテナントを含む)は、E2E の命名のデータがあっても走査しない(AP にも Keycloak にも触れない)。"""
        tenant_id = cp_db.insert_tenant(status="ACTIVE")
        code = cp_db.tenant(tenant_id)["tenant_code"]
        ap_db.track(tenant_id)
        seed = ApSeed(ap_db, idp, TenantContext(tenant_id=tenant_id, tenant_code=code, plane="app"), code)
        seed.user(U_EMAIL)
        seed.org(ORG_NAME)
        before = seed.remaining()
        result = make_cleaner().run()
        check.equal(result.app_tenants, [])
        check.equal((seed.remaining(), calls.tenant_user_admin), (before, []))

    @pytest.mark.parametrize("status", ["SUSPENDED", "PENDING_DELETION", "FAILED", "PROVISIONING"])
    def test_only_active_seed_tenants_are_scanned(self, make_cleaner, cp_db, ap_db, idp, scan_as_seed, calls, status):
        """走査対象のテナントでも、ACTIVE でなければ AP 側は走査しない(停止中のレルムに触れない)。"""
        tenant_id = cp_db.insert_tenant(status=status)
        code = cp_db.tenant(tenant_id)["tenant_code"]
        ap_db.track(tenant_id)
        scan_as_seed(code)
        seed = ApSeed(ap_db, idp, TenantContext(tenant_id=tenant_id, tenant_code=code, plane="app"), code)
        seed.user(U_EMAIL)
        before = seed.remaining()
        result = make_cleaner(scope={tenant_id}).run()
        check.equal((result.app_tenants, seed.remaining(), calls.tenant_user_admin), ([], before, []))

    def test_e2e_named_tenant_is_not_scanned_in_ap(self, make_cleaner, e2e_tenant, calls):
        """E2E の命名のテナントは CP で物理削除するだけで、AP 側の走査対象にならない。"""
        e2e_tenant("ACTIVE")
        result = make_cleaner().run()
        check.equal((result.app_tenants, calls.tenant_user_admin), ([], []))
        check.equal(result.tenants.deprovisioned, 1)


class TestCrossTenant:
    """走査する各テナントは、自分のデータだけを扱う(他テナントのデータに触れない・数えない)。"""

    def make_seed(self, cp_db, ap_db, idp, scan_as_seed):
        tenant_id = cp_db.insert_tenant(status="ACTIVE")
        code = cp_db.tenant(tenant_id)["tenant_code"]
        ap_db.track(tenant_id)
        scan_as_seed(code)
        return ApSeed(ap_db, idp, TenantContext(tenant_id=tenant_id, tenant_code=code, plane="app"), code)

    def test_each_tenant_only_its_own(self, make_cleaner, cp_db, ap_db, idp, scan_as_seed):
        """2 つのテナントに同名の E2E のデータがあっても、それぞれ自分のテナントの分だけを数えて削除する。テナントごとに Keycloak のレルムも別。"""
        a = self.make_seed(cp_db, ap_db, idp, scan_as_seed)
        b = self.make_seed(cp_db, ap_db, idp, scan_as_seed)
        a.user(U_EMAIL)
        a.org(ORG_NAME)
        b.user(U_EMAIL)
        b.org(ORG_NAME)
        b.todo(TODO_TITLE, b.user("alice@example.com").id)
        result = make_cleaner().run()
        by_code = {counts.tenant_code: counts for counts in result.app_tenants}
        check.equal(set(by_code), {a.code, b.code})
        check.equal((by_code[a.code].users, by_code[a.code].organizations, by_code[a.code].todos), (1, 1, 0))
        check.equal((by_code[b.code].users, by_code[b.code].organizations, by_code[b.code].todos), (1, 1, 1))
        check.equal((a.remaining()["users"], b.remaining()["users"]), (set(), {"alice@example.com"}))

    def test_unscanned_tenant_keeps_its_data(self, make_cleaner, cp_db, ap_db, idp, scan_as_seed):
        """走査対象でないテナントの同名のデータは、他のテナントを走査しても削除されない。"""
        scanned = self.make_seed(cp_db, ap_db, idp, scan_as_seed)
        other_id = cp_db.insert_tenant(status="ACTIVE")
        ap_db.track(other_id)
        other_code = cp_db.tenant(other_id)["tenant_code"]
        other = ApSeed(ap_db, idp, TenantContext(tenant_id=other_id, tenant_code=other_code, plane="app"), other_code)
        for seed in (scanned, other):
            seed.user(U_EMAIL)
            seed.org(ORG_NAME)
            seed.todo(TODO_TITLE, seed.user("alice@example.com").id)
        make_cleaner().run()
        check.equal((scanned.remaining()["orgs"], scanned.remaining()["todos"]), (set(), set()))
        check.equal((other.remaining()["orgs"], other.remaining()["todos"], U_EMAIL in other.remaining()["users"]), ({ORG_NAME}, {TODO_TITLE}, True))
