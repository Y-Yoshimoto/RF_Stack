# -*- coding: utf-8 -*-
"""main_app.services.organization_service(組織管理。PF-ORG-01..03)のテスト。

DB は開発 DB の ``app_db``。使い捨てのテナントを作り、終了時に監査ログを含めて削除する(``ap_db``)。alpha / beta には触れない。
"""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest
import pytest_check as check
from sqlalchemy.exc import DBAPIError, IntegrityError

from main_app.models import TOrganizationMember
from main_app.repositories import users as user_repo
from main_app.services.errors import (
    InvalidOrganizationMembersError,
    OrganizationNameConflictError,
    OrganizationNotFoundError,
    OrganizationValidationError,
    OrganizationVersionConflictError,
)
from main_app.services.organization_service import MAX_ORGANIZATION_MEMBERS, ORGANIZATION_NAME_MAX_LENGTH, OrganizationService
from modules.tenancy.context import TenantContext


@dataclass
class Env:
    ctx: TenantContext
    actor: object  # 操作者の t_user


@pytest.fixture
def env(ap_db) -> Env:
    """使い捨てのテナントと、操作者のユーザー行。"""
    ctx = ap_db.tenant()
    return Env(ctx=ctx, actor=ap_db.add_user(ctx, sub=str(uuid.uuid4()), email="admin@example.com", display_name="Admin"))


@pytest.fixture
def run(ap_db, env):
    """``run(lambda service: ...)`` でセッション・サービスを作って呼ぶ(コンテキストと操作者を変えられる)。"""

    def call(func, *, ctx=None, actor_sub=None):
        target = ctx or env.ctx
        with ap_db.session(target) as session:
            return func(OrganizationService(session, actor_subject=actor_sub if actor_sub is not None else env.actor.idp_subject))

    return call


class TestCreate:
    """組織の作成。"""

    def test_creates_with_audit(self, run, ap_db, env):
        """組織を作る(version=1、作成者=操作者、未削除)。監査ログ organization.create(source=admin)を同じトランザクションで残す。"""
        view = run(lambda s: s.create_organization(name="  開発部  "))
        check.equal((view.name, view.version), ("開発部", 1))
        row = ap_db.orgs(env.ctx)[0]
        check.equal((row["id"], row["name"], row["created_by"], row["updated_by"], row["deleted_at"], row["tenant_id"]), (view.id, "開発部", env.actor.id, env.actor.id, None, env.ctx.tenant_id))
        audit = ap_db.audits(env.ctx, "organization.create")
        check.equal(len(audit), 1)
        check.equal((audit[0]["actor_id"], audit[0]["target_type"], audit[0]["target_id"], audit[0]["payload"]), (env.actor.id, "organization", str(view.id), {"name": "開発部", "source": "admin"}))

    @pytest.mark.parametrize(
        ("name", "reason"),
        [("", "required"), ("   ", "required"), ("x" * (ORGANIZATION_NAME_MAX_LENGTH + 1), "too_long"), ("a\nb", "format"), ("a\x00b", "format"), (None, "required"), (123, "required")],
    )
    def test_invalid_name(self, run, ap_db, env, name, reason):
        """空・長すぎる・制御文字を含む名前は OrganizationValidationError(field=name)で、何も作らない。"""
        with pytest.raises(OrganizationValidationError) as caught:
            run(lambda s: s.create_organization(name=name))
        check.equal((caught.value.field, caught.value.reason), ("name", reason))
        check.equal((ap_db.orgs(env.ctx), ap_db.audits(env.ctx, "organization.create")), ([], []))

    def test_max_length_name_is_accepted(self, run):
        """上限ちょうどの長さの名前は作れる。"""
        view = run(lambda s: s.create_organization(name="x" * ORGANIZATION_NAME_MAX_LENGTH))
        check.equal(len(view.name), ORGANIZATION_NAME_MAX_LENGTH)

    @pytest.mark.parametrize("second", ["開発部", "  開発部 ", "ENG", "eng", "Eng"])
    def test_duplicate_active_name_is_conflict_case_insensitive(self, run, ap_db, env, second):
        """有効な組織と同じ名前(前後の空白・大文字小文字を除いて同じ)は OrganizationNameConflictError。2 件目は作らない。"""
        first = "ENG" if second.lower() == "eng" else "開発部"
        run(lambda s: s.create_organization(name=first))
        with pytest.raises(OrganizationNameConflictError) as caught:
            run(lambda s: s.create_organization(name=second))
        check.equal(caught.value.code, "organization_name_already_exists")
        check.equal(len(ap_db.orgs(env.ctx)), 1)
        check.equal(len(ap_db.audits(env.ctx, "organization.create")), 1)

    def test_same_name_in_other_tenant_is_allowed(self, run, ap_db, env):
        """別テナントの同名の組織は重複にならない。"""
        other = ap_db.tenant()
        run(lambda s: s.create_organization(name="開発部"))
        run(lambda s: s.create_organization(name="開発部"), ctx=other)
        check.equal(len(ap_db.orgs(other)), 1)

    def test_name_of_deleted_organization_can_be_reused(self, run, ap_db, env):
        """論理削除した組織の名前は再利用できる(一意性は有効な組織の中だけ)。"""
        first = run(lambda s: s.create_organization(name="開発部"))
        run(lambda s: s.delete_organization(first.id, expected_version=first.version))
        second = run(lambda s: s.create_organization(name="開発部"))
        check.not_equal(first.id, second.id)
        orgs = ap_db.orgs(env.ctx)
        check.equal(sorted((o["name"], o["deleted_at"] is not None) for o in orgs), [("開発部", False), ("開発部", True)])

    def test_concurrent_creates_of_same_name_produce_one(self, ap_db, env):
        """同じ名前の同時作成は、一意制約を 409 に変換して片方だけが成功する(重複を作らない)。"""
        barrier = threading.Barrier(2)

        def attempt(_):
            barrier.wait(timeout=10)
            with ap_db.session(env.ctx) as session:
                try:
                    OrganizationService(session, actor_subject=env.actor.idp_subject).create_organization(name="同時")
                except OrganizationNameConflictError:
                    return "conflict"
                return "ok"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(attempt, range(2)))
        check.equal(outcomes, ["conflict", "ok"])
        check.equal(len(ap_db.orgs(env.ctx)), 1)


