# -*- coding: utf-8 -*-
"""E2EDataCleaner の AP 側で、ToDo のコメント・チェックリスト項目(リビジョン 0004 で追加)を扱うことのテスト。

- 対象の ToDo(``E2E ToDo <8桁>``。論理削除済みを含む)のコメント(論理削除済みを含む)・項目は ToDo と一緒に物理削除される(外部キー違反にならない)
- 対象外の ToDo のコメント・項目は消さない
- E2E のユーザーが対象外の ToDo にコメント(投稿者)・項目(作成者・更新者・完了者)を残している場合は、ユーザーの削除をスキップする(AP も Keycloak も残る)
- dry_run の件数は実際の件数と同じ。再実行は何も削除しない

使い捨てテナント + ``TenantRealmIdp``(Keycloak のフェイク)。alpha / beta には触れない(``test_20_cleaner_app.py`` と同じ分離)。
"""
import pytest
import pytest_check as check
from sqlalchemy import text

from dev_cleanup.test_20_cleaner_app import ApSeed, SeedUser
from dev_tools.e2e_cleanup import AppTenantCleanupCounts
from modules.tenancy.context import TenantContext

U_EMAIL = "e2e-aaaa1111@example.com"
TODO_TITLE = "E2E ToDo eeee5555"
DELETED_TODO_TITLE = "E2E ToDo ffff6666"
ORDINARY = "買い物"


@pytest.fixture
def tenant(cp_db, ap_db, idp, scan_as_seed) -> ApSeed:
    """AP の走査対象にした使い捨てテナント(台帳に ACTIVE の ``zt-*``。``test_20_cleaner_app.py`` と同じ)。"""
    tenant_id = cp_db.insert_tenant(status="ACTIVE")
    code = cp_db.tenant(tenant_id)["tenant_code"]
    ap_db.track(tenant_id)
    scan_as_seed(code)
    return ApSeed(ap_db, idp, TenantContext(tenant_id=tenant_id, tenant_code=code, plane="app"), code)


@pytest.fixture
def alice(tenant: ApSeed) -> SeedUser:
    return tenant.user("alice@example.com")


def remaining_counts(tenant: ApSeed) -> dict[str, int]:
    return {
        "comments": len(tenant.ap_db.rows(tenant.ctx, "SELECT 1 FROM t_todo_comment")),
        "items": len(tenant.ap_db.rows(tenant.ctx, "SELECT 1 FROM t_todo_checklist_item")),
        "todos": len(tenant.ap_db.rows(tenant.ctx, "SELECT 1 FROM t_todo")),
        "activities": len(tenant.ap_db.rows(tenant.ctx, "SELECT 1 FROM t_todo_activity")),
    }


class TestTodoChildren:
    """対象の ToDo のコメント・項目は ToDo と一緒に消え、対象外の ToDo のものは残る。"""

    @pytest.fixture
    def data(self, tenant: ApSeed, alice: SeedUser):
        u = tenant.user(U_EMAIL)
        f, c = tenant.factory, tenant.ctx
        target = tenant.todo(TODO_TITLE, alice.id, assignees=[u.id])
        deleted_target = tenant.todo(DELETED_TODO_TITLE, alice.id, deleted=True)
        ordinary = tenant.todo(ORDINARY, alice.id, assignees=[alice.id])
        f.comment(c, target, alice.id)
        f.comment(c, target, u.id)
        f.comment(c, target, u.id, deleted=True)
        f.comment(c, deleted_target, alice.id)
        f.item(c, target, alice.id, position=0, done_by=u.id)
        f.item(c, target, u.id, position=1)
        f.item(c, deleted_target, alice.id, position=0)
        f.comment(c, ordinary, alice.id, body="keep me")
        f.item(c, ordinary, alice.id, title="keep item", done_by=alice.id)
        tenant.activity(target, u.id)
        return u, target, ordinary

    def test_children_of_target_todos_are_purged(self, make_cleaner, tenant, data):
        """対象の ToDo(論理削除済みを含む)のコメント 4 件・項目 3 件が物理削除され、対象外の ToDo のコメント・項目は残る。E2E のユーザーも(参照が全て消えるため)削除される。"""
        result = make_cleaner().run()
        check.equal(result.failures, [])
        counts = result.app_tenants[0]
        check.equal((counts.todos, counts.todo_comments, counts.todo_checklist_items, counts.users, counts.skipped_users), (2, 4, 3, 1, 0))
        remaining = remaining_counts(tenant)
        check.equal((remaining["comments"], remaining["items"], remaining["todos"]), (1, 1, 1))
        check.equal([r["body"] for r in tenant.ap_db.rows(tenant.ctx, "SELECT body FROM t_todo_comment")], ["keep me"])
        check.equal([r["title"] for r in tenant.ap_db.rows(tenant.ctx, "SELECT title FROM t_todo_checklist_item")], ["keep item"])

    def test_dry_run_counts_match_and_change_nothing(self, make_cleaner, tenant, data):
        """dry_run の件数(コメント・項目を含む)は実際の件数と同じで、dry_run では何も削除しない。"""
        before = remaining_counts(tenant)
        dry = make_cleaner().run(dry_run=True)
        check.equal(remaining_counts(tenant), before)
        real = make_cleaner().run()
        check.equal(dry.app_tenants, real.app_tenants)
        check.equal((real.app_tenants[0].todo_comments, real.app_tenants[0].todo_checklist_items), (4, 3))

    def test_idempotent(self, make_cleaner, tenant, data):
        """2 回目は何も削除しない(コメント・項目の件数も 0)。"""
        make_cleaner().run()
        second = make_cleaner().run()
        check.equal(second.app_tenants, [AppTenantCleanupCounts(tenant_code=tenant.code)])


