# -*- coding: utf-8 -*-
"""開発用の ToDo シード(``dev_tools.seed_todos``。ToDoApp.md §9.4)のテスト。

使い捨てのテナントとフェイクの Keycloak に対して ``seed_tenant_todos()`` を呼ぶ(``conftest.py``)。確認すること: 冪等(2 回実行して件数が変わらない)、
件数(alpha 20 件・beta 6 件)、組み合わせの網羅、``[Seed] `` 始まり、サービス経由で作られた(アクティビティ・監査ログが残る)、開発環境以外では拒否、
E2E の後片付けの対象外。
"""
import datetime as dt

import pytest
import pytest_check as check

from dev_tools import e2e_cleanup, seed_todos
from dev_tools.seed_todos import ALPHA_TODOS, BETA_TODOS, SEED_ORGANIZATIONS, SEED_PREFIX, SEED_TODOS
from main_app.services.todo_service import TodoService

from .conftest import TODAY


def expected_children(todos):
    """定義から数えた期待値: (項目の数, 完了の数, コメントの数)。"""
    return (sum(len(t.checklist) for t in todos), sum(1 for t in todos for _, done in t.checklist if done), sum(len(t.comments) for t in todos))


class TestFirstRun:
    """初回の実行。"""

    def test_creates_the_documented_numbers(self, seed_env):
        """alpha: ToDo 20 件・組織 2 件(1 件は論理削除)・ユーザー 3 人。コメント・項目の数は定義どおり。"""
        result = seed_env.run()
        items, done, comments = expected_children(ALPHA_TODOS)
        check.equal((len(ALPHA_TODOS), len(BETA_TODOS)), (20, 6))
        check.equal((len(result.todos_created), result.todos_existing, result.todos_skipped, result.users), (20, 0, [], 3))
        check.equal(result.organizations_created, [o.name for o in SEED_ORGANIZATIONS])
        check.equal(result.organizations_deleted, [o.name for o in SEED_ORGANIZATIONS if o.deleted])
        counts = seed_env.counts()
        check.equal((counts["t_todo"], counts["t_todo_comment"], counts["t_todo_checklist_item"], counts["t_user"]), (20, comments, items, 3))
        check.equal(len(seed_env.rows("SELECT 1 FROM t_todo_checklist_item WHERE is_done")), done)
        check.equal(len(seed_env.rows("SELECT 1 FROM t_organization WHERE name LIKE '[Seed] %' AND deleted_at IS NOT NULL")), 1)
        check.equal(len(seed_env.rows("SELECT 1 FROM t_organization WHERE name LIKE '[Seed] %' AND deleted_at IS NULL")), 1)

    def test_beta_numbers(self, beta_env):
        """beta: ToDo 6 件。"""
        result = beta_env.run()
        items, _, comments = expected_children(BETA_TODOS)
        check.equal(len(result.todos_created), 6)
        counts = beta_env.counts()
        check.equal((counts["t_todo"], counts["t_todo_comment"], counts["t_todo_checklist_item"]), (6, comments, items))

    def test_everything_starts_with_seed_prefix(self, seed_env):
        """作ったすべての ToDo のタイトルと組織名が ``[Seed] `` で始まる(デフォルト組織とユーザーを除く)。"""
        seed_env.run()
        check.is_true(all(r["title"].startswith(SEED_PREFIX) for r in seed_env.rows("SELECT title FROM t_todo")))
        names = [r["name"] for r in seed_env.rows("SELECT name FROM t_organization")]
        check.equal(sorted(n for n in names if n.startswith(SEED_PREFIX)), sorted(o.name for o in SEED_ORGANIZATIONS))
        check.equal(len(names), 3, "デフォルト組織 + シードの 2 組織")

    def test_users_synced_like_login(self, seed_env):
        """ユーザーはログインと同じ同期で確保される: IdP の sub・ロール・名前が入り、last_login_at が設定される。"""
        seed_env.run()
        users = {r["idp_subject"]: r for r in seed_env.rows("SELECT * FROM t_user")}
        idp_users = seed_env.idp_users()
        check.equal(set(users), {u.subject for u in idp_users.values()})
        check.is_in("tenant_admin", users[idp_users["admin"].subject]["roles"])
        check.equal(users[idp_users["member"].subject]["roles"], ["member"])
        check.is_true(all(u["last_login_at"] is not None and u["is_active"] for u in users.values()))

    def test_created_through_services_with_activities_and_audit(self, seed_env):
        """サービス経由で作られるため、アクティビティ(created / checklist_changed)と監査ログ(todo.create / comment_create / checklist_change)が残る。"""
        seed_env.run()
        items, done, comments = expected_children(ALPHA_TODOS)
        activities = [r["action"] for r in seed_env.rows("SELECT action FROM t_todo_activity")]
        check.equal(activities.count("created"), 20)
        check.equal(activities.count("checklist_changed"), items + done, "追加 + 完了")
        audits = [r["action"] for r in seed_env.rows("SELECT action FROM t_ap_audit_log")]
        check.equal((audits.count("todo.create"), audits.count("todo.comment_create"), audits.count("todo.checklist_change")), (20, comments, items + done))
        check.is_not_in("todo.delete", audits)

    def test_combinations_are_covered(self, seed_env):
        """網羅する組み合わせ: 閲覧範囲 4 種(公開先が全て削除済みの organization を含む)× 作成者 3 人 × 担当者 0/1/2 人、ステータス 3 種、期限(期限切れ・今日・数日後・なし)、チェックリスト(なし・一部・全完了)、コメントの有無。"""
        seed_env.run()
        users = {r["id"]: r["email"].split("@")[0] for r in seed_env.rows("SELECT id, email FROM t_user")}
        todos = seed_env.rows("SELECT * FROM t_todo")
        active_orgs = {r["id"] for r in seed_env.rows("SELECT id FROM t_organization WHERE deleted_at IS NULL")}
        links = seed_env.rows("SELECT todo_id, organization_id FROM t_todo_organization")
        effective = set()
        for todo in todos:
            if todo["visibility"] == "organization":
                valid = any(link["organization_id"] in active_orgs for link in links if link["todo_id"] == todo["id"])
                effective.add("organization(有効)" if valid else "organization(全て削除済み)")
            else:
                effective.add(todo["visibility"])
        check.equal(effective, {"private", "tenant", "organization(有効)", "organization(全て削除済み)"})
        check.equal({users[t["created_by"]] for t in todos}, {"alpha-admin", "alpha-member", "alpha-member2"})
        assignee_counts = {len(seed_env.rows("SELECT 1 FROM t_todo_assignee WHERE todo_id = :t", t=t["id"])) for t in todos}
        check.equal(assignee_counts, {0, 1, 2})
        check.equal({t["status"] for t in todos}, {"open", "in_progress", "done"})
        due = {None if t["due_date"] is None else (t["due_date"] - TODAY).days for t in todos}
        dated = {d for d in due if d is not None}
        check.is_true(None in due and 0 in dated and any(d < 0 for d in dated) and any(d > 0 for d in dated), due)
        progress = {tuple(seed_env.rows("SELECT count(*) AS n, count(*) FILTER (WHERE is_done) AS d FROM t_todo_checklist_item WHERE todo_id = :t", t=t["id"])[0].values()) for t in todos}
        check.is_true((0, 0) in progress and any(0 < d < n for n, d in progress) and any(n > 0 and n == d for n, d in progress), progress)
        with_comments = {len(seed_env.rows("SELECT 1 FROM t_todo_comment WHERE todo_id = :t", t=t["id"])) > 0 for t in todos}
        check.equal(with_comments, {True, False})

    def test_due_dates_are_relative_to_today(self, seed_env):
        """期限は実行日(today)からの日数で決まる。"""
        seed_env.run(today=TODAY)
        expected = sorted(None if t.due_in_days is None else TODAY + dt.timedelta(days=t.due_in_days) for t in ALPHA_TODOS if t.due_in_days is not None)
        got = sorted(r["due_date"] for r in seed_env.rows("SELECT due_date FROM t_todo WHERE due_date IS NOT NULL"))
        check.equal(got, expected)

    def test_dangling_visibility_is_private_in_effect(self, seed_env):
        """公開先がすべて削除済みの organization の ToDo は、有効な閲覧範囲が private(作成者と担当者だけが見える。AP-VIS-08)。"""
        seed_env.run()
        users = {r["email"].split("@")[0]: r for r in seed_env.rows("SELECT id, email FROM t_user")}
        legacy = next(t for t in ALPHA_TODOS if t.title.endswith("旧プロジェクトの資料整理"))
        todo_id = seed_env.rows("SELECT id FROM t_todo WHERE title = :t", t=legacy.title)[0]["id"]
        with seed_env.ap_db.session(seed_env.ctx) as session:
            member2 = users["alpha-member2"]["id"]
            from main_app.services.errors import TodoNotFoundError

            view = TodoService(session, actor_user_id=users["alpha-admin"]["id"], actor_roles=("tenant_admin",)).get_todo(todo_id)
            check.equal(view.effective_visibility.value, "private")
            with pytest.raises(TodoNotFoundError):
                TodoService(session, actor_user_id=member2, actor_roles=("member",)).get_todo(todo_id)


