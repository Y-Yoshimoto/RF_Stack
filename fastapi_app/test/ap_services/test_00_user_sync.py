# -*- coding: utf-8 -*-
"""main_app.services.user_sync(ログイン時のユーザー同期・デフォルト組織・各リクエストの有効確認)のテスト。

開発 DB の ``app_db`` に、使い捨てのテナント(ランダムな UUID)を作って確認する。alpha / beta のデータには触れない。
終了時に、``app_cp_agent`` で監査ログを含めて削除する(``ap_db`` フィクスチャ)。
"""
import datetime as dt
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import pytest_check as check

from main_app.services.errors import UserDeactivatedError, UserNotSyncedError
from main_app.services.user_sync import DEFAULT_ORGANIZATION_NAME, TenantContextMismatchError, require_active_session_user, sync_user_on_login
from modules.tenancy.context import TenantContextMissingError, get_tenant_context


def login(ap_db, ctx, sub, *, email="alice@example.com", name="Alice Liddell"):
    """ログイン同期を 1 回行う(コミットされる)。"""
    with ap_db.session(ctx) as session:
        return sync_user_on_login(session, tenant_id=ctx.tenant_id, idp_subject=sub, email=email, display_name=name)


class TestCreateUser:
    """初回ログインでユーザー行を作る(PF-USR-04 / 05)。"""

    def test_first_login_creates_user_with_audit(self, ap_db):
        """行が無ければ作成する(version=1、有効、created_by=NULL、last_login_at 設定)。監査ログ user.create(source=login)を同じトランザクションで残す。"""
        ctx = ap_db.tenant()
        before = dt.datetime.now(dt.UTC)
        result = login(ap_db, ctx, "sub-1")
        check.is_true(result.created)
        check.is_false(result.profile_updated)
        check.is_false(result.email_conflict)
        row = ap_db.user(ctx, result.user_id)
        check.equal((row["idp_subject"], row["email"], row["display_name"], row["is_active"], row["version"]), ("sub-1", "alice@example.com", "Alice Liddell", True, 1))
        check.is_none(row["created_by"])
        check.is_none(row["updated_by"])
        check.greater_equal(row["last_login_at"], before)
        audit = ap_db.audits(ctx, "user.create")
        check.equal(len(audit), 1)
        check.equal((audit[0]["target_type"], audit[0]["target_id"], audit[0]["actor_id"]), ("user", str(result.user_id), None))
        check.equal(audit[0]["payload"], {"source": "login", "email": "alice@example.com", "display_name": "Alice Liddell"})
        check.equal(audit[0]["tenant_id"], ctx.tenant_id)

    @pytest.mark.parametrize(
        ("email", "name", "expected_email", "expected_name"),
        [
            ("  Bob@Example.com  ", "  Bob  ", "Bob@Example.com", "Bob"),
            ("bob@example.com", "   ", "bob@example.com", "bob@example.com"),
            ("bob@example.com", None, "bob@example.com", "bob@example.com"),
            (None, None, None, "sub-x"),
            ("   ", "", None, "sub-x"),
        ],
        ids=["trimmed", "blank-name-uses-email", "no-name-uses-email", "nothing-uses-sub", "blank-email"],
    )
    def test_input_normalization(self, ap_db, email, name, expected_email, expected_name):
        """メール・表示名は前後の空白を除く。表示名が空ならメール → sub の順で代用し、メールが空なら NULL にする(大文字小文字は IdP の値のまま)。"""
        ctx = ap_db.tenant()
        result = login(ap_db, ctx, "sub-x", email=email, name=name)
        row = ap_db.user(ctx, result.user_id)
        check.equal((row["email"], row["display_name"]), (expected_email, expected_name))

    def test_empty_subject_is_rejected(self, ap_db):
        """idp_subject が空なら ValueError で、何も作らない。"""
        ctx = ap_db.tenant()
        with pytest.raises(ValueError):
            login(ap_db, ctx, "")
        check.equal(ap_db.users(ctx), [])
        check.equal(ap_db.orgs(ctx), [])