class TestReferencedByKeptChildren:
    """E2E のユーザーが対象外の ToDo に残したコメント・項目から参照されているなら、ユーザーを削除せずスキップする。"""

    @pytest.fixture
    def ordinary(self, tenant: ApSeed, alice: SeedUser):
        return tenant.todo(ORDINARY, alice.id, assignees=[alice.id])

    @pytest.mark.parametrize("kind", ["comment_author", "item_created_by", "item_updated_by", "item_done_by"])
    def test_user_is_skipped_and_rows_are_kept(self, make_cleaner, tenant, alice, ordinary, idp, kind):
        """対象外の ToDo のコメントの投稿者・項目の作成者・更新者・完了者の E2E ユーザーは、削除せずスキップする(AP も Keycloak も残り、他のユーザーは削除する)。"""
        blocked = tenant.user(U_EMAIL)
        free = tenant.user("e2e-gggg7777@example.com")
        f, c = tenant.factory, tenant.ctx
        if kind == "comment_author":
            f.comment(c, ordinary, blocked.id, body="by e2e")
        elif kind == "item_created_by":
            f.item(c, ordinary, blocked.id)
        elif kind == "item_updated_by":
            f.item(c, ordinary, alice.id)
            with tenant.ap_db.session(c) as session:
                session.execute(text("UPDATE t_todo_checklist_item SET updated_by = :u WHERE todo_id = :t"), {"u": blocked.id, "t": ordinary})
                session.commit()
        else:
            f.item(c, ordinary, alice.id, done_by=blocked.id)
        result = make_cleaner().run()
        counts = result.app_tenants[0]
        check.equal((counts.users, counts.skipped_users, counts.keycloak_users), (1, 1, 1))
        check.equal(tenant.remaining()["users"], {U_EMAIL, "alice@example.com"})
        check.is_in(U_EMAIL, tenant.remaining()["kc"])
        check.is_not_in(free.email, tenant.remaining()["kc"])
        check.equal(remaining_counts(tenant)["comments"] + remaining_counts(tenant)["items"], 1, "対象外の ToDo の行は消さない")
        check.is_true(result.ok)

    def test_skip_is_stable_across_runs(self, make_cleaner, tenant, ordinary):
        """スキップは dry_run でも実行でも、何度実行しても同じ(コメントが残る限りユーザーも残る)。"""
        blocked = tenant.user(U_EMAIL)
        tenant.factory.comment(tenant.ctx, ordinary, blocked.id)
        counts = [make_cleaner().run(dry_run=True).app_tenants[0].skipped_users, make_cleaner().run().app_tenants[0].skipped_users, make_cleaner().run().app_tenants[0].skipped_users]
        check.equal(counts, [1, 1, 1])

    def test_comment_on_target_todo_does_not_block(self, make_cleaner, tenant, alice):
        """E2E のユーザーのコメント・項目が対象の ToDo にだけあるなら、止めずに(ToDo と一緒に消して)ユーザーも削除する。"""
        u = tenant.user(U_EMAIL)
        target = tenant.todo(TODO_TITLE, alice.id)
        tenant.factory.comment(tenant.ctx, target, u.id)
        tenant.factory.item(tenant.ctx, target, u.id, done_by=u.id)
        counts = make_cleaner().run().app_tenants[0]
        check.equal((counts.users, counts.skipped_users, counts.todo_comments, counts.todo_checklist_items), (1, 0, 1, 1))
        check.equal(remaining_counts(tenant)["comments"] + remaining_counts(tenant)["items"], 0)

    def test_non_e2e_users_comments_never_block_or_vanish(self, make_cleaner, tenant, alice, ordinary):
        """通常のユーザー(E2E の命名でない)のコメント・項目は、そのまま残る(件数 0 の削除)。"""
        tenant.factory.comment(tenant.ctx, ordinary, alice.id)
        tenant.factory.item(tenant.ctx, ordinary, alice.id)
        counts = make_cleaner().run().app_tenants
        check.equal(counts, [AppTenantCleanupCounts(tenant_code=tenant.code)])
        check.equal((remaining_counts(tenant)["comments"], remaining_counts(tenant)["items"]), (1, 1))
