# -*- coding: utf-8 -*-
"""ToDo の閲覧範囲(AP-VIS)のテスト。一覧(各 scope)と単体(詳細・更新・削除・担当者変更・アクティビティ)で同じ結果になること(AP-VIS-09)。

期待値(オラクル)は、仕様(docs/spec/ToDoApp.md §4.2)から実装とは独立に Python で計算する。ToDo は ``TodoFactory`` で直接作る。
開発 DB の使い捨てテナントに作り、終了時に削除する(alpha / beta には触れない)。
"""
import uuid
from dataclasses import dataclass

import pytest
import pytest_check as check

from main_app.services.errors import TodoNotFoundError, TodoVersionConflictError
from main_app.services.todo_policy import TodoScope

ACTORS = ["admin", "creator", "assignee", "m1", "m2", "outsider", "n3"]
SCOPES = ["all", "mine", "assigned", "shared"]


@dataclass
class Case:
    """オラクル用の ToDo の期待値の元データ。"""

    key: str
    creator: str
    visibility: str
    orgs: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    deleted: bool = False


CASES = [
    Case("private", "creator", "private"),
    Case("private_assigned", "creator", "private", assignees=("assignee",)),
    Case("tenant", "creator", "tenant"),
    Case("tenant_deleted", "creator", "tenant", deleted=True),
    Case("org_o1", "creator", "organization", orgs=("o1",)),
    Case("org_o2", "creator", "organization", orgs=("o2",)),
    Case("org_o1_o2", "creator", "organization", orgs=("o1", "o2")),
    Case("org_o3_only", "creator", "organization", orgs=("o3",)),
    Case("org_o1_o3", "creator", "organization", orgs=("o1", "o3")),
    Case("org_o1_assigned_m2", "creator", "organization", orgs=("o1",), assignees=("m2",)),
    Case("private_by_m1", "m1", "private"),
    Case("tenant_by_outsider", "outsider", "tenant"),
    Case("org_o1_by_n3", "n3", "organization", orgs=("o1",)),
    Case("private_assigned_both", "m2", "private", assignees=("assignee", "m1")),
]


def can_view(world, case: Case, actor_key: str) -> bool:
    """仕様(AP-VIS)から計算する、閲覧できるか。"""
    actor = world.people[actor_key]
    if case.deleted:
        return False
    if actor.is_admin:
        return True
    if case.creator == actor_key or actor_key in case.assignees:
        return True
    if case.visibility == "tenant":
        return True
    if case.visibility == "organization":
        members = {"o1": {"m1"}, "o2": {"m2"}, "o3": {"n3"}}
        active = {"o1", "o2"}
        return any(org in active and actor_key in members[org] for org in case.orgs)
    return False


def in_scope(case: Case, actor_key: str, scope: str) -> bool:
    mine = case.creator == actor_key
    assigned = actor_key in case.assignees
    return {"all": True, "mine": mine, "assigned": assigned, "shared": not mine and not assigned}[scope]


@pytest.fixture
def seeded(world):
    """CASES の ToDo を作り、key → ID を返す。"""
    ids = {}
    for case in CASES:
        ids[case.key] = world.factory.add(
            world.ctx,
            world.people[case.creator],
            title=case.key,
            visibility=case.visibility,
            orgs=[world.orgs[o] for o in case.orgs],
            assignees=[world.people[a] for a in case.assignees],
            deleted=case.deleted,
        )
    return ids


def list_all(world, actor, **kwargs) -> set[str]:
    """全ページを辿り、タイトル(= key)の集合を返す。"""
    titles, after = [], None
    with world.service(actor) as service:
        for _ in range(50):
            page = service.list_todos(limit=4, after=after, sort="created_at", **kwargs)
            titles.extend(item.title for item in page.items)
            after = page.next_after
            if after is None:
                break
    assert len(titles) == len(set(titles)), "一覧に重複がある"
    return set(titles)


@pytest.mark.parametrize("actor_key", ACTORS)
class TestListMatchesOracle:
    """一覧は、仕様から計算した期待値と一致する。"""

    @pytest.mark.parametrize("scope", SCOPES)
    def test_scope_lists_exactly_the_viewable_todos(self, world, seeded, actor_key, scope):
        """各 scope の一覧は「閲覧できる ToDo」と「scope の条件(mine / assigned / shared)」の積と一致する(論理削除済みは誰にも出ない)。"""
        expected = {case.key for case in CASES if can_view(world, case, actor_key) and in_scope(case, actor_key, scope)}
        check.equal(list_all(world, world.people[actor_key], scope=scope), expected)

    def test_scopes_partition_all(self, world, seeded, actor_key):
        """mine / assigned / shared の和は all(assigned と shared は重ならず、mine と shared も重ならない)。"""
        sets = {scope: list_all(world, world.people[actor_key], scope=scope) for scope in SCOPES}
        check.equal(sets["mine"] | sets["assigned"] | sets["shared"], sets["all"])
        check.equal(sets["shared"] & (sets["mine"] | sets["assigned"]), set())


