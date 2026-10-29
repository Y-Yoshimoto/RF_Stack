# -*- coding: utf-8 -*-
"""ユーザーの写し(姓・名・ロール)と、画面が名前を引くための API の追加分のテスト(docs/spec/ToDoApp.md §9.3・§9.5、02 §5.6)。

対象: GET /api/v1/users(first_name / last_name / roles、ids)、GET /users/{id}・PATCH の応答の項目、GET /api/v1/me の organizations、
GET /api/v1/todos/{id}/activities の users。いずれもクロステナント(他テナントの ID・組織が出ない)を 2 テナントのデータで確認する。

認証・テナント判定・CSRF・サービス・DB(開発 DB の ``app_db``、RLS)は実物。Keycloak だけがフェイク(``fake_idp_user_service``)。
テナントは台帳に作る使い捨て(``ap_tenant``)。alpha / beta には触れない。
"""
import datetime as dt
import uuid

import pytest
import pytest_check as check
from todos.conftest import TodoFactory

from main_app.models import TTodoActivity

from .conftest import with_csrf

USERS = "/api/v1/users"
ME = "/api/v1/me"
TODOS = "/api/v1/todos"

pytestmark = pytest.mark.usefixtures("fake_idp_user_service")


def etag(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


@pytest.fixture
def world(ap_tenant, ap_login):
    """2 つのテナント(A / B)。A には管理者・メンバー 2 人、B には管理者とメンバーがいる。"""

    class World:
        a = ap_tenant()
        b = ap_tenant()

    World.admin_a = ap_login(World.a, name="Ada")
    World.member_a = ap_login(World.a, roles=("member",), name="Mia")
    World.other_a = ap_login(World.a, roles=("member",), name="Otto")
    World.admin_b = ap_login(World.b, name="Bea")
    World.member_b = ap_login(World.b, roles=("member",), name="Ben")
    return World


def set_copies(ap_db, ctx, user_id, *, first, last, roles) -> None:
    """ユーザー行の写しを直接設定する(同期済みの状態の準備)。"""
    with ap_db.session(ctx) as session:
        session.connection().exec_driver_sql("UPDATE t_user SET first_name = %s, last_name = %s, roles = %s WHERE id = %s", (first, last, roles, user_id))
        session.commit()


def ids_param(*user_ids) -> dict[str, str]:
    return {"ids": ",".join(str(user_id) for user_id in user_ids)}


class TestListCopies:
    """GET /api/v1/users: 姓・名・ロールは AP の DB の写し(IdP に問い合わせない)。"""

    def test_items_carry_the_copies(self, client, world, ap_db, idp):
        """同期済みのユーザーは姓・名・ロール(tenant_admin, member の順)を返し、未同期のユーザーは null / 空配列。IdP には問い合わせない。"""
        set_copies(ap_db, world.a.ctx, world.admin_a.user_id, first="Ada", last="Admin", roles=["tenant_admin", "member"])
        set_copies(ap_db, world.a.ctx, world.member_a.user_id, first="Mia", last="Member", roles=["member"])
        before = list(idp.factory_realms)
        body = client.get(USERS, headers=world.admin_a.headers).json()
        by_id = {item["id"]: item for item in body["items"]}
        check.equal(len(body["items"]), 3)
        admin, member, unsynced = by_id[str(world.admin_a.user_id)], by_id[str(world.member_a.user_id)], by_id[str(world.other_a.user_id)]
        check.equal((admin["first_name"], admin["last_name"], admin["roles"]), ("Ada", "Admin", ["tenant_admin", "member"]))
        check.equal((member["first_name"], member["last_name"], member["roles"]), ("Mia", "Member", ["member"]))
        check.equal((unsynced["first_name"], unsynced["last_name"], unsynced["roles"]), (None, None, []))
        check.equal(idp.factory_realms, before)

    def test_other_tenant_copies_are_not_listed(self, client, world, ap_db):
        """他テナントのユーザーは、その写しも含めて一覧に出ない(件数も自分のテナントだけ)。"""
        set_copies(ap_db, world.b.ctx, world.admin_b.user_id, first="Bea", last="Admin", roles=["tenant_admin", "member"])
        body = client.get(USERS, headers=world.admin_a.headers).json()
        listed = {item["id"] for item in body["items"]}
        check.equal(listed, {str(world.admin_a.user_id), str(world.member_a.user_id), str(world.other_a.user_id)})
        check.is_not_in("Bea", client.get(USERS, headers=world.admin_a.headers).text)

    def test_member_sees_the_same_fields(self, client, world):
        """member も同じ項目を取得できる(参照は全メンバー)。"""
        item = client.get(USERS, headers=world.member_a.headers).json()["items"][0]
        check.is_true({"first_name", "last_name", "roles"} <= set(item))


class TestListIds:
    """GET /api/v1/users?ids=: 画面が ID から名前を引くための絞り込み。"""

    def test_filters_by_ids(self, client, world):
        """指定した ID のユーザーだけを返す。存在しない ID はエラーにならず含まれない。"""
        wanted = [world.admin_a.user_id, world.other_a.user_id, uuid.uuid4()]
        body = client.get(USERS, headers=world.member_a.headers, params=ids_param(*wanted)).json()
        check.equal({item["id"] for item in body["items"]}, {str(world.admin_a.user_id), str(world.other_a.user_id)})

    def test_duplicates_are_removed(self, client, world):
        """同じ ID が複数あっても 1 件(重複は除く)。"""
        body = client.get(USERS, headers=world.admin_a.headers, params=ids_param(*([world.member_a.user_id] * 5))).json()
        check.equal([item["id"] for item in body["items"]], [str(world.member_a.user_id)])

    def test_exactly_100_ids_is_accepted(self, client, world):
        """重複を除いてちょうど 100 件は受け付ける(存在するのは 1 件)。"""
        ids = [world.member_a.user_id, *(uuid.uuid4() for _ in range(99))]
        response = client.get(USERS, headers=world.admin_a.headers, params=ids_param(*ids))
        check.equal(response.status_code, 200)
        check.equal(len(response.json()["items"]), 1)

    def test_duplicates_do_not_count_toward_the_limit(self, client, world):
        """上限は重複を除いた件数で数える(重複を含めて 101 個でも、重複を除いて 100 件なら受け付ける)。"""
        ids = [uuid.uuid4() for _ in range(100)]
        response = client.get(USERS, headers=world.admin_a.headers, params=ids_param(*ids, ids[0]))
        check.equal(response.status_code, 200)

    def test_101_ids_is_422_too_many(self, client, world):
        """重複を除いて 101 件は 422(invalid_user_input。ids の too_many)。"""
        response = client.get(USERS, headers=world.admin_a.headers, params=ids_param(*(uuid.uuid4() for _ in range(101))))
        check.equal(response.status_code, 422)
        body = response.json()
        check.equal(body["code"], "invalid_user_input")
        check.equal((body["errors"][0]["field"], body["errors"][0]["code"]), ("ids", "too_many"))
        check.is_in("application/problem+json", response.headers["content-type"])

    @pytest.mark.parametrize("bad", ["abc", f"{uuid.uuid4()},not-a-uuid", "12345", f"{uuid.uuid4()};{uuid.uuid4()}", "g" * 36])
    def test_malformed_ids_are_422_format(self, client, world, bad):
        """UUID でない値を 1 つでも含むと 422(ids の format)。一部だけを処理しない。"""
        response = client.get(USERS, headers=world.admin_a.headers, params={"ids": bad})
        check.equal(response.status_code, 422)
        check.equal((response.json()["code"], response.json()["errors"][0]["field"], response.json()["errors"][0]["code"]), ("invalid_user_input", "ids", "format"))

    @pytest.mark.parametrize("empty", ["", " ", ",", " , ,"])
    def test_empty_ids_return_nothing(self, client, world, empty):
        """ids が空(空文字・区切りだけ)なら 0 件(全件ではない)。"""
        response = client.get(USERS, headers=world.admin_a.headers, params={"ids": empty})
        check.equal(response.status_code, 200)
        check.equal((response.json()["items"], response.json()["next_cursor"]), ([], None))

    def test_omitted_ids_return_everyone(self, client, world):
        """ids を省略すれば全員(絞り込まない)。空とは区別される。"""
        check.equal(len(client.get(USERS, headers=world.admin_a.headers).json()["items"]), 3)

    def test_whitespace_around_ids_is_ignored(self, client, world):
        """ID の前後の空白は無視する。"""
        raw = f" {world.member_a.user_id} , {world.other_a.user_id} "
        body = client.get(USERS, headers=world.admin_a.headers, params={"ids": raw}).json()
        check.equal(len(body["items"]), 2)

    def test_other_tenant_ids_are_not_included(self, client, world):
        """他テナントのユーザー ID を指定しても結果に含まれない(404 ではなく、存在しない ID と同じ扱い)。逆方向も同じ。"""
        mixed = client.get(USERS, headers=world.admin_a.headers, params=ids_param(world.member_a.user_id, world.admin_b.user_id, world.member_b.user_id))
        check.equal(mixed.status_code, 200)
        check.equal([item["id"] for item in mixed.json()["items"]], [str(world.member_a.user_id)])
        only_foreign = client.get(USERS, headers=world.admin_a.headers, params=ids_param(world.admin_b.user_id, world.member_b.user_id)).json()
        check.equal(only_foreign["items"], [])
        reverse = client.get(USERS, headers=world.admin_b.headers, params=ids_param(world.admin_a.user_id, world.member_b.user_id)).json()
        check.equal([item["id"] for item in reverse["items"]], [str(world.member_b.user_id)])

    def test_combines_with_other_filters_and_paging(self, client, world, ap_db):
        """is_active との組み合わせ、limit と cursor によるページングでも ids の絞り込みが効く(続きのリクエストでも ids を指定する)。"""
        with ap_db.session(world.a.ctx) as session:
            session.connection().exec_driver_sql("UPDATE t_user SET is_active = false WHERE id = %s", (world.other_a.user_id,))
            session.commit()
        params = ids_param(world.admin_a.user_id, world.member_a.user_id, world.other_a.user_id)
        active = client.get(USERS, headers=world.admin_a.headers, params={**params, "is_active": "true"}).json()
        check.equal({item["id"] for item in active["items"]}, {str(world.admin_a.user_id), str(world.member_a.user_id)})
        inactive = client.get(USERS, headers=world.admin_a.headers, params={**params, "is_active": "false"}).json()
        check.equal([item["id"] for item in inactive["items"]], [str(world.other_a.user_id)])

        seen: list[str] = []
        cursor = None
        for _ in range(5):
            page = client.get(USERS, headers=world.admin_a.headers, params={**params, "limit": 2, **({"cursor": cursor} if cursor else {})}).json()
            seen.extend(item["id"] for item in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        check.equal(sorted(seen), sorted(str(i) for i in (world.admin_a.user_id, world.member_a.user_id, world.other_a.user_id)))
        check.equal(len(seen), len(set(seen)))

    def test_ids_in_a_tenant_without_the_user_is_unauthenticated_first(self, client, world):
        """未認証なら ids があっても 401(絞り込みの前に認証)。"""
        check.equal(client.get(USERS, params=ids_param(world.member_a.user_id)).status_code, 401)


class TestDetailAndPatch:
    """GET /users/{id}・PATCH の応答の項目。"""

    def test_get_refreshes_the_copy_from_the_idp(self, client, world, idp, ap_db):
        """GET /users/{id} は IdP の姓・名・ロールで写しを更新して返す。version が +1 され(ETag も)、以降の一覧にも反映される。"""
        member = world.member_a
        idp.state_for(world.a.realm).users[member.sub].update({"firstName": "Maria", "lastName": "Member-Updated"})
        response = client.get(f"{USERS}/{member.user_id}", headers=world.admin_a.headers)
        check.equal(response.status_code, 200, response.text)
        body = response.json()
        check.equal((body["first_name"], body["last_name"], body["display_name"], body["roles"], body["version"]), ("Maria", "Member-Updated", "Maria Member-Updated", ["member"], 2))
        check.equal(response.headers["ETag"], '"2"')
        listed = {item["id"]: item for item in client.get(USERS, headers=world.admin_a.headers).json()["items"]}[str(member.user_id)]
        check.equal((listed["first_name"], listed["last_name"], listed["roles"], listed["version"]), ("Maria", "Member-Updated", ["member"], 2))

    def test_get_fills_unsynced_copy_without_version_bump(self, client, world):
        """未同期(姓・名 NULL、ロール空)のユーザーを GET すると写しを埋めるが、表示名が同じなら version は 1 のまま。"""
        response = client.get(f"{USERS}/{world.member_a.user_id}", headers=world.admin_a.headers)
        body = response.json()
        check.equal((body["first_name"], body["last_name"], body["roles"], body["version"]), ("Mia", "Actor", ["member"], 1))
        check.equal(response.headers["ETag"], '"1"')

    def test_get_when_user_is_missing_in_idp_returns_the_copy(self, client, world, idp, ap_db):
        """IdP にユーザーが無ければ、写しのまま 200 で返す(version も変えない)。"""
        set_copies(ap_db, world.a.ctx, world.member_a.user_id, first="Mia", last="Member", roles=["member"])
        idp.state_for(world.a.realm).users.pop(world.member_a.sub)
        response = client.get(f"{USERS}/{world.member_a.user_id}", headers=world.admin_a.headers)
        check.equal(response.status_code, 200)
        body = response.json()
        check.equal((body["first_name"], body["last_name"], body["roles"], body["version"]), ("Mia", "Member", ["member"], 1))

    def test_get_idp_failure_is_502(self, client, world, idp):
        """IdP の問い合わせに失敗したら 502(identity_provider_operation_failed)。IdP のエラー詳細は返さない。"""
        idp.fail("GET", r"/users/[^/]+$", 500)
        response = client.get(f"{USERS}/{world.member_a.user_id}", headers=world.admin_a.headers)
        check.equal((response.status_code, response.json()["code"]), (502, "identity_provider_operation_failed"))
        check.is_not_in("injected", response.text)

    def test_patch_response_has_the_copies(self, client, world, idp):
        """PATCH の応答に姓・名・ロールを含む(姓・名を変えた場合は更新後の値)。ETag は新しい version。"""
        response = client.patch(f"{USERS}/{world.member_a.user_id}", json={"first_name": "Maria", "last_name": "Rossi"}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal(response.status_code, 200, response.text)
        body = response.json()
        check.equal((body["first_name"], body["last_name"], body["display_name"], body["version"]), ("Maria", "Rossi", "Maria Rossi", 2))
        check.is_in("roles", body)
        check.equal(response.headers["ETag"], '"2"')

    def test_patch_roles_updates_the_listed_copy(self, client, world):
        """PATCH でロールを変えると、応答と一覧のロールが「直接付与 + 既定の member」になる。"""
        response = client.patch(f"{USERS}/{world.member_a.user_id}", json={"roles": ["tenant_admin"]}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal(response.status_code, 200, response.text)
        check.equal(response.json()["roles"], ["tenant_admin", "member"])
        listed = {item["id"]: item for item in client.get(USERS, headers=world.admin_a.headers).json()["items"]}[str(world.member_a.user_id)]
        check.equal(listed["roles"], ["tenant_admin", "member"])

    def test_create_response_has_the_names(self, client, world):
        """POST の応答の user に姓・名が入り、roles は指定したロールを含む。"""
        response = client.post(USERS, json={"email": "new@example.com", "first_name": "New", "last_name": "Person", "roles": ["tenant_admin"]}, headers=with_csrf(world.admin_a.headers))
        check.equal(response.status_code, 201, response.text)
        user = response.json()["user"]
        check.equal((user["first_name"], user["last_name"]), ("New", "Person"))
        check.is_in("tenant_admin", user["roles"])

    def test_create_response_roles_match_the_copy(self, client, world):
        """POST の応答の roles は、同じユーザーの一覧・詳細で返る写しのロール(実効ロール)と一致する。"""
        response = client.post(USERS, json={"email": "new@example.com", "first_name": "New", "last_name": "Person", "roles": ["tenant_admin"]}, headers=with_csrf(world.admin_a.headers))
        user = response.json()["user"]
        listed = {item["id"]: item for item in client.get(USERS, headers=world.admin_a.headers).json()["items"]}[user["id"]]
        check.equal(user["roles"], listed["roles"])

    def test_other_tenant_user_is_404_and_untouched(self, client, world, ap_db, idp):
        """他テナントのユーザーの GET / PATCH は 404(存在を明かさない)。IdP に問い合わせず、他テナントの行も変わらない。"""
        before = list(idp.factory_realms)
        get = client.get(f"{USERS}/{world.member_b.user_id}", headers=world.admin_a.headers)
        patch = client.patch(f"{USERS}/{world.member_b.user_id}", json={"first_name": "X", "last_name": "Y"}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal((get.status_code, patch.status_code), (404, 404))
        check.equal(idp.factory_realms, before)
        row = ap_db.user(world.b.ctx, world.member_b.user_id)
        check.equal((row["version"], row["first_name"]), (1, None))


class TestMeOrganizations:
    """GET /api/v1/me の organizations: 所属する有効な組織(組織名順)。"""

    def test_only_active_memberships_in_name_order(self, client, world, ap_db):
        """所属する有効な組織だけを組織名順で返す。論理削除済み・所属していない組織は含めない。"""
        ap_db.add_org(world.a.ctx, "C-Org", members=(world.member_a.user_id,))
        ap_db.add_org(world.a.ctx, "A-Org", members=(world.member_a.user_id, world.other_a.user_id))
        ap_db.add_org(world.a.ctx, "B-Deleted", deleted=True, members=(world.member_a.user_id,))
        ap_db.add_org(world.a.ctx, "D-Not-Member", members=(world.other_a.user_id,))
        organizations = client.get(ME, headers=world.member_a.headers).json()["organizations"]
        check.equal([org["name"] for org in organizations], ["A-Org", "C-Org"])
        check.equal(set(organizations[0]), {"id", "name"})

    def test_no_membership_is_empty(self, client, world, ap_db):
        """所属が無いユーザーは空配列(組織が存在しても)。"""
        ap_db.add_org(world.a.ctx, "A-Org", members=(world.other_a.user_id,))
        check.equal(client.get(ME, headers=world.member_a.headers).json()["organizations"], [])

    def test_other_tenant_organizations_never_appear(self, client, world, ap_db):
        """他テナントの組織は、同名でも出ない。それぞれのテナントのユーザーは自分のテナントの組織だけを見る。"""
        own = ap_db.add_org(world.a.ctx, "Shared Name", members=(world.member_a.user_id,))
        foreign = ap_db.add_org(world.b.ctx, "Shared Name", members=(world.member_b.user_id,))
        ap_db.add_org(world.b.ctx, "B-Only", members=(world.member_b.user_id,))
        in_a = client.get(ME, headers=world.member_a.headers).json()["organizations"]
        in_b = client.get(ME, headers=world.member_b.headers).json()["organizations"]
        check.equal([org["id"] for org in in_a], [str(own.id)])
        check.equal(sorted(org["id"] for org in in_b), sorted([str(foreign.id), str(next(o for o in ap_db.orgs(world.b.ctx) if o["name"] == "B-Only")["id"])]))
        check.is_not_in("B-Only", client.get(ME, headers=world.member_a.headers).text)

    def test_ids_match_the_organizations_api(self, client, world, ap_db):
        """id は GET /api/v1/organizations の id と同じ値。組織名の変更は次の取得に反映される。"""
        org = ap_db.add_org(world.a.ctx, "Old Name", members=(world.member_a.user_id,))
        listed = client.get("/api/v1/organizations", headers=world.admin_a.headers).json()["items"]
        check.is_in(str(org.id), [item["id"] for item in listed])
        with ap_db.session(world.a.ctx) as session:
            session.connection().exec_driver_sql("UPDATE t_organization SET name = 'New Name' WHERE id = %s", (org.id,))
            session.commit()
        check.equal(client.get(ME, headers=world.member_a.headers).json()["organizations"], [{"id": str(org.id), "name": "New Name"}])

    def test_membership_removal_is_reflected(self, client, world, ap_db):
        """メンバーから外れると次の取得から出なくなる。"""
        org = ap_db.add_org(world.a.ctx, "Team", members=(world.member_a.user_id,))
        check.equal(len(client.get(ME, headers=world.member_a.headers).json()["organizations"]), 1)
        with ap_db.session(world.a.ctx) as session:
            session.connection().exec_driver_sql("DELETE FROM t_organization_member WHERE organization_id = %s", (org.id,))
            session.commit()
        check.equal(client.get(ME, headers=world.member_a.headers).json()["organizations"], [])


class TestActivityUsers:
    """GET /api/v1/todos/{id}/activities の users: ページが参照するユーザーの表示名と有効か(キーはユーザー ID)。"""

    @pytest.fixture
    def todo(self, world, ap_db):
        """A の ToDo(作成者 Ada、担当者 Mia)。アクティビティは直接作る。"""
        factory = TodoFactory(ap_db)
        todo_id = factory.add(world.a.ctx, world.admin_a.user_id, title="T", visibility="tenant", assignees=[world.member_a.user_id])
        return todo_id

    def add_activity(self, ap_db, world, todo_id, actor_id, action, payload, *, ctx=None, offset=0):
        ctx = ctx or world.a.ctx
        with ap_db.session(ctx) as session:
            session.add(TTodoActivity(tenant_id=ctx.tenant_id, todo_id=todo_id, actor_id=actor_id, action=action, payload=payload, created_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=offset)))
            session.commit()

    def test_actor_removed_assignee_and_inactive_user_are_resolved(self, client, world, ap_db, todo):
        """操作者・担当者から外れたユーザー・無効化されたユーザーも users に入る(display_name と is_active)。"""
        self.add_activity(ap_db, world, todo, world.admin_a.user_id, "created", {"values": {"assignee_ids": [str(world.member_a.user_id)]}}, offset=0)
        self.add_activity(ap_db, world, todo, world.admin_a.user_id, "assignees_changed", {"added": [str(world.other_a.user_id)], "removed": [str(world.member_a.user_id)]}, offset=1)
        with ap_db.session(world.a.ctx) as session:
            session.connection().exec_driver_sql("UPDATE t_user SET is_active = false WHERE id = %s", (world.member_a.user_id,))
            session.commit()
        body = client.get(f"{TODOS}/{todo}/activities", headers=world.other_a.headers).json()
        users = body["users"]
        check.equal(set(users), {str(world.admin_a.user_id), str(world.member_a.user_id), str(world.other_a.user_id)})
        check.equal(users[str(world.admin_a.user_id)], {"display_name": "Ada Actor", "is_active": True})
        check.equal(users[str(world.member_a.user_id)], {"display_name": "Mia Actor", "is_active": False})
        check.equal(users[str(world.other_a.user_id)], {"display_name": "Otto Actor", "is_active": True})

    def test_other_tenant_user_ids_in_payload_are_not_resolved(self, client, world, ap_db, todo):
        """payload に他テナントのユーザー ID が入っていても users に含めない(名前が漏れない)。存在しない ID・UUID でない値も無視し、取得は失敗しない。"""
        ghost = uuid.uuid4()
        self.add_activity(ap_db, world, todo, world.admin_a.user_id, "assignees_changed",
                          {"added": [str(world.member_b.user_id), str(ghost), "not-a-uuid", 123, None], "removed": [str(world.admin_b.user_id)]})
        self.add_activity(ap_db, world, todo, world.admin_a.user_id, "created", {"values": {"assignee_ids": [str(world.member_b.user_id)]}}, offset=1)
        response = client.get(f"{TODOS}/{todo}/activities", headers=world.admin_a.headers)
        check.equal(response.status_code, 200, response.text)
        body = response.json()
        check.equal(set(body["users"]), {str(world.admin_a.user_id)})
        check.is_not_in("Ben", response.text)
        check.is_not_in("Bea", response.text)
        check.equal(len(body["items"]), 2)

    def test_malformed_payloads_do_not_break_the_list(self, client, world, ap_db, todo):
        """壊れた payload(種別に合わない形・空)でも一覧は取得できる(users は操作者だけ)。"""
        self.add_activity(ap_db, world, todo, world.admin_a.user_id, "created", {"values": "oops"})
        self.add_activity(ap_db, world, todo, world.admin_a.user_id, "assignees_changed", {"added": "x", "removed": {"a": 1}}, offset=1)
        self.add_activity(ap_db, world, todo, world.admin_a.user_id, "updated", {}, offset=2)
        response = client.get(f"{TODOS}/{todo}/activities", headers=world.admin_a.headers)
        check.equal(response.status_code, 200)
        check.equal(set(response.json()["users"]), {str(world.admin_a.user_id)})

    def test_users_cover_only_the_page(self, client, world, ap_db, todo):
        """users はそのページのアクティビティが参照するユーザーだけ。次のページの参照先は、そのページで返る。"""
        self.add_activity(ap_db, world, todo, world.other_a.user_id, "updated", {}, offset=0)
        self.add_activity(ap_db, world, todo, world.admin_a.user_id, "assignees_changed", {"added": [str(world.member_a.user_id)], "removed": []}, offset=1)
        first = client.get(f"{TODOS}/{todo}/activities", headers=world.admin_a.headers, params={"limit": 1}).json()
        check.equal(set(first["users"]), {str(world.admin_a.user_id), str(world.member_a.user_id)})
        second = client.get(f"{TODOS}/{todo}/activities", headers=world.admin_a.headers, params={"limit": 1, "cursor": first["next_cursor"]}).json()
        check.equal(set(second["users"]), {str(world.other_a.user_id)})

    def test_empty_list_has_empty_users(self, client, world, todo):
        """アクティビティが無ければ users は空のオブジェクト。"""
        body = client.get(f"{TODOS}/{todo}/activities", headers=world.admin_a.headers).json()
        check.equal((body["items"], body["users"]), ([], {}))

    def test_cross_tenant_todo_is_404(self, client, world, todo):
        """他テナントの ToDo のアクティビティは 404(todo_not_found)で、users も返さない。"""
        response = client.get(f"{TODOS}/{todo}/activities", headers=world.admin_b.headers)
        check.equal((response.status_code, response.json()["code"]), (404, "todo_not_found"))
        check.is_not_in("users", response.json())

    def test_through_the_api_flow(self, client, world):
        """API で ToDo を作って担当者を入れ替えた結果のアクティビティでも、操作者・外れた担当者・追加した担当者が users に入る。"""
        created = client.post(TODOS, json={"title": "flow", "visibility": "tenant", "assignee_ids": [str(world.member_a.user_id)]}, headers=with_csrf(world.admin_a.headers))
        check.equal(created.status_code, 201, created.text)
        todo_id = created.json()["id"]
        replaced = client.put(f"{TODOS}/{todo_id}/assignees", json={"user_ids": [str(world.other_a.user_id)]}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal(replaced.status_code, 200, replaced.text)
        body = client.get(f"{TODOS}/{todo_id}/activities", headers=world.admin_a.headers).json()
        check.equal(set(body["users"]), {str(world.admin_a.user_id), str(world.member_a.user_id), str(world.other_a.user_id)})
        check.equal(set(next(iter(body["users"].values()))), {"display_name", "is_active"})