class TestExistingUser:
    """既存のユーザーのプロフィール同期と最終ログイン日時。"""

    def test_login_only_updates_last_login_without_version_bump(self, ap_db):
        """プロフィールが変わらない再ログインでは last_login_at だけが進み、version は上がらず、user.sync の監査ログも残さない。"""
        ctx = ap_db.tenant()
        first = login(ap_db, ctx, "sub-1")
        before = ap_db.user(ctx, first.user_id)
        second = login(ap_db, ctx, "sub-1")
        after = ap_db.user(ctx, first.user_id)
        check.equal((second.user_id, second.created, second.profile_updated, second.email_conflict), (first.user_id, False, False, False))
        check.greater(after["last_login_at"], before["last_login_at"])
        check.equal(after["version"], 1)
        check.equal((after["display_name"], after["email"]), (before["display_name"], before["email"]))
        check.equal(ap_db.audits(ctx, "user.sync"), [])
        check.equal(len(ap_db.users(ctx)), 1)

    def test_profile_change_is_synced_with_version_bump_and_audit(self, ap_db):
        """表示名・メールが IdP で変わっていれば同期し、version を +1、updated_by=NULL、監査ログ user.sync に差分を残す。"""
        ctx = ap_db.tenant()
        first = login(ap_db, ctx, "sub-1")
        result = login(ap_db, ctx, "sub-1", email="alice2@example.com", name="Alice L.")
        row = ap_db.user(ctx, first.user_id)
        check.is_true(result.profile_updated)
        check.equal((row["display_name"], row["email"], row["version"]), ("Alice L.", "alice2@example.com", 2))
        audit = ap_db.audits(ctx, "user.sync")
        check.equal(len(audit), 1)
        check.equal(audit[0]["payload"]["changes"], {"display_name": {"before": "Alice Liddell", "after": "Alice L."}, "email": {"before": "alice@example.com", "after": "alice2@example.com"}})
        check.equal(audit[0]["payload"]["version"], {"before": 1, "after": 2})
        check.equal(audit[0]["payload"]["source"], "login")

    def test_only_display_name_changed(self, ap_db):
        """表示名だけが変わった場合は、メールを変えずに表示名だけ更新して version を +1 する。"""
        ctx = ap_db.tenant()
        first = login(ap_db, ctx, "sub-1")
        login(ap_db, ctx, "sub-1", name="Renamed")
        row = ap_db.user(ctx, first.user_id)
        check.equal((row["display_name"], row["email"], row["version"]), ("Renamed", "alice@example.com", 2))
        check.equal(list(ap_db.audits(ctx, "user.sync")[0]["payload"]["changes"]), ["display_name"])

    def test_same_subject_in_other_tenant_is_a_different_user(self, ap_db):
        """同じ sub・メールでも、別テナントのログインは別のユーザー行を作る(テナントごとに独立。PF-USR-06)。"""
        a, b = ap_db.tenant(), ap_db.tenant()
        ra = login(ap_db, a, "sub-1")
        rb = login(ap_db, b, "sub-1")
        check.not_equal(ra.user_id, rb.user_id)
        check.equal([r["id"] for r in ap_db.users(a)], [ra.user_id])
        check.equal([r["id"] for r in ap_db.users(b)], [rb.user_id])
        check.equal(ap_db.audits(a, "user.create")[0]["target_id"], str(ra.user_id))


class TestMissingEmailClaim:
    """トークンにメールアドレスが無いログイン(要判断: 仕様に記載が無い)。"""

    def test_missing_email_claim_keeps_stored_email(self, ap_db):
        """メールのクレームが無い(None)ログインでは、保存済みのメールアドレスを消さず、version も上げない。"""
        ctx = ap_db.tenant()
        first = login(ap_db, ctx, "sub-1", email="alice@example.com")
        login(ap_db, ctx, "sub-1", email=None)
        row = ap_db.user(ctx, first.user_id)
        check.equal((row["email"], row["version"]), ("alice@example.com", 1))