class TestIdempotent:
    """何度実行しても同じ状態に収束する。"""

    def test_second_run_changes_nothing(self, seed_env):
        """2 回実行しても件数が変わらない: 全テーブルの行数が同じで、2 回目の結果は作成 0・既存 20。ToDo の ID も変わらない。"""
        first = seed_env.run()
        before = seed_env.counts()
        ids = {r["id"] for r in seed_env.rows("SELECT id FROM t_todo")}
        second = seed_env.run()
        after = seed_env.counts()
        # ユーザー同期でログイン時の監査ログ(user.sync)が増える可能性があるため、監査ログ以外の全テーブルが同じであることを確認する
        before_without_audit = {k: v for k, v in before.items() if k != "t_ap_audit_log"}
        after_without_audit = {k: v for k, v in after.items() if k != "t_ap_audit_log"}
        check.equal(after_without_audit, before_without_audit)
        check.equal((len(first.todos_created), len(second.todos_created), second.todos_existing), (20, 0, 20))
        check.equal((second.organizations_created, second.organizations_deleted), ([], []))
        check.equal({r["id"] for r in seed_env.rows("SELECT id FROM t_todo")}, ids)

    def test_third_run_with_another_date_is_still_stable(self, seed_env):
        """別の日に実行しても(期限が変わる日付でも)重複して作らない(タイトルで判定)。"""
        seed_env.run(today=TODAY)
        before = seed_env.counts()["t_todo"]
        seed_env.run(today=TODAY + dt.timedelta(days=30))
        seed_env.run(today=TODAY + dt.timedelta(days=31))
        check.equal(seed_env.counts()["t_todo"], before)

    def test_deleted_seed_todo_is_recreated(self, seed_env):
        """論理削除した ToDo は「無い」とみなして作り直す(論理削除済みは既存に数えない)。再作成後は 20 件(生きているもの)。"""
        seed_env.run()
        first = ALPHA_TODOS[0]
        todo_id = seed_env.rows("SELECT id FROM t_todo WHERE title = :t", t=first.title)[0]["id"]
        admin = seed_env.rows("SELECT id FROM t_user WHERE email LIKE 'alpha-admin@%'")[0]["id"]
        with seed_env.ap_db.session(seed_env.ctx) as session:
            TodoService(session, actor_user_id=admin, actor_roles=("tenant_admin",)).delete_todo(todo_id, expected_version=1)
        result = seed_env.run()
        check.equal(result.todos_created, [first.title])
        check.equal(len(seed_env.rows("SELECT 1 FROM t_todo WHERE deleted_at IS NULL")), 20)

    def test_todo_for_deleted_organization_is_skipped_not_failed(self, seed_env):
        """公開先が削除済みの組織の ToDo を論理削除した後の再実行は、新たには作れない(AP-VIS-10)ためスキップして続行する(失敗しない)。"""
        seed_env.run()
        legacy = next(t for t in ALPHA_TODOS if t.organizations and t.organizations[0] == seed_todos.LEGACY)
        todo_id = seed_env.rows("SELECT id FROM t_todo WHERE title = :t", t=legacy.title)[0]["id"]
        admin = seed_env.rows("SELECT id FROM t_user WHERE email LIKE 'alpha-admin@%'")[0]["id"]
        with seed_env.ap_db.session(seed_env.ctx) as session:
            TodoService(session, actor_user_id=admin, actor_roles=("tenant_admin",)).delete_todo(todo_id, expected_version=1)
        result = seed_env.run()
        check.equal(result.todos_created, [])
        check.is_in(legacy.title, result.todos_skipped)

    def test_existing_user_data_is_not_duplicated(self, seed_env):
        """ユーザー・組織は何度でも同じ行を使う(重複して作らない)。"""
        seed_env.run()
        users = {r["id"] for r in seed_env.rows("SELECT id FROM t_user")}
        orgs = {r["id"] for r in seed_env.rows("SELECT id FROM t_organization")}
        seed_env.run()
        check.equal(({r["id"] for r in seed_env.rows("SELECT id FROM t_user")}, {r["id"] for r in seed_env.rows("SELECT id FROM t_organization")}), (users, orgs))

    def test_tenant_without_definitions_creates_no_todos(self, seed_env, monkeypatch):
        """ToDo の定義が無いテナントコードでは、ユーザーは確保するが ToDo は作らない。"""
        monkeypatch.setattr(seed_todos, "SEED_TODOS", {})
        result = seed_env.run()
        check.equal((result.todos_created, result.users, seed_env.counts()["t_todo"]), ([], 3, 0))


