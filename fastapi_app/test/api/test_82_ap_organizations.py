# -*- coding: utf-8 -*-
"""/api/v1/organizations(AP の組織管理 API。01 PF-ORG-01..03、§10.2)のテスト。

認証・テナント判定・CSRF・ユーザーの有効確認・サービス・DB(開発 DB の ``app_db``、RLS)はすべて実物(Keycloak は使わない)。
テナントは台帳に作る使い捨て(``ap_tenant``)。alpha / beta には触れない。AP のデータ(監査ログを含む)は終了時に削除する。
"""
import uuid

import pytest
import pytest_check as check

from .conftest import with_csrf

ORGS = "/api/v1/organizations"

pytestmark = pytest.mark.usefixtures("real_active_user")


def etag(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


@pytest.fixture
def world(ap_tenant, ap_login):
    """2 つのテナント(A / B)。A には管理者とメンバー、B には管理者がいる。"""

    class World:
        a = ap_tenant()
        b = ap_tenant()

    World.admin_a = ap_login(World.a)
    World.member_a = ap_login(World.a, roles=("member",))
    World.admin_b = ap_login(World.b)
    return World


def create_org(client, actor, name="開発部"):
    return client.post(ORGS, json={"name": name}, headers=with_csrf(actor.headers))


class TestAuthorization:
    """参照は全メンバー、変更は tenant_admin のみ。"""

    def test_unauthenticated(self, client, world):
        """Cookie が無ければ 401。"""
        check.equal(client.get(ORGS).status_code, 401)

    def test_cp_session_is_rejected(self, client, admin, world):
        """CP のセッションでは 401。"""
        check.equal(client.get(ORGS, headers=admin).status_code, 401)

    def test_member_can_read_but_not_write(self, client, world, ap_db):
        """member は一覧・詳細を取得できるが、作成・更新・削除・メンバー置き換えは 403。何も変わらない。"""
        org = ap_db.add_org(world.a.ctx, "開発部")
        member = world.member_a.headers
        check.equal(client.get(ORGS, headers=member).status_code, 200)
        check.equal(client.get(f"{ORGS}/{org.id}", headers=member).status_code, 200)
        check.equal((create_org(client, world.member_a, "x").status_code), 403)
        check.equal(client.patch(f"{ORGS}/{org.id}", json={"name": "y"}, headers=with_csrf(member, **etag(1))).status_code, 403)
        check.equal(client.delete(f"{ORGS}/{org.id}", headers=with_csrf(member, **etag(1))).status_code, 403)
        check.equal(client.put(f"{ORGS}/{org.id}/members", json={"user_ids": []}, headers=with_csrf(member, **etag(1))).status_code, 403)
        row = ap_db.orgs(world.a.ctx)[0]
        check.equal((row["name"], row["version"], row["deleted_at"]), ("開発部", 1, None))

    def test_write_requires_csrf_headers(self, client, world, ap_db):
        """CSRF 対策のヘッダーが無い変更系は 403 で、処理されない。"""
        response = client.post(ORGS, json={"name": "x"}, headers=world.admin_a.headers)
        check.equal(response.status_code, 403)
        check.equal(ap_db.orgs(world.a.ctx), [])


class TestCrud:
    """作成・取得・更新・削除。"""

    def test_create(self, client, world):
        """201。Location に組織の URL、ETag は "1"、本文は組織(member_ids は空)。"""
        response = create_org(client, world.admin_a, " 開発部 ")
        body = response.json()
        check.equal(response.status_code, 201, response.text)
        check.equal((response.headers["Location"], response.headers["ETag"]), (f"/api/v1/organizations/{body['id']}", '"1"'))
        check.equal((body["name"], body["version"], body["member_ids"]), ("開発部", 1, []))
        check.equal(set(body), {"id", "name", "version", "created_at", "updated_at", "member_ids"})

    @pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "x" * 101}, {"name": None}, {"name": 5}])
    def test_create_invalid_is_422(self, client, world, body):
        """名前の欠落・空・長すぎる・型違いは 422。"""
        check.equal(client.post(ORGS, json=body, headers=with_csrf(world.admin_a.headers)).status_code, 422)

    def test_create_whitespace_name_is_422_problem(self, client, world):
        """空白だけの名前は 422(invalid_organization_input)。"""
        response = create_org(client, world.admin_a, "   ")
        check.equal((response.status_code, response.json()["code"]), (422, "invalid_organization_input"))

    def test_duplicate_name_is_409_case_insensitive(self, client, world):
        """有効な組織と同じ名前(大文字小文字を区別しない)は 409(organization_name_already_exists)。"""
        create_org(client, world.admin_a, "Dev")
        response = create_org(client, world.admin_a, "DEV")
        check.equal((response.status_code, response.json()["code"]), (409, "organization_name_already_exists"))

    def test_get_has_etag_and_members(self, client, world, ap_db):
        """詳細は ETag とメンバーの ID(ID 順)付き。"""
        u1, u2 = world.admin_a.user_id, world.member_a.user_id
        org = ap_db.add_org(world.a.ctx, "開発部", members=(u1, u2))
        response = client.get(f"{ORGS}/{org.id}", headers=world.member_a.headers)
        check.equal((response.status_code, response.headers["ETag"]), (200, '"1"'))
        check.equal(response.json()["member_ids"], sorted([str(u1), str(u2)]))

    def test_update_requires_if_match(self, client, world, ap_db):
        """PATCH は If-Match 必須(無ければ 428、版が違えば 412、形式不正は 400)。"""
        org = ap_db.add_org(world.a.ctx, "開発部")
        url = f"{ORGS}/{org.id}"
        headers = with_csrf(world.admin_a.headers)
        check.equal(client.patch(url, json={"name": "x"}, headers=headers).status_code, 428)
        check.equal(client.patch(url, json={"name": "x"}, headers={**headers, "If-Match": "abc"}).status_code, 400)
        stale = client.patch(url, json={"name": "x"}, headers={**headers, **etag(4)})
        check.equal((stale.status_code, stale.json()["code"]), (412, "organization_version_conflict"))
        check.equal(ap_db.orgs(world.a.ctx)[0]["name"], "開発部")

    def test_update_name(self, client, world):
        """名前を変更すると 200、ETag と version が +1。古い版での再更新は 412。"""
        org = create_org(client, world.admin_a, "旧名").json()
        url = f"{ORGS}/{org['id']}"
        response = client.patch(url, json={"name": "新名"}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal((response.status_code, response.headers["ETag"], response.json()["name"], response.json()["version"]), (200, '"2"', "新名", 2))
        check.equal(client.patch(url, json={"name": "他"}, headers=with_csrf(world.admin_a.headers, **etag(1))).status_code, 412)

    def test_update_to_existing_name_is_409(self, client, world):
        """別の有効な組織の名前への変更は 409。"""
        create_org(client, world.admin_a, "営業部")
        org = create_org(client, world.admin_a, "開発部").json()
        response = client.patch(f"{ORGS}/{org['id']}", json={"name": "営業部"}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal((response.status_code, response.json()["code"]), (409, "organization_name_already_exists"))

    def test_delete_is_soft_and_returns_204(self, client, world, ap_db):
        """DELETE は 204(本文なし)。論理削除で、以降の取得・更新・再削除・メンバー置き換えは 404。一覧にも出ない。行は DB に残る。"""
        org = create_org(client, world.admin_a).json()
        url = f"{ORGS}/{org['id']}"
        deleted = client.delete(url, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal((deleted.status_code, deleted.content), (204, b""))
        headers = with_csrf(world.admin_a.headers, **etag(2))
        check.equal(client.get(url, headers=world.admin_a.headers).status_code, 404)
        check.equal(client.patch(url, json={"name": "x"}, headers=headers).status_code, 404)
        check.equal(client.delete(url, headers=headers).status_code, 404)
        check.equal(client.put(f"{url}/members", json={"user_ids": []}, headers=headers).status_code, 404)
        check.equal(client.get(ORGS, headers=world.admin_a.headers).json()["items"], [])
        rows = ap_db.orgs(world.a.ctx)
        check.equal(len(rows), 1)
        check.is_not_none(rows[0]["deleted_at"])

    def test_delete_requires_if_match(self, client, world):
        """DELETE も If-Match 必須(428 / 412)。"""
        org = create_org(client, world.admin_a).json()
        url = f"{ORGS}/{org['id']}"
        check.equal(client.delete(url, headers=with_csrf(world.admin_a.headers)).status_code, 428)
        check.equal(client.delete(url, headers=with_csrf(world.admin_a.headers, **etag(3))).status_code, 412)
        check.equal(client.get(url, headers=world.admin_a.headers).status_code, 200)

    def test_name_can_be_reused_after_delete(self, client, world):
        """削除した組織の名前で新しい組織を作れる。"""
        org = create_org(client, world.admin_a, "再利用").json()
        client.delete(f"{ORGS}/{org['id']}", headers=with_csrf(world.admin_a.headers, **etag(1)))
        again = create_org(client, world.admin_a, "再利用")
        check.equal(again.status_code, 201)
        check.not_equal(again.json()["id"], org["id"])

    def test_unknown_id_is_404_and_malformed_is_422(self, client, world):
        """存在しない ID は 404(organization_not_found)、UUID でない値は 422。"""
        response = client.get(f"{ORGS}/{uuid.uuid4()}", headers=world.admin_a.headers)
        check.equal((response.status_code, response.json()["code"]), (404, "organization_not_found"))
        check.equal(client.get(f"{ORGS}/xyz", headers=world.admin_a.headers).status_code, 422)


class TestMembers:
    """PUT /api/v1/organizations/{id}/members(全置換)。"""

    def test_replace_members(self, client, world):
        """メンバーを置き換えると 200、ETag と version が +1、member_ids に反映される(ID 順)。"""
        org = create_org(client, world.admin_a).json()
        ids = [str(world.admin_a.user_id), str(world.member_a.user_id)]
        response = client.put(f"{ORGS}/{org['id']}/members", json={"user_ids": ids}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        body = response.json()
        check.equal((response.status_code, response.headers["ETag"], body["version"]), (200, '"2"', 2))
        check.equal(body["member_ids"], sorted(ids))
        again = client.put(f"{ORGS}/{org['id']}/members", json={"user_ids": ids}, headers=with_csrf(world.admin_a.headers, **etag(2)))
        check.equal((again.status_code, again.json()["version"]), (200, 2))
        cleared = client.put(f"{ORGS}/{org['id']}/members", json={"user_ids": []}, headers=with_csrf(world.admin_a.headers, **etag(2)))
        check.equal((cleared.json()["member_ids"], cleared.json()["version"]), ([], 3))

    def test_me_lists_own_active_organizations(self, client, world):
        """/me の organizations は所属する有効な組織(組織名順)。論理削除した組織は含まない。"""
        first, second = create_org(client, world.admin_a, "Bravo").json(), create_org(client, world.admin_a, "Alpha").json()
        for org in (first, second):
            client.put(f"{ORGS}/{org['id']}/members", json={"user_ids": [str(world.member_a.user_id)]}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        listed = client.get("/api/v1/me", headers=world.member_a.headers).json()["organizations"]
        check.equal(listed, [{"id": second["id"], "name": "Alpha"}, {"id": first["id"], "name": "Bravo"}])
        client.delete(f"{ORGS}/{second['id']}", headers=with_csrf(world.admin_a.headers, **etag(2)))
        check.equal([o["name"] for o in client.get("/api/v1/me", headers=world.member_a.headers).json()["organizations"]], ["Bravo"])

    def test_requires_if_match(self, client, world):
        """If-Match が無ければ 428、版が違えば 412。"""
        org = create_org(client, world.admin_a).json()
        url = f"{ORGS}/{org['id']}/members"
        check.equal(client.put(url, json={"user_ids": []}, headers=with_csrf(world.admin_a.headers)).status_code, 428)
        check.equal(client.put(url, json={"user_ids": []}, headers=with_csrf(world.admin_a.headers, **etag(9))).status_code, 412)

    @pytest.mark.parametrize("body", [{}, {"user_ids": "x"}, {"user_ids": ["not-a-uuid"]}, {"user_ids": None}])
    def test_invalid_body_is_422(self, client, world, body):
        """user_ids の欠落・型違い・UUID でない値は 422。"""
        org = create_org(client, world.admin_a).json()
        response = client.put(f"{ORGS}/{org['id']}/members", json=body, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal(response.status_code, 422)

    def test_unknown_user_is_422_with_ids(self, client, world):
        """テナント内に存在しないユーザーは 422(invalid_organization_members)。存在しない ID が user_ids に入り、メンバーは変わらない。"""
        org = create_org(client, world.admin_a).json()
        ghost = str(uuid.uuid4())
        response = client.put(f"{ORGS}/{org['id']}/members", json={"user_ids": [str(world.admin_a.user_id), ghost]}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        body = response.json()
        check.equal((response.status_code, body["code"], body["user_ids"]), (422, "invalid_organization_members", [ghost]))
        check.equal(client.get(f"{ORGS}/{org['id']}", headers=world.admin_a.headers).json()["member_ids"], [])


class TestListAndPagination:
    """GET /api/v1/organizations。"""

    def test_cursor_pagination(self, client, world):
        """limit=2 でカーソルを辿ると、全組織が重複・欠落なく並ぶ(sort ごと)。論理削除済みは含まない。"""
        for i in range(5):
            create_org(client, world.admin_a, f"org-{i}")
        gone = create_org(client, world.admin_a, "gone").json()
        client.delete(f"{ORGS}/{gone['id']}", headers=with_csrf(world.admin_a.headers, **etag(1)))
        for sort in ("name", "-name", "created_at", "-created_at"):
            seen, cursor = [], None
            for _ in range(10):
                params = {"limit": 2, "sort": sort, **({"cursor": cursor} if cursor else {})}
                body = client.get(ORGS, headers=world.admin_a.headers, params=params).json()
                seen.extend(item["name"] for item in body["items"])
                cursor = body["next_cursor"]
                if cursor is None:
                    break
            check.equal(sorted(seen), [f"org-{i}" for i in range(5)], sort)
            check.is_true(all("member_ids" not in item for item in body["items"]))

    def test_sort_order(self, client, world):
        """name の昇順・降順で並ぶ。"""
        for name in ("b", "c", "a"):
            create_org(client, world.admin_a, name)
        asc = [i["name"] for i in client.get(ORGS, headers=world.admin_a.headers, params={"sort": "name"}).json()["items"]]
        desc = [i["name"] for i in client.get(ORGS, headers=world.admin_a.headers, params={"sort": "-name"}).json()["items"]]
        check.equal((asc, desc), (["a", "b", "c"], ["c", "b", "a"]))

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"sort": "version"}, {"cursor": "garbage"}])
    def test_invalid_query_is_422(self, client, world, params):
        """limit の範囲外・許可していない sort・壊れたカーソルは 422。"""
        check.equal(client.get(ORGS, headers=world.admin_a.headers, params=params).status_code, 422)


class TestCrossTenant:
    """テナント分離(tenant-isolation §5.1)を、実際のサービス・DB(RLS)で確認する。"""

    @pytest.fixture
    def foreign(self, client, world):
        """テナント B に作った組織(メンバー付き)。"""
        org = create_org(client, world.admin_b, "他社の組織").json()
        response = client.put(f"{ORGS}/{org['id']}/members", json={"user_ids": [str(world.admin_b.user_id)]}, headers=with_csrf(world.admin_b.headers, **etag(1)))
        assert response.status_code == 200, response.text
        return response.json()

    def test_get_other_tenant_organization_is_404(self, client, world, foreign):
        """A の管理者が B の組織を ID 指定で取得すると、存在しない ID と同じ 404。"""
        response = client.get(f"{ORGS}/{foreign['id']}", headers=world.admin_a.headers)
        missing = client.get(f"{ORGS}/{uuid.uuid4()}", headers=world.admin_a.headers)
        check.equal((response.status_code, response.json()["code"]), (404, "organization_not_found"))
        check.equal(response.json()["detail"], missing.json()["detail"])
        check.is_not_in("他社の組織", response.text)

    def test_write_to_other_tenant_organization_is_404_and_untouched(self, client, world, foreign, ap_db):
        """A の管理者が B の組織を更新・削除・メンバー置き換えしようとすると 404。B の組織(名前・版・所属・削除状態)は変わらない。"""
        url = f"{ORGS}/{foreign['id']}"
        headers = with_csrf(world.admin_a.headers, **etag(foreign["version"]))
        check.equal(client.patch(url, json={"name": "乗っ取り"}, headers=headers).status_code, 404)
        check.equal(client.delete(url, headers=headers).status_code, 404)
        check.equal(client.put(f"{url}/members", json={"user_ids": []}, headers=headers).status_code, 404)
        row = ap_db.orgs(world.b.ctx)[0]
        check.equal((row["name"], row["version"], row["deleted_at"]), ("他社の組織", foreign["version"], None))
        check.equal(ap_db.members(world.b.ctx, uuid.UUID(foreign["id"])), [world.admin_b.user_id])

    def test_list_never_includes_other_tenant(self, client, world, foreign):
        """A の一覧に B の組織は現れない(ページング・並び替え込み)。"""
        create_org(client, world.admin_a, "自社の組織")
        for params in ({}, {"limit": 1}, {"sort": "-name"}):
            body = client.get(ORGS, headers=world.admin_a.headers, params=params).json()
            check.is_not_in(foreign["id"], [item["id"] for item in body["items"]])
            check.is_not_in("他社の組織", str(body))
        check.equal([i["name"] for i in client.get(ORGS, headers=world.admin_b.headers).json()["items"]], ["他社の組織"])

    def test_cannot_attach_other_tenant_user_as_member(self, client, world, ap_db):
        """A の組織のメンバーに B のユーザーを指定すると 422(invalid_organization_members)。B のユーザー ID が含まれていたことを明かさず、所属は作られない。"""
        org = create_org(client, world.admin_a).json()
        response = client.put(f"{ORGS}/{org['id']}/members", json={"user_ids": [str(world.admin_b.user_id)]}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal((response.status_code, response.json()["code"]), (422, "invalid_organization_members"))
        check.equal(ap_db.members(world.a.ctx, uuid.UUID(org["id"])), [])
        check.equal(ap_db.rows(world.b.ctx, "SELECT * FROM t_organization_member"), [])

    def test_cannot_attach_own_user_to_other_tenant_organization(self, client, world, foreign):
        """逆方向: A の管理者が B の組織に A のユーザーを関連付けようとしても 404(B の組織は見えない)。"""
        response = client.put(f"{ORGS}/{foreign['id']}/members", json={"user_ids": [str(world.admin_a.user_id)]}, headers=with_csrf(world.admin_a.headers, **etag(foreign["version"])))
        check.equal(response.status_code, 404)

    def test_tenant_id_in_body_is_ignored(self, client, world, ap_db):
        """リクエストのボディ・クエリに B の tenant_id を混ぜても無視され、A の組織として作られる。"""
        response = client.post(
            ORGS,
            json={"name": "混入", "tenant_id": str(world.b.id), "tenant_code": world.b.code},
            params={"tenant_id": str(world.b.id)},
            headers=with_csrf(world.admin_a.headers, **{"X-Tenant-ID": str(world.b.id)}),
        )
        check.equal(response.status_code, 201, response.text)
        check.equal([o["name"] for o in ap_db.orgs(world.a.ctx)], ["混入"])
        check.equal(ap_db.orgs(world.b.ctx), [])

    def test_same_name_in_both_tenants(self, client, world):
        """別テナントの同名の組織を作れる(一意性はテナント内)。"""
        check.equal(create_org(client, world.admin_a, "共通名").status_code, 201)
        check.equal(create_org(client, world.admin_b, "共通名").status_code, 201)