@pytest.mark.parametrize("actor_key", ACTORS)
class TestSingleOperationsMatchList:
    """単体の取得・更新・削除・担当者変更・アクティビティは、一覧と同じ「閲覧できるか」で 404 になる。"""

    def test_not_found_iff_not_viewable(self, world, seeded, actor_key):
        """閲覧できない ToDo は、どの操作でも TodoNotFoundError。閲覧できる ToDo は(版が古ければ TodoVersionConflictError で)404 にならない。"""
        actor = world.people[actor_key]
        listed = list_all(world, actor)
        operations = {
            "get": lambda s, i, v: s.get_todo(i),
            "activities": lambda s, i, v: s.list_activities(i),
            "update": lambda s, i, v: s.update_todo(i, expected_version=v + 100, title="x"),
            "delete": lambda s, i, v: s.delete_todo(i, expected_version=v + 100),
            "assignees": lambda s, i, v: s.set_assignees(i, expected_version=v + 100, user_ids=[]),
        }
        for case in CASES:
            todo_id = seeded[case.key]
            viewable = can_view(world, case, actor_key)
            check.equal(case.key in listed, viewable, f"一覧 {case.key}")
            for name, operation in operations.items():
                try:
                    with world.service(actor) as service:
                        operation(service, todo_id, 1)
                    outcome = "ok"
                except TodoNotFoundError:
                    outcome = "404"
                except TodoVersionConflictError:
                    outcome = "412"
                expected = ("ok" if name in ("get", "activities") else "412") if viewable else "404"
                check.equal(outcome, expected, f"{actor_key} / {case.key} / {name}")

    def test_unknown_id_is_the_same_as_not_viewable(self, world, seeded, actor_key):
        """存在しない ID と閲覧できない ID は区別できない(どちらも同じ TodoNotFoundError)。"""
        actor = world.people[actor_key]
        hidden = next((case for case in CASES if not can_view(world, case, actor_key)), None)
        for todo_id in ([seeded[hidden.key]] if hidden else []) + [uuid.uuid4()]:
            with pytest.raises(TodoNotFoundError) as caught:
                world.call(actor, lambda s, todo_id=todo_id: s.get_todo(todo_id))
            check.equal(str(caught.value), f"todo not found: {todo_id}")


class TestFilterDoesNotLeak:
    """絞り込み(担当者・組織)でも、閲覧できない ToDo は現れない。"""

    def test_organization_filter_respects_visibility(self, world, seeded):
        """organization_id で絞り込んでも、組織の所属者でない人には公開先の ToDo が見えない。tenant_admin・作成者・担当者には見える。"""
        expected = {
            "admin": {"org_o1", "org_o1_o2", "org_o1_o3", "org_o1_assigned_m2", "org_o1_by_n3"},
            "m1": {"org_o1", "org_o1_o2", "org_o1_o3", "org_o1_assigned_m2", "org_o1_by_n3"},
            "outsider": set(),
            "n3": {"org_o1_by_n3"},  # 作成者として見える
            "m2": {"org_o1_o2", "org_o1_assigned_m2"},  # org_o1_o2 は O2 の所属者として、org_o1_assigned_m2 は担当者として見える
        }
        for actor_key, titles in expected.items():
            check.equal(list_all(world, world.people[actor_key], organization_id=world.o1), titles, actor_key)

    def test_deleted_organization_filter_matches_nothing(self, world, seeded):
        """論理削除済みの組織で絞り込むと、管理者でも 0 件(公開先として有効ではない)。"""
        check.equal(list_all(world, world.admin, organization_id=world.o3), set())

    def test_assignee_filter_respects_visibility(self, world, seeded):
        """assignee_id で絞り込んでも、見えない ToDo は含まれない(他人の private な ToDo の担当者を探れない)。"""
        check.equal(list_all(world, world.outsider, assignee_id=world.assignee.id), set())
        check.equal(list_all(world, world.admin, assignee_id=world.assignee.id), {"private_assigned", "private_assigned_both"})
        check.equal(list_all(world, world.m1, assignee_id=world.assignee.id), {"private_assigned_both"})