class TestGetAndList:
    """参照。論理削除済み・他テナントの組織は見えない。"""

    def test_get_and_members(self, run, ap_db, env):
        """組織を ID で取得でき、メンバーの ID は ID 順に返る。"""
        u1, u2 = ap_db.add_user(env.ctx), ap_db.add_user(env.ctx)
        org = ap_db.add_org(env.ctx, "開発部", members=(u2.id, u1.id))
        view = run(lambda s: s.get_organization(org.id))
        check.equal((view.id, view.name, view.version), (org.id, "開発部", 1))
        check.equal(run(lambda s: s.list_member_ids(org.id)), sorted([u1.id, u2.id]))

    def test_unknown_deleted_and_other_tenant_are_all_not_found(self, run, ap_db, env):
        """存在しない ID・論理削除済み・他テナントの組織は、すべて同じ OrganizationNotFoundError(参照・メンバー参照とも)。"""
        other = ap_db.tenant()
        deleted = ap_db.add_org(env.ctx, "削除済み", deleted=True)
        foreign = ap_db.add_org(other, "他社の組織")
        for organization_id in (uuid.uuid4(), deleted.id, foreign.id):
            with pytest.raises(OrganizationNotFoundError) as caught:
                run(lambda s, organization_id=organization_id: s.get_organization(organization_id))
            check.equal(caught.value.organization_id, organization_id)
            with pytest.raises(OrganizationNotFoundError):
                run(lambda s, organization_id=organization_id: s.list_member_ids(organization_id))

    def test_list_excludes_deleted_and_other_tenant(self, run, ap_db, env):
        """一覧には有効な自テナントの組織だけが並ぶ(論理削除済み・他テナントは含まれず、件数にも現れない)。"""
        other = ap_db.tenant()
        ap_db.add_org(env.ctx, "b")
        ap_db.add_org(env.ctx, "a")
        ap_db.add_org(env.ctx, "gone", deleted=True)
        ap_db.add_org(other, "x")
        ap_db.add_org(other, "y")
        check.equal([o.name for o in run(lambda s: s.list_organizations()).items], ["a", "b"])
        check.equal([o.name for o in run(lambda s: s.list_organizations(sort="-name")).items], ["b", "a"])
        check.equal([o.name for o in run(lambda s: s.list_organizations(), ctx=other).items], ["x", "y"])

    def test_pagination_has_no_gaps_or_duplicates(self, run, ap_db, env):
        """limit と after で、同じ並び替えキー(作成日時が同じでも id で安定)を重複・欠落なく辿れる。"""
        for i in range(5):
            ap_db.add_org(env.ctx, f"org-{i}")
        collected, after, pages = [], None, 0
        for _ in range(10):
            page = run(lambda s, after=after: s.list_organizations(limit=2, sort="created_at", after=after))
            collected.extend(o.name for o in page.items)
            pages += 1
            after = page.next_after
            if after is None:
                break
        check.equal(collected, [f"org-{i}" for i in range(5)])
        check.equal(pages, 3)

    def test_invalid_sort(self, run):
        """許可していない並び替えキーは OrganizationValidationError(field=sort)。"""
        with pytest.raises(OrganizationValidationError) as caught:
            run(lambda s: s.list_organizations(sort="version"))
        check.equal((caught.value.field, caught.value.reason), ("sort", "unsupported"))