class TestEnvironmentGuard:
    """開発環境以外では拒否する。"""

    @pytest.mark.parametrize("env", ["production", "staging", "test", "", "dev"])
    def test_run_seed_todos_refuses_non_development(self, monkeypatch, env):
        """APP_ENV が development でない(production・未設定・空・dev など)と RuntimeError。台帳(CP)にも Keycloak にも触れない(セッションを渡さずに失敗する)。"""
        monkeypatch.setenv("APP_ENV", env)
        with pytest.raises(RuntimeError, match="APP_ENV=development"):
            seed_todos.run_seed_todos(None)

    def test_unset_app_env_is_refused(self, monkeypatch):
        """APP_ENV が未設定でも拒否する(明示が必要)。"""
        monkeypatch.delenv("APP_ENV", raising=False)
        with pytest.raises(RuntimeError):
            seed_todos.run_seed_todos(None)

    @pytest.mark.parametrize("env", ["production", "staging", ""])
    def test_cli_exits_with_2(self, monkeypatch, capsys, env):
        """CLI は開発環境以外では終了コード 2 を返し、標準エラーに理由を出す(DB・Keycloak には接続しない)。"""
        monkeypatch.setenv("APP_ENV", env)
        check.equal(seed_todos.main([]), 2)
        check.is_in("APP_ENV=development", capsys.readouterr().err)

    @pytest.mark.parametrize("env", ["development", "Development", " DEVELOPMENT "])
    def test_development_is_accepted_case_insensitively(self, monkeypatch, env):
        """development は大文字小文字・前後の空白を無視して受け付ける(ガードを通る)。"""
        monkeypatch.setenv("APP_ENV", env)
        from control_plane_app.seed import require_explicit_development

        require_explicit_development()