class TestEmailConflict:
    """メールアドレスがテナント内の別のユーザー行で使われている場合(ログインは止めない)。"""

    def test_new_user_with_conflicting_email_is_created_without_email(self, ap_db):
        """初回ログインのメールが別の行(大文字小文字違いを含む)で使われていれば、メール無しで作成し email_conflict=True。"""
        ctx = ap_db.tenant()
        ap_db.add_user(ctx, sub="old-sub", email="Shared@Example.com", display_name="Old")
        result = login(ap_db, ctx, "new-sub", email="shared@example.com", name="New")
        row = ap_db.user(ctx, result.user_id)
        check.is_true(result.created)
        check.is_true(result.email_conflict)
        check.is_none(row["email"])
        check.equal(row["display_name"], "New")
        check.equal(ap_db.audits(ctx, "user.create")[0]["payload"]["email"], None)

    def test_existing_user_keeps_email_but_other_fields_are_synced(self, ap_db):
        """既存ユーザーのメールが別の行と衝突する場合、メールは同期せず email_conflict=True。表示名は同期する。"""
        ctx = ap_db.tenant()
        other = ap_db.add_user(ctx, sub="other", email="taken@example.com")
        mine = login(ap_db, ctx, "sub-1", email="mine@example.com", name="Mine")
        result = login(ap_db, ctx, "sub-1", email="TAKEN@example.com", name="Mine 2")
        row = ap_db.user(ctx, mine.user_id)
        check.is_true(result.email_conflict)
        check.is_true(result.profile_updated)
        check.equal((row["email"], row["display_name"], row["version"]), ("mine@example.com", "Mine 2", 2))
        check.equal(ap_db.user(ctx, other.id)["email"], "taken@example.com")

    def test_conflict_only_does_not_touch_version(self, ap_db):
        """メールの衝突だけで他に変更が無ければ、version を変えず user.sync も残さない(last_login_at だけ更新)。"""
        ctx = ap_db.tenant()
        ap_db.add_user(ctx, sub="other", email="taken@example.com")
        mine = login(ap_db, ctx, "sub-1", email="mine@example.com")
        result = login(ap_db, ctx, "sub-1", email="taken@example.com")
        check.equal((result.email_conflict, result.profile_updated), (True, False))
        check.equal(ap_db.user(ctx, mine.user_id)["version"], 1)
        check.equal(ap_db.audits(ctx, "user.sync"), [])

    def test_same_email_in_other_tenant_is_not_a_conflict(self, ap_db):
        """別テナントで同じメールが使われていても衝突しない(RLS によりそのテナントの行だけを見る)。"""
        a, b = ap_db.tenant(), ap_db.tenant()
        ap_db.add_user(a, sub="a-sub", email="alice@example.com")
        result = login(ap_db, b, "b-sub", email="alice@example.com")
        check.is_false(result.email_conflict)
        check.equal(ap_db.user(b, result.user_id)["email"], "alice@example.com")


class TestDeactivatedUser:
    """無効化されたユーザーのログインは拒否し、何も変更しない(PF-USR-03)。"""

    def test_login_is_rejected_and_nothing_changes(self, ap_db):
        """UserDeactivatedError。last_login_at・version・プロフィールは変わらず、監査ログも増えず、デフォルト組織も作らない(ロールバック)。"""
        ctx = ap_db.tenant()
        user = ap_db.add_user(ctx, sub="sub-1", email="old@example.com", display_name="Old", is_active=False)
        with pytest.raises(UserDeactivatedError) as caught:
            login(ap_db, ctx, "sub-1", email="new@example.com", name="New")
        check.equal(caught.value.user_id, user.id)
        row = ap_db.user(ctx, user.id)
        check.equal((row["email"], row["display_name"], row["version"], row["is_active"]), ("old@example.com", "Old", 1, False))
        check.is_none(row["last_login_at"])
        check.equal(ap_db.audits(ctx), [])
        check.equal(ap_db.orgs(ctx), [])

    def test_reactivated_user_can_login(self, ap_db):
        """有効に戻したユーザーはログインできる。"""
        ctx = ap_db.tenant()
        user = ap_db.add_user(ctx, sub="sub-1", is_active=True)
        result = login(ap_db, ctx, "sub-1")
        check.equal(result.user_id, user.id)


class TestTenantContext:
    """テナントコンテキストの検証(呼び出し側の誤りは送出し、データを作らない)。"""

    def test_mismatching_tenant_id_is_rejected(self, ap_db):
        """引数の tenant_id がコンテキストと違えば TenantContextMismatchError。ユーザーも組織も作らない。"""
        ctx, other = ap_db.tenant(), ap_db.tenant()
        with ap_db.session(ctx) as session, pytest.raises(TenantContextMismatchError):
            sync_user_on_login(session, tenant_id=other.tenant_id, idp_subject="sub-1", email="a@example.com", display_name="A")
        for tenant in (ctx, other):
            check.equal(ap_db.users(tenant), [])
            check.equal(ap_db.orgs(tenant), [])

    def test_missing_context_is_rejected(self, ap_db):
        """コンテキストが無ければ TenantContextMissingError。"""
        ctx = ap_db.tenant()
        check.is_none(get_tenant_context())
        with ap_db.maker() as session, pytest.raises(TenantContextMissingError):
            sync_user_on_login(session, tenant_id=ctx.tenant_id, idp_subject="sub-1", email=None, display_name=None)