class TestUpdate:
    """組織名の変更。"""

    def test_rename(self, run, ap_db, env):
        """名前を変えると version +1、updated_by=操作者、監査ログ organization.update に差分が残る。"""
        org = ap_db.add_org(env.ctx, "旧名")
        view = run(lambda s: s.update_organization(org.id, expected_version=1, name=" 新名 "))
        check.equal((view.name, view.version), ("新名", 2))
        row = ap_db.orgs(env.ctx)[0]
        check.equal((row["name"], row["version"], row["updated_by"]), ("新名", 2, env.actor.id))
        audit = ap_db.audits(env.ctx, "organization.update")
        check.equal(audit[0]["payload"], {"changes": {"name": {"before": "旧名", "after": "新名"}}, "version": {"before": 1, "after": 2}})

    def test_same_name_is_noop(self, run, ap_db, env):
        """同じ名前なら何もしない(version も監査ログも増えない)。"""
        org = ap_db.add_org(env.ctx, "同じ")
        view = run(lambda s: s.update_organization(org.id, expected_version=1, name="同じ"))
        check.equal(view.version, 1)
        check.equal(ap_db.audits(env.ctx, "organization.update"), [])

    def test_case_only_rename_of_itself_is_allowed(self, run, ap_db, env):
        """自分自身の名前を大文字小文字だけ変えるのは、他の組織との重複ではないので許可する。"""
        org = ap_db.add_org(env.ctx, "Dev")
        view = run(lambda s: s.update_organization(org.id, expected_version=1, name="DEV"))
        check.equal((view.name, view.version), ("DEV", 2))

    def test_rename_to_other_active_name_is_conflict(self, run, ap_db, env):
        """別の有効な組織の名前(大文字小文字違いを含む)への変更は OrganizationNameConflictError で、変更しない。"""
        ap_db.add_org(env.ctx, "営業部")
        org = ap_db.add_org(env.ctx, "開発部")
        with pytest.raises(OrganizationNameConflictError):
            run(lambda s: s.update_organization(org.id, expected_version=1, name="営業部"))
        row = next(o for o in ap_db.orgs(env.ctx) if o["id"] == org.id)
        check.equal((row["name"], row["version"]), ("開発部", 1))
        check.equal(ap_db.audits(env.ctx, "organization.update"), [])

    def test_rename_to_deleted_name_is_allowed(self, run, ap_db, env):
        """論理削除済みの組織の名前には変更できる。"""
        ap_db.add_org(env.ctx, "旧部署", deleted=True)
        org = ap_db.add_org(env.ctx, "開発部")
        view = run(lambda s: s.update_organization(org.id, expected_version=1, name="旧部署"))
        check.equal(view.name, "旧部署")

    def test_stale_version(self, run, ap_db, env):
        """version が違えば OrganizationVersionConflictError(期待値・現在値付き)で、変更しない。"""
        org = ap_db.add_org(env.ctx, "開発部")
        with pytest.raises(OrganizationVersionConflictError) as caught:
            run(lambda s: s.update_organization(org.id, expected_version=3, name="新名"))
        check.equal((caught.value.expected_version, caught.value.actual_version, caught.value.code), (3, 1, "organization_version_conflict"))
        check.equal(ap_db.orgs(env.ctx)[0]["name"], "開発部")

    def test_invalid_name(self, run, ap_db, env):
        """不正な名前は OrganizationValidationError。"""
        org = ap_db.add_org(env.ctx, "開発部")
        with pytest.raises(OrganizationValidationError):
            run(lambda s: s.update_organization(org.id, expected_version=1, name=" "))

    def test_deleted_and_other_tenant_organizations_are_not_found(self, run, ap_db, env):
        """論理削除済み・他テナントの組織の更新は OrganizationNotFoundError。他テナントの組織は変わらない。"""
        other = ap_db.tenant()
        deleted = ap_db.add_org(env.ctx, "削除済み", deleted=True)
        foreign = ap_db.add_org(other, "他社")
        for organization_id in (deleted.id, foreign.id, uuid.uuid4()):
            with pytest.raises(OrganizationNotFoundError):
                run(lambda s, organization_id=organization_id: s.update_organization(organization_id, expected_version=1, name="乗っ取り"))
        row = ap_db.orgs(other)[0]
        check.equal((row["name"], row["version"]), ("他社", 1))
        check.equal(ap_db.audits(other), [])

    def test_concurrent_updates_only_one_wins(self, ap_db, env):
        """同じ version の同時更新は直列化され、片方だけ成功する(更新の消失なし)。"""
        org = ap_db.add_org(env.ctx, "開発部")
        barrier = threading.Barrier(2)

        def attempt(name):
            barrier.wait(timeout=10)
            with ap_db.session(env.ctx) as session:
                try:
                    OrganizationService(session, actor_subject=env.actor.idp_subject).update_organization(org.id, expected_version=1, name=name)
                except OrganizationVersionConflictError:
                    return "conflict"
                return "ok"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(attempt, ["甲", "乙"]))
        check.equal(outcomes, ["conflict", "ok"])
        check.equal(ap_db.orgs(env.ctx)[0]["version"], 2)