class TestFetchIdpUsers:
    """Keycloak(フェイク)からの引き当て。"""

    def test_reads_sub_names_and_effective_roles(self, seed_env):
        """シードのユーザーの sub・メール・姓・名・実効ロールを引く。管理者は tenant_admin、他は member。"""
        users = seed_env.idp_users()
        check.equal(set(users), {"admin", "member", "member2"})
        check.is_in("tenant_admin", users["admin"].roles)
        check.is_in("member", users["member"].roles)
        check.is_not_in("tenant_admin", users["member2"].roles)
        check.equal((users["admin"].first_name, users["admin"].last_name), ("Alpha", "Admin"))

    def test_missing_user_raises_with_guidance(self, seed_env):
        """Keycloak にシードのユーザーが無ければ RuntimeError(先にテナント・ユーザーのシードを実行するよう案内する)。"""
        realm = seed_env.idp.users(seed_env.tenant.realm_name)
        victim = next(uid for uid, u in realm.items() if u["username"] == "alpha-member2")
        realm.pop(victim)
        with pytest.raises(RuntimeError, match="control_plane_app.seed"):
            seed_env.idp_users()


class TestNotTargetOfE2ECleanup:
    """E2E の後片付けの対象にならない。"""

    def test_names_do_not_match_e2e_patterns(self):
        """シードのタイトル・組織名は E2E の命名(``E2E ToDo <8桁>`` / ``E2E Org <8桁>``)に一致しない。ユーザーのメールも E2E の命名でない。"""
        titles = [t.title for todos in SEED_TODOS.values() for t in todos]
        check.is_false(any(e2e_cleanup.is_e2e_todo_title(title) for title in titles))
        check.is_false(any(e2e_cleanup.is_e2e_organization_name(o.name) for o in SEED_ORGANIZATIONS))
        from modules.auth.dev_profiles import DEV_TENANT_USERS

        check.is_false(any(e2e_cleanup.is_e2e_user(u.email, u.username) for users in DEV_TENANT_USERS.values() for u in users))

    def test_titles_are_unique_per_tenant(self):
        """冪等の判定がタイトルなので、テナントごとにタイトルが重複していない。"""
        for code, todos in SEED_TODOS.items():
            titles = [t.title for t in todos]
            check.equal(len(titles), len(set(titles)), code)
            check.is_true(all(title.startswith(SEED_PREFIX) for title in titles), code)

    def test_e2e_cleanup_finds_no_targets_in_seeded_tenant(self, seed_env):
        """シード済みのテナントで E2E の後片付けの対象探索(``_find_app_targets``)を実行すると、ユーザー・組織・ToDo とも対象が 0 件(スキップされるユーザーも無い)。"""
        from modules.tenancy.db import apply_tenant_guc

        seed_env.run()
        with seed_env.ap_db.agent.connect() as connection:
            apply_tenant_guc(connection, seed_env.ctx.tenant_id)
            targets = e2e_cleanup._find_app_targets(connection, seed_env.ctx.tenant_id)
            connection.rollback()
        check.equal((targets.user_ids, targets.organization_ids, targets.todo_ids, targets.skipped_user_ids), (set(), set(), set(), set()))