class TestOrganizationChanges:
    """組織の削除・所属の変更が、一覧と単体の両方に同じように反映される(AP-VIS-08)。"""

    def test_deleting_the_only_organization_makes_it_private(self, world):
        """公開先の組織がすべて削除されると、所属者から見えなくなる(private 相当)。作成者・担当者・管理者には見え続け、effective_visibility は private になる。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1], assignees=[world.assignee])
        check.equal(world.call(world.m1, lambda s: s.get_todo(todo_id)).effective_visibility.value, "organization")
        with world.ap_db.session(world.ctx) as session:
            session.connection().exec_driver_sql("UPDATE t_organization SET deleted_at = now() WHERE id = %s", (world.o1,))
            session.commit()
        with pytest.raises(TodoNotFoundError):
            world.call(world.m1, lambda s: s.get_todo(todo_id))
        check.equal(list_all(world, world.m1), set())
        for person in (world.creator, world.assignee, world.admin):
            detail = world.call(person, lambda s: s.get_todo(todo_id))
            check.equal((detail.visibility.value, detail.effective_visibility.value, detail.organizations), ("organization", "private", ()))

    def test_remaining_organizations_still_decide(self, world):
        """公開先が 2 つで片方が削除されても、残りの組織の所属者には見える。削除された組織の所属者には見えない。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o1, world.o3])
        check.is_not_none(world.call(world.m1, lambda s: s.get_todo(todo_id)))
        with pytest.raises(TodoNotFoundError):
            world.call(world.n3, lambda s: s.get_todo(todo_id))
        detail = world.call(world.admin, lambda s: s.get_todo(todo_id))
        check.equal([o.id for o in detail.organizations], [world.o1])
        check.equal(detail.effective_visibility.value, "organization")

    def test_joining_and_leaving_an_organization(self, world):
        """組織に所属すると見えるようになり、外れると見えなくなる(所属の変更は次のリクエストから反映される)。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="organization", orgs=[world.o2])
        with pytest.raises(TodoNotFoundError):
            world.call(world.outsider, lambda s: s.get_todo(todo_id))
        with world.ap_db.session(world.ctx) as session:
            session.connection().exec_driver_sql("INSERT INTO t_organization_member (tenant_id, organization_id, user_id) VALUES (%s, %s, %s)", (world.ctx.tenant_id, world.o2, world.outsider.id))
            session.commit()
        check.is_not_none(world.call(world.outsider, lambda s: s.get_todo(todo_id)))
        check.equal(list_all(world, world.outsider), {"todo"})
        with world.ap_db.session(world.ctx) as session:
            session.connection().exec_driver_sql("DELETE FROM t_organization_member WHERE user_id = %s", (world.outsider.id,))
            session.commit()
        with pytest.raises(TodoNotFoundError):
            world.call(world.outsider, lambda s: s.get_todo(todo_id))

    def test_non_organization_visibility_ignores_leftover_links(self, world):
        """visibility が organization 以外なら、公開先の行が残っていても組織の所属は閲覧範囲に影響しない(private のまま)。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="private", orgs=[world.o1])
        with pytest.raises(TodoNotFoundError):
            world.call(world.m1, lambda s: s.get_todo(todo_id))
        check.equal(list_all(world, world.m1), set())

    def test_user_deactivation_does_not_change_visibility(self, world):
        """担当者が無効化されても、割り当ては残り、閲覧範囲(担当者として見える)も変わらない(AP-ASN-04)。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="private", assignees=[world.inactive])
        detail = world.call(world.admin, lambda s: s.get_todo(todo_id))
        check.equal([(a.user_id, a.is_active) for a in detail.assignees], [(world.inactive.id, False)])


class TestPermissionsInDetail:
    """詳細の permissions(画面の出し分け用)は ToDoApp.md §3 の表と一致する。"""

    @pytest.mark.parametrize(
        ("actor_key", "expected"),
        [
            ("admin", (True, True, True, True, True)),
            ("creator", (True, True, True, True, True)),
            ("assignee", (False, True, False, True, False)),
            ("m1", (False, False, False, False, False)),
        ],
    )
    def test_permissions(self, world, actor_key, expected):
        """tenant_admin・作成者は全操作、担当者はステータスと担当者の変更だけ、それ以外の閲覧者は何もできない。"""
        todo_id = world.factory.add(world.ctx, world.creator, visibility="tenant", assignees=[world.assignee])
        permissions = world.call(world.people[actor_key], lambda s: s.get_todo(todo_id)).permissions
        check.equal((permissions.can_edit_fields, permissions.can_change_status, permissions.can_change_visibility, permissions.can_change_assignees, permissions.can_delete), expected)


def test_scope_enum_values():
    """表示範囲は mine / assigned / shared / all の 4 つ。"""
    check.equal(sorted(s.value for s in TodoScope), sorted(SCOPES))