class TestDelete:
    """論理削除(PF-ORG-03)。"""

    def test_soft_delete_keeps_row_and_members(self, run, ap_db, env):
        """削除は論理削除(deleted_at 設定、version +1)で、行も所属も物理的には残る。監査ログ organization.delete を残す。"""
        user = ap_db.add_user(env.ctx)
        org = ap_db.add_org(env.ctx, "開発部", members=(user.id,))
        run(lambda s: s.delete_organization(org.id, expected_version=1))
        row = ap_db.orgs(env.ctx)[0]
        check.is_not_none(row["deleted_at"])
        check.equal((row["version"], row["updated_by"]), (2, env.actor.id))
        check.equal(ap_db.members(env.ctx, org.id), [user.id])
        audit = ap_db.audits(env.ctx, "organization.delete")
        check.equal((len(audit), audit[0]["payload"]), (1, {"name": "開発部", "version": {"before": 1, "after": 2}}))

    def test_deleted_organization_is_gone_for_every_operation(self, run, ap_db, env):
        """削除後は、取得・メンバー参照・更新・再削除・メンバー置き換えのすべてが OrganizationNotFoundError。一覧にも出ない。"""
        org = ap_db.add_org(env.ctx, "開発部")
        run(lambda s: s.delete_organization(org.id, expected_version=1))
        operations = [
            lambda s: s.get_organization(org.id),
            lambda s: s.list_member_ids(org.id),
            lambda s: s.update_organization(org.id, expected_version=2, name="x"),
            lambda s: s.delete_organization(org.id, expected_version=2),
            lambda s: s.set_members(org.id, expected_version=2, user_ids=[]),
        ]
        for operation in operations:
            with pytest.raises(OrganizationNotFoundError):
                run(operation)
        check.equal(run(lambda s: s.list_organizations()).items, [])

    def test_stale_version(self, run, ap_db, env):
        """version が違えば OrganizationVersionConflictError で削除しない。"""
        org = ap_db.add_org(env.ctx, "開発部")
        with pytest.raises(OrganizationVersionConflictError):
            run(lambda s: s.delete_organization(org.id, expected_version=9))
        check.is_none(ap_db.orgs(env.ctx)[0]["deleted_at"])

    def test_other_tenant_organization_is_not_found_and_untouched(self, run, ap_db, env):
        """他テナントの組織の削除は OrganizationNotFoundError で、他テナントの組織は削除されない。"""
        other = ap_db.tenant()
        foreign = ap_db.add_org(other, "他社")
        with pytest.raises(OrganizationNotFoundError):
            run(lambda s: s.delete_organization(foreign.id, expected_version=1))
        row = ap_db.orgs(other)[0]
        check.equal((row["deleted_at"], row["version"]), (None, 1))
        check.equal(ap_db.audits(other), [])