class TestDefaultOrganization:
    """デフォルト組織は「組織の行が 1 件も無い」ときだけ作る(PF-ORG-04、05 #31)。"""

    def test_created_on_first_login_of_empty_tenant(self, ap_db):
        """組織が無いテナントの初回ログインで 1 件作る(名前はデフォルト組織、作成者 NULL、監査ログ organization.create source=default)。"""
        ctx = ap_db.tenant()
        result = login(ap_db, ctx, "sub-1")
        orgs = ap_db.orgs(ctx)
        check.equal([o["id"] for o in orgs], [result.default_organization_id])
        check.equal((orgs[0]["name"], orgs[0]["version"], orgs[0]["created_by"], orgs[0]["deleted_at"]), (DEFAULT_ORGANIZATION_NAME, 1, None, None))
        audit = ap_db.audits(ctx, "organization.create")
        check.equal(len(audit), 1)
        check.equal(audit[0]["payload"], {"name": DEFAULT_ORGANIZATION_NAME, "source": "default"})

    def test_not_created_again_for_later_logins(self, ap_db):
        """2 回目以降のログイン・別ユーザーのログインでは作らない(default_organization_id は None)。"""
        ctx = ap_db.tenant()
        login(ap_db, ctx, "sub-1")
        again = login(ap_db, ctx, "sub-1")
        other = login(ap_db, ctx, "sub-2", email="b@example.com")
        check.is_none(again.default_organization_id)
        check.is_none(other.default_organization_id)
        check.equal(len(ap_db.orgs(ctx)), 1)

    def test_not_created_when_an_active_organization_exists(self, ap_db):
        """有効な組織が既にあれば作らない。"""
        ctx = ap_db.tenant()
        ap_db.add_org(ctx, "開発部")
        result = login(ap_db, ctx, "sub-1")
        check.is_none(result.default_organization_id)
        check.equal([o["name"] for o in ap_db.orgs(ctx)], ["開発部"])

    def test_not_recreated_when_every_organization_was_soft_deleted(self, ap_db):
        """論理削除済みの組織しか無くても作らない(管理者が全組織を削除した意思を尊重する)。"""
        ctx = ap_db.tenant()
        ap_db.add_org(ctx, DEFAULT_ORGANIZATION_NAME, deleted=True)
        result = login(ap_db, ctx, "sub-1")
        check.is_none(result.default_organization_id)
        check.equal(ap_db.orgs(ctx, include_deleted=False), [])
        check.equal(len(ap_db.orgs(ctx)), 1)

    def test_other_tenant_organizations_do_not_count(self, ap_db):
        """別テナントに組織があっても、このテナントに無ければ作る(RLS により他テナントの行は見えない)。"""
        a, b = ap_db.tenant(), ap_db.tenant()
        ap_db.add_org(a, "A の組織")
        result = login(ap_db, b, "sub-1")
        check.is_not_none(result.default_organization_id)
        check.equal([o["name"] for o in ap_db.orgs(a)], ["A の組織"])
        check.equal([o["tenant_id"] for o in ap_db.orgs(b)], [b.tenant_id])

    def test_failure_rolls_back_user_and_organization(self, ap_db, monkeypatch):
        """同期の途中(デフォルト組織の作成後)で失敗したら、ユーザー・組織・監査ログのすべてをロールバックする。"""
        ctx = ap_db.tenant()
        from main_app.services import user_sync

        def boom(session, ctx):
            raise RuntimeError("boom")

        monkeypatch.setattr(user_sync, "ensure_default_organization", boom)
        with pytest.raises(RuntimeError):
            login(ap_db, ctx, "sub-1")
        check.equal((ap_db.users(ctx), ap_db.orgs(ctx), ap_db.audits(ctx)), ([], [], []))