class TestSetMembers:
    """メンバーの全置換(PF-ORG-02)。"""

    def test_add_and_remove_members(self, run, ap_db, env):
        """指定したユーザーの集合に置き換える(追加・削除)。version +1、監査ログに追加/削除した ID を残す。"""
        a, b, c = (ap_db.add_user(env.ctx) for _ in range(3))
        org = ap_db.add_org(env.ctx, "開発部", members=(a.id, b.id))
        view = run(lambda s: s.set_members(org.id, expected_version=1, user_ids=[b.id, c.id]))
        check.equal(view.version, 2)
        check.equal(ap_db.members(env.ctx, org.id), sorted([b.id, c.id]))
        audit = ap_db.audits(env.ctx, "organization.set_members")
        check.equal(len(audit), 1)
        check.equal((audit[0]["payload"]["added"], audit[0]["payload"]["removed"], audit[0]["payload"]["version"]), ([str(c.id)], [str(a.id)], {"before": 1, "after": 2}))
        check.equal(ap_db.orgs(env.ctx)[0]["updated_by"], env.actor.id)

    def test_same_members_is_noop(self, run, ap_db, env):
        """メンバーが変わらない置き換え(順序・重複違いを含む)は何もしない(version も監査ログも増えない)。"""
        a, b = ap_db.add_user(env.ctx), ap_db.add_user(env.ctx)
        org = ap_db.add_org(env.ctx, "開発部", members=(a.id, b.id))
        view = run(lambda s: s.set_members(org.id, expected_version=1, user_ids=[b.id, a.id, b.id]))
        check.equal(view.version, 1)
        check.equal(ap_db.audits(env.ctx, "organization.set_members"), [])

    def test_empty_list_removes_everyone(self, run, ap_db, env):
        """空の配列で全員を外せる。"""
        a = ap_db.add_user(env.ctx)
        org = ap_db.add_org(env.ctx, "開発部", members=(a.id,))
        run(lambda s: s.set_members(org.id, expected_version=1, user_ids=[]))
        check.equal(ap_db.members(env.ctx, org.id), [])

    def test_duplicates_are_collapsed(self, run, ap_db, env):
        """重複した ID は 1 つにして追加する。"""
        a = ap_db.add_user(env.ctx)
        org = ap_db.add_org(env.ctx, "開発部")
        run(lambda s: s.set_members(org.id, expected_version=1, user_ids=[a.id, a.id]))
        check.equal(ap_db.members(env.ctx, org.id), [a.id])

    def test_deactivated_users_can_be_members(self, run, ap_db, env):
        """無効化されたユーザーもメンバーにできる。"""
        a = ap_db.add_user(env.ctx, is_active=False)
        org = ap_db.add_org(env.ctx, "開発部")
        run(lambda s: s.set_members(org.id, expected_version=1, user_ids=[a.id]))
        check.equal(ap_db.members(env.ctx, org.id), [a.id])

    def test_unknown_user_is_rejected(self, run, ap_db, env):
        """存在しないユーザー ID が含まれると InvalidOrganizationMembersError(存在しない ID だけ)。メンバーは変わらず、version も上がらない。"""
        a = ap_db.add_user(env.ctx)
        ghost = uuid.uuid4()
        org = ap_db.add_org(env.ctx, "開発部")
        with pytest.raises(InvalidOrganizationMembersError) as caught:
            run(lambda s: s.set_members(org.id, expected_version=1, user_ids=[a.id, ghost]))
        check.equal(caught.value.user_ids, (ghost,))
        check.equal((caught.value.code, caught.value.field, caught.value.reason), ("invalid_organization_members", "user_ids", "not_found"))
        check.equal(ap_db.members(env.ctx, org.id), [])
        check.equal(ap_db.orgs(env.ctx)[0]["version"], 1)

    def test_other_tenant_user_is_rejected(self, run, ap_db, env):
        """他テナントのユーザーは存在しないユーザーと同じ InvalidOrganizationMembersError(RLS で見えない)。他テナントの組織にも、自組織にも所属は作られない。"""
        other = ap_db.tenant()
        mine = ap_db.add_user(env.ctx)
        foreign = ap_db.add_user(other)
        org = ap_db.add_org(env.ctx, "開発部")
        with pytest.raises(InvalidOrganizationMembersError) as caught:
            run(lambda s: s.set_members(org.id, expected_version=1, user_ids=[mine.id, foreign.id]))
        check.equal(caught.value.user_ids, (foreign.id,))
        check.equal(ap_db.members(env.ctx, org.id), [])
        check.equal(ap_db.rows(other, "SELECT * FROM t_organization_member"), [])

    def test_composite_foreign_key_rejects_cross_tenant_member_even_without_precheck(self, run, ap_db, env, monkeypatch):
        """事前チェックをすり抜けても、複合外部キーで他テナントのユーザーの所属は作れず、InvalidOrganizationMembersError になりロールバックされる(多重防御)。"""
        other = ap_db.tenant()
        foreign = ap_db.add_user(other)
        org = ap_db.add_org(env.ctx, "開発部")
        monkeypatch.setattr(user_repo, "find_existing_user_ids", lambda session, ids: set(ids))
        with pytest.raises(InvalidOrganizationMembersError):
            run(lambda s: s.set_members(org.id, expected_version=1, user_ids=[foreign.id]))
        check.equal(ap_db.members(env.ctx, org.id), [])
        check.equal(ap_db.orgs(env.ctx)[0]["version"], 1)
        check.equal(ap_db.audits(env.ctx, "organization.set_members"), [])

    def test_other_tenant_organization_is_not_found(self, run, ap_db, env):
        """他テナントの組織のメンバー置き換えは OrganizationNotFoundError。他テナントの所属は変わらない。"""
        other = ap_db.tenant()
        theirs = ap_db.add_user(other)
        foreign = ap_db.add_org(other, "他社", members=(theirs.id,))
        with pytest.raises(OrganizationNotFoundError):
            run(lambda s: s.set_members(foreign.id, expected_version=1, user_ids=[]))
        check.equal(ap_db.members(other, foreign.id), [theirs.id])

    def test_stale_version(self, run, ap_db, env):
        """version が違えば OrganizationVersionConflictError で、メンバーは変わらない。"""
        a = ap_db.add_user(env.ctx)
        org = ap_db.add_org(env.ctx, "開発部")
        with pytest.raises(OrganizationVersionConflictError):
            run(lambda s: s.set_members(org.id, expected_version=5, user_ids=[a.id]))
        check.equal(ap_db.members(env.ctx, org.id), [])

    def test_validation_of_user_ids(self, run, ap_db, env):
        """user_ids の型・形式・件数の上限(1000)を検証する。違反は OrganizationValidationError で、何も変えない。"""
        org = ap_db.add_org(env.ctx, "開発部")
        cases = [
            ("abc", "type"),
            (["not-a-uuid"], "format"),
            ([str(uuid.uuid4())], "format"),
            ([uuid.uuid4() for _ in range(MAX_ORGANIZATION_MEMBERS + 1)], "too_many"),
        ]
        for value, reason in cases:
            with pytest.raises(OrganizationValidationError) as caught:
                run(lambda s, value=value: s.set_members(org.id, expected_version=1, user_ids=value))
            check.equal((caught.value.field, caught.value.reason), ("user_ids", reason))
        check.equal(ap_db.orgs(env.ctx)[0]["version"], 1)


class TestDatabaseGuards:
    """DB の制約(複合外部キー・RLS の WITH CHECK)でも、テナントを跨ぐ関連付けは拒否される。"""

    def test_member_row_with_user_of_other_tenant_is_rejected(self, ap_db, env):
        """tenant_id=自テナントのまま、他テナントのユーザーを指す所属の行は、複合外部キーで拒否される。"""
        other = ap_db.tenant()
        foreign = ap_db.add_user(other)
        org = ap_db.add_org(env.ctx, "開発部")
        with ap_db.session(env.ctx) as session:
            session.add(TOrganizationMember(tenant_id=env.ctx.tenant_id, organization_id=org.id, user_id=foreign.id))
            with pytest.raises(IntegrityError):
                session.commit()
        check.equal(ap_db.members(env.ctx, org.id), [])

    def test_row_with_other_tenant_id_is_rejected_by_rls(self, ap_db, env):
        """コンテキストと違う tenant_id を書いた行は、RLS の WITH CHECK で拒否される(リクエスト由来の tenant_id を混ぜても書けない)。"""
        other = ap_db.tenant()
        mine = ap_db.add_user(env.ctx)
        org = ap_db.add_org(env.ctx, "開発部")
        with ap_db.session(env.ctx) as session:
            session.add(TOrganizationMember(tenant_id=other.tenant_id, organization_id=org.id, user_id=mine.id))
            with pytest.raises(DBAPIError):
                session.commit()
        check.equal(ap_db.members(env.ctx, org.id), [])
        check.equal(ap_db.rows(other, "SELECT * FROM t_organization_member"), [])