class TestConcurrency:
    """同時ログイン。どの順序で実行されても結果が同じになる(一意制約違反はセーブポイントで吸収する)。"""

    @staticmethod
    def run_parallel(ap_db, ctx, subjects):
        barrier = threading.Barrier(len(subjects))

        def one(sub):
            barrier.wait(timeout=10)
            return login(ap_db, ctx, sub, email=f"{sub}@example.com", name=sub)

        with ThreadPoolExecutor(max_workers=len(subjects)) as pool:
            return list(pool.map(one, subjects))

    def test_same_user_logging_in_concurrently_has_one_row(self, ap_db):
        """同じ sub が同時に初回ログインしても、ユーザー行は 1 件で、全員が同じユーザー ID を得る(作成したのは 1 つだけ)。デフォルト組織も 1 件。"""
        ctx = ap_db.tenant()
        results = self.run_parallel(ap_db, ctx, ["same-sub"] * 5)
        check.equal(len({r.user_id for r in results}), 1)
        check.equal(sum(1 for r in results if r.created), 1)
        check.equal(len(ap_db.users(ctx)), 1)
        check.equal(len(ap_db.orgs(ctx)), 1)
        check.equal(len(ap_db.audits(ctx, "user.create")), 1)
        check.equal(sum(1 for r in results if r.default_organization_id is not None), 1)

    def test_different_users_concurrently_create_one_default_organization(self, ap_db):
        """別々のユーザーが組織の無いテナントに同時にログインしても、デフォルト組織は 1 件だけ。全員のユーザー行が作られる。"""
        ctx = ap_db.tenant()
        results = self.run_parallel(ap_db, ctx, [f"sub-{i}" for i in range(6)])
        check.equal(len(ap_db.users(ctx)), 6)
        orgs = ap_db.orgs(ctx)
        check.equal(len(orgs), 1)
        check.equal(sum(1 for r in results if r.default_organization_id is not None), 1)
        check.equal(len(ap_db.audits(ctx, "organization.create")), 1)


class TestRequireActiveSessionUser:
    """各リクエストでのユーザーの有効確認(PF-USR-03 のセッション失効)。"""

    def test_returns_user_id_for_active_user(self, ap_db):
        """有効なユーザーは AP のユーザー ID(t_user.id)を返す。"""
        ctx = ap_db.tenant()
        user = ap_db.add_user(ctx, sub="sub-1")
        with ap_db.session(ctx) as session:
            check.equal(require_active_session_user(session, idp_subject="sub-1"), user.id)

    def test_deactivated_user_is_rejected_immediately(self, ap_db):
        """is_active=false のユーザーは UserDeactivatedError(user_id 付き)。キャッシュせず、更新の直後から拒否される。"""
        ctx = ap_db.tenant()
        user = ap_db.add_user(ctx, sub="sub-1")
        with ap_db.session(ctx) as session:
            check.equal(require_active_session_user(session, idp_subject="sub-1"), user.id)
            session.connection().exec_driver_sql("UPDATE t_user SET is_active = false WHERE id = %s", (user.id,))
            session.commit()
            with pytest.raises(UserDeactivatedError) as caught:
                require_active_session_user(session, idp_subject="sub-1")
        check.equal(caught.value.user_id, user.id)

    def test_unknown_subject_is_not_synced(self, ap_db):
        """ユーザー行が無い sub は UserNotSyncedError(再ログインで同期される)。"""
        ctx = ap_db.tenant()
        with ap_db.session(ctx) as session, pytest.raises(UserNotSyncedError):
            require_active_session_user(session, idp_subject="nobody")

    def test_other_tenant_user_is_not_visible(self, ap_db):
        """他テナントにだけ存在する sub は、このテナントでは UserNotSyncedError(他テナントの行は見えず、存在も判別できない)。"""
        a, b = ap_db.tenant(), ap_db.tenant()
        ap_db.add_user(b, sub="only-in-b")
        with ap_db.session(a) as session, pytest.raises(UserNotSyncedError):
            require_active_session_user(session, idp_subject="only-in-b")

    def test_does_not_write(self, ap_db):
        """確認は読み取りのみ(last_login_at・version を変えない)。"""
        ctx = ap_db.tenant()
        user = ap_db.add_user(ctx, sub="sub-1")
        with ap_db.session(ctx) as session:
            require_active_session_user(session, idp_subject="sub-1")
        row = ap_db.user(ctx, user.id)
        check.is_none(row["last_login_at"])
        check.equal(row["version"], 1)
        check.equal(ap_db.audits(ctx), [])


def test_user_ids_are_uuid7(ap_db):
    """ユーザー ID・組織 ID は UUIDv7(時系列順)。"""
    ctx = ap_db.tenant()
    result = login(ap_db, ctx, "sub-1")
    check.equal(result.user_id.version, 7)
    check.equal(result.default_organization_id.version, 7)
    check.is_instance(result.user_id, uuid.UUID)
