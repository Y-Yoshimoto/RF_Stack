# -*- coding: utf-8 -*-
"""/api/v1/users(AP のユーザー管理 API。01 PF-USR-01..03、§10.2)のテスト。

- 認証・テナント判定・CSRF・ユーザーの有効確認・サービス・DB(開発 DB の ``app_db``、RLS)は実物。Keycloak だけがフェイク(``fake_idp_user_service``)。
- テナントは台帳に作る使い捨て(``ap_tenant``)。alpha / beta には触れない。AP のデータ(監査ログを含む)は終了時に削除する。
"""
import logging
import uuid

import pytest
import pytest_check as check

from .conftest import SENTINEL_TEMP_PASSWORD, with_csrf

USERS = "/api/v1/users"

pytestmark = pytest.mark.usefixtures("fake_idp_user_service")


def etag(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


@pytest.fixture
def world(ap_tenant, ap_login):
    """2 つのテナント(A / B)。それぞれ管理者(tenant_admin)を持ち、A にはメンバー(member)もいる。"""

    class World:
        a = ap_tenant()
        b = ap_tenant()

    World.admin_a = ap_login(World.a)
    World.member_a = ap_login(World.a, roles=("member",))
    World.admin_b = ap_login(World.b)
    return World


def create_user(client, actor, *, email="new.user@example.com", **overrides):
    body = {"email": email, "first_name": "New", "last_name": "User", **overrides}
    return client.post(USERS, json=body, headers=with_csrf(actor.headers))


class TestAuthorization:
    """参照はテナントの全メンバー、変更は tenant_admin のみ。"""

    def test_unauthenticated(self, client, world):
        """Cookie が無ければ 401(unauthenticated)。"""
        response = client.get(USERS)
        check.equal((response.status_code, response.json()["code"]), (401, "unauthenticated"))

    def test_cp_session_is_rejected(self, client, admin, world):
        """CP のセッションでは 401(プレーンが違う)。"""
        check.equal(client.get(USERS, headers=admin).status_code, 401)

    def test_member_can_read(self, client, world):
        """member も一覧・詳細を取得できる。"""
        listed = client.get(USERS, headers=world.member_a.headers)
        check.equal(listed.status_code, 200)
        detail = client.get(f"{USERS}/{world.admin_a.user_id}", headers=world.member_a.headers)
        check.equal(detail.status_code, 200)

    def test_member_cannot_create_or_update(self, client, world, idp):
        """member の POST / PATCH は 403(forbidden)。IdP にも AP にも何も作らない。"""
        response = create_user(client, world.member_a)
        check.equal((response.status_code, response.json()["code"]), (403, "forbidden"))
        patch = client.patch(f"{USERS}/{world.admin_a.user_id}", json={"is_active": False}, headers=with_csrf(world.member_a.headers, **etag(1)))
        check.equal(patch.status_code, 403)
        check.equal(idp.writes, [])

    def test_write_requires_csrf_headers(self, client, world, idp):
        """CSRF 対策のヘッダー(許可オリジン)が無い POST は 403 で、処理されない。"""
        response = client.post(USERS, json={"email": "x@example.com", "first_name": "X", "last_name": "Y"}, headers=world.admin_a.headers)
        check.equal(response.status_code, 403)
        check.equal(idp.writes, [])

    def test_viewer_of_another_plane_cannot_create(self, client, world, admin):
        """CP の saas_admin の Cookie では作成できない(401)。"""
        response = client.post(USERS, json={"email": "x@example.com", "first_name": "X", "last_name": "Y"}, headers=with_csrf(admin))
        check.equal(response.status_code, 401)


class TestCreate:
    """POST /api/v1/users。"""

    def test_created_response(self, client, world, idp):
        """201。Location にユーザーの URL、ETag に "1"、Cache-Control: no-store。本文は user(roles 付き)と credentials(一時パスワード)。IdP の利用者 ID は返さない。"""
        response = create_user(client, world.admin_a, roles=["member"])
        check.equal(response.status_code, 201, response.text)
        body = response.json()
        check.equal(response.headers["Location"], f"/api/v1/users/{body['user']['id']}")
        check.equal(response.headers["ETag"], '"1"')
        check.equal(response.headers["Cache-Control"], "no-store")
        check.equal(body["credentials"], {"username": "new.user@example.com", "temporary_password": SENTINEL_TEMP_PASSWORD})
        user = body["user"]
        check.equal((user["email"], user["display_name"], user["is_active"], user["version"], user["roles"], user["last_login_at"]), ("new.user@example.com", "New User", True, 1, ["member"], None))
        check.equal(set(user), {"id", "email", "display_name", "is_active", "last_login_at", "version", "created_at", "updated_at", "roles"})
        idp_user = next(u for u in idp.users(world.a.realm).values() if u["email"] == "new.user@example.com")
        check.is_not_in(idp_user["id"], response.text)
        check.equal(idp.factory_realms[-1], world.a.realm)

    def test_password_appears_only_in_the_create_response(self, client, world, ap_db, caplog):
        """一時パスワードは作成のレスポンスにだけ現れる。以降の一覧・詳細、AP の DB、ログには残らない。"""
        with caplog.at_level(logging.DEBUG):
            created = create_user(client, world.admin_a).json()
            listed = client.get(USERS, headers=world.admin_a.headers)
            detail = client.get(f"{USERS}/{created['user']['id']}", headers=world.admin_a.headers)
        check.is_not_in(SENTINEL_TEMP_PASSWORD, listed.text + detail.text)
        check.is_not_in(SENTINEL_TEMP_PASSWORD, ap_db.dump(world.a.ctx))
        check.is_not_in(SENTINEL_TEMP_PASSWORD, caplog.text)
        check.is_not_in("no-store", detail.headers.get("Cache-Control", ""))

    def test_audit_log_records_actor(self, client, world, ap_db):
        """監査ログ user.create の actor は、セッションのユーザーの t_user.id(sub ではない)。"""
        created = create_user(client, world.admin_a).json()
        audit = ap_db.audits(world.a.ctx, "user.create")
        check.equal(len(audit), 1)
        check.equal((audit[0]["actor_id"], audit[0]["target_id"]), (world.admin_a.user_id, created["user"]["id"]))

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"email": "a@example.com", "first_name": "A"},
            {"email": "a@example.com", "first_name": "", "last_name": "B"},
            {"email": "a@example.com", "first_name": "A", "last_name": "B", "roles": []},
            {"email": "a@example.com", "first_name": "A", "last_name": "B", "roles": ["saas_admin"]},
            {"email": "a@example.com", "first_name": "A", "last_name": "B", "roles": ["manage-users"]},
            {"email": "a@example.com", "first_name": "A", "last_name": "B", "roles": "member"},
        ],
    )
    def test_invalid_body_is_422(self, client, world, idp, body):
        """必須項目の欠落・空・tenant_admin / member 以外のロールは 422。IdP にも書き込まない。"""
        response = client.post(USERS, json=body, headers=with_csrf(world.admin_a.headers))
        check.equal(response.status_code, 422)
        check.equal(idp.writes, [])

    @pytest.mark.parametrize(("overrides", "code"), [({"email": "not-an-email"}, "invalid_user_input"), ({"username": "ab"}, "invalid_user_input")])
    def test_service_validation_is_422_problem(self, client, world, overrides, code):
        """サービス層の検証(メール形式・ユーザー名)の違反は 422(invalid_user_input)で、errors に項目が入る。"""
        response = create_user(client, world.admin_a, **overrides)
        body = response.json()
        check.equal((response.status_code, body["code"]), (422, code))
        check.equal(len(body["errors"]), 1)

    def test_default_role_is_member(self, client, world, idp):
        """roles を省略すると member。"""
        body = create_user(client, world.admin_a).json()
        check.equal(body["user"]["roles"], ["member"])

    def test_duplicate_email_is_409(self, client, world):
        """テナント内で同じメール(大文字小文字を区別しない)は 409(user_already_exists)。"""
        check.equal(create_user(client, world.admin_a, email="dup@example.com").status_code, 201)
        response = create_user(client, world.admin_a, email="DUP@example.com", username="other-name")
        check.equal((response.status_code, response.json()["code"]), (409, "user_already_exists"))

    def test_same_email_in_other_tenant_is_allowed(self, client, world):
        """別テナントで同じメールのユーザーを作れる(PF-USR-06)。"""
        check.equal(create_user(client, world.admin_a, email="same@example.com").status_code, 201)
        check.equal(create_user(client, world.admin_b, email="same@example.com").status_code, 201)

    def test_idp_failure_is_502_without_details(self, client, world, idp, ap_db):
        """認証基盤の失敗は 502(identity_provider_operation_failed)。内部の要約・Keycloak の応答を返さず、AP にはユーザーを作らない。"""
        idp.fail("POST", r"/users$", 500)
        response = create_user(client, world.admin_a)
        check.equal((response.status_code, response.json()["code"]), (502, "identity_provider_operation_failed"))
        for hidden in ("KeycloakAdminError", "http_status", "injected", SENTINEL_TEMP_PASSWORD):
            check.is_not_in(hidden, response.text)
        check.equal(len(ap_db.users(world.a.ctx)), 2)  # 管理者とメンバー


class TestGetAndList:
    """GET /api/v1/users、/api/v1/users/{id}。"""

    def test_detail_has_etag_and_roles(self, client, world):
        """詳細は ETag(version)とロール付き。admin は tenant_admin と(既定ロールの)member を持つ。"""
        response = client.get(f"{USERS}/{world.admin_a.user_id}", headers=world.member_a.headers)
        body = response.json()
        check.equal((response.status_code, response.headers["ETag"], body["version"]), (200, '"1"', 1))
        check.equal(body["roles"], ["tenant_admin", "member"])
        check.equal(body["id"], str(world.admin_a.user_id))
        check.is_not_in("idp_subject", response.text)
        check.is_not_in(world.admin_a.sub, response.text)

    def test_list_does_not_include_roles(self, client, world):
        """一覧の要素にはロールを含めない。自テナントの 2 人だけ(管理者・メンバー)。"""
        body = client.get(USERS, headers=world.admin_a.headers).json()
        check.equal(sorted(i["id"] for i in body["items"]), sorted([str(world.admin_a.user_id), str(world.member_a.user_id)]))
        check.is_true(all("roles" not in item for item in body["items"]))
        check.is_none(body["next_cursor"])

    def test_cursor_pagination_has_no_gaps_or_duplicates(self, client, world):
        """limit=2 でカーソルを辿ると、全ユーザーが重複・欠落なく並ぶ(sort 指定ごと)。"""
        for i in range(4):
            check.equal(create_user(client, world.admin_a, email=f"u{i}@example.com").status_code, 201)
        for sort in ("display_name", "-display_name", "created_at", "-created_at"):
            seen, cursor = [], None
            for _ in range(10):
                params = {"limit": 2, "sort": sort, **({"cursor": cursor} if cursor else {})}
                body = client.get(USERS, headers=world.admin_a.headers, params=params).json()
                seen.extend(item["id"] for item in body["items"])
                cursor = body["next_cursor"]
                if cursor is None:
                    break
            check.equal(len(seen), 6, sort)
            check.equal(len(set(seen)), 6, sort)

    def test_is_active_filter(self, client, world):
        """is_active で絞り込める。"""
        created = create_user(client, world.admin_a, email="off@example.com").json()["user"]
        patch = client.patch(f"{USERS}/{created['id']}", json={"is_active": False}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal(patch.status_code, 200, patch.text)
        off = client.get(USERS, headers=world.admin_a.headers, params={"is_active": "false"}).json()["items"]
        on = client.get(USERS, headers=world.admin_a.headers, params={"is_active": "true"}).json()["items"]
        check.equal([i["id"] for i in off], [created["id"]])
        check.is_not_in(created["id"], [i["id"] for i in on])

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"sort": "email"}, {"cursor": "garbage"}, {"is_active": "maybe"}])
    def test_invalid_query_is_422(self, client, world, params):
        """limit の範囲外・許可していない sort・壊れたカーソル・不正な真偽値は 422。"""
        check.equal(client.get(USERS, headers=world.admin_a.headers, params=params).status_code, 422)

    def test_cursor_for_other_sort_is_422(self, client, world):
        """別の sort で作ったカーソルは 422(並び替えの指定が違う)。"""
        create_user(client, world.admin_a, email="x1@example.com")
        first = client.get(USERS, headers=world.admin_a.headers, params={"limit": 1, "sort": "display_name"}).json()
        check.is_not_none(first["next_cursor"])
        response = client.get(USERS, headers=world.admin_a.headers, params={"limit": 1, "sort": "-display_name", "cursor": first["next_cursor"]})
        check.equal(response.status_code, 422)

    def test_unknown_user_is_404(self, client, world):
        """存在しない ID は 404(user_not_found)。形式が不正な ID は 422。"""
        response = client.get(f"{USERS}/{uuid.uuid4()}", headers=world.admin_a.headers)
        check.equal((response.status_code, response.json()["code"]), (404, "user_not_found"))
        check.equal(client.get(f"{USERS}/not-a-uuid", headers=world.admin_a.headers).status_code, 422)

    def test_idp_failure_on_roles_is_502(self, client, world, idp):
        """詳細のロール取得で IdP が失敗したら 502。"""
        idp.fail("GET", r"/role-mappings/realm/composite$", 500)
        response = client.get(f"{USERS}/{world.member_a.user_id}", headers=world.admin_a.headers)
        check.equal((response.status_code, response.json()["code"]), (502, "identity_provider_operation_failed"))


class TestUpdate:
    """PATCH /api/v1/users/{id}。"""

    def test_if_match_is_required(self, client, world):
        """If-Match が無ければ 428(precondition_required)。形式が不正なら 400。"""
        url = f"{USERS}/{world.member_a.user_id}"
        missing = client.patch(url, json={"is_active": False}, headers=with_csrf(world.admin_a.headers))
        check.equal((missing.status_code, missing.json()["code"]), (428, "precondition_required"))
        bad = client.patch(url, json={"is_active": False}, headers=with_csrf(world.admin_a.headers, **{"If-Match": "*"}))
        check.equal(bad.status_code, 400)

    def test_stale_version_is_412(self, client, world, ap_db):
        """version が違えば 412(user_version_conflict)で、変更しない。"""
        response = client.patch(f"{USERS}/{world.member_a.user_id}", json={"is_active": False}, headers=with_csrf(world.admin_a.headers, **etag(5)))
        check.equal((response.status_code, response.json()["code"]), (412, "user_version_conflict"))
        check.is_true(ap_db.user(world.a.ctx, world.member_a.user_id)["is_active"])

    def test_update_names_and_etag(self, client, world, idp):
        """姓・名を更新すると 200、ETag と version が +1、display_name が変わる。ロールは本文に含まない。IdP の姓・名も変わる。"""
        url = f"{USERS}/{world.member_a.user_id}"
        response = client.patch(url, json={"first_name": "Grace", "last_name": "Hopper"}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        body = response.json()
        check.equal((response.status_code, response.headers["ETag"], body["version"], body["display_name"]), (200, '"2"', 2, "Grace Hopper"))
        check.is_not_in("roles", body)
        check.equal(idp.users(world.a.realm)[world.member_a.sub]["firstName"], "Grace")
        again = client.patch(url, json={"first_name": "G", "last_name": "H"}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal(again.status_code, 412)

    def test_update_roles(self, client, world):
        """ロールを置き換えると、詳細で反映を確認できる。"""
        url = f"{USERS}/{world.member_a.user_id}"
        response = client.patch(url, json={"roles": ["tenant_admin"]}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal(response.status_code, 200)
        check.equal(client.get(url, headers=world.admin_a.headers).json()["roles"], ["tenant_admin", "member"])

    @pytest.mark.parametrize(
        "body",
        [{}, {"first_name": None}, {"is_active": None}, {"roles": None}, {"roles": []}, {"roles": ["saas_admin"]}, {"first_name": "OnlyFirst"}, {"is_active": "yes please"}],
    )
    def test_invalid_body_is_422(self, client, world, body):
        """null の明示・空のロール・許可外のロール・姓名の片方だけ・真偽値でない値は 422(空のボディ {} は変更なしで 200)。"""
        response = client.patch(f"{USERS}/{world.member_a.user_id}", json=body, headers=with_csrf(world.admin_a.headers, **etag(1)))
        expected = 200 if body == {} else 422
        check.equal(response.status_code, expected, response.text)

    def test_self_deactivation_is_409(self, client, world, ap_db):
        """自分自身の無効化は 409(user_self_modification_forbidden、operation=deactivate)。"""
        response = client.patch(f"{USERS}/{world.admin_a.user_id}", json={"is_active": False}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        body = response.json()
        check.equal((response.status_code, body["code"], body["operation"]), (409, "user_self_modification_forbidden", "deactivate"))
        check.is_true(ap_db.user(world.a.ctx, world.admin_a.user_id)["is_active"])

    def test_removing_own_admin_role_is_409(self, client, world):
        """自分の tenant_admin を外す更新は 409(operation=remove_tenant_admin)。"""
        response = client.patch(f"{USERS}/{world.admin_a.user_id}", json={"roles": ["member"]}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal((response.status_code, response.json()["operation"]), (409, "remove_tenant_admin"))

    def test_idp_failure_is_502_and_not_applied(self, client, world, idp, ap_db):
        """認証基盤の失敗は 502。AP の行は変わらない。"""
        idp.fail("PUT", r"/users/[^/]+$", 500)
        response = client.patch(f"{USERS}/{world.member_a.user_id}", json={"first_name": "A", "last_name": "B"}, headers=with_csrf(world.admin_a.headers, **etag(1)))
        check.equal((response.status_code, response.json()["code"]), (502, "identity_provider_operation_failed"))
        check.equal(ap_db.user(world.a.ctx, world.member_a.user_id)["version"], 1)


class TestCrossTenant:
    """テナント分離(tenant-isolation §5.1)を、実際のサービス・DB(RLS)で確認する。"""

    @pytest.fixture
    def foreign(self, client, world):
        """テナント B に作ったユーザー(B の管理者が作成)。"""
        return create_user(client, world.admin_b, email="foreign@example.com").json()["user"]

    def test_get_other_tenant_user_is_404(self, client, world, foreign):
        """A の管理者が B のユーザーを ID 指定で取得すると、存在しない ID と同じ 404(user_not_found)。"""
        mine = client.get(f"{USERS}/{uuid.uuid4()}", headers=world.admin_a.headers)
        theirs = client.get(f"{USERS}/{foreign['id']}", headers=world.admin_a.headers)
        check.equal((theirs.status_code, theirs.json()["code"]), (404, "user_not_found"))
        check.equal({k: v for k, v in theirs.json().items() if k not in ("request_id", "instance")}, {k: v for k, v in mine.json().items() if k not in ("request_id", "instance")})
        check.is_not_in("foreign@example.com", theirs.text)

    def test_update_other_tenant_user_is_404_and_untouched(self, client, world, foreign, idp, ap_db):
        """A の管理者が B のユーザーを更新・無効化・ロール変更しようとすると 404。B のユーザー(AP・IdP)は変わらない。"""
        snapshot = idp.snapshot()
        for body in ({"first_name": "Hacked", "last_name": "Name"}, {"is_active": False}, {"roles": ["tenant_admin"]}):
            response = client.patch(f"{USERS}/{foreign['id']}", json=body, headers=with_csrf(world.admin_a.headers, **etag(1)))
            check.equal((response.status_code, response.json()["code"]), (404, "user_not_found"))
        row = ap_db.user(world.b.ctx, uuid.UUID(foreign["id"]))
        check.equal((row["display_name"], row["is_active"], row["version"]), ("New User", True, 1))
        check.equal(idp.snapshot(), snapshot)

    def test_list_never_includes_other_tenant(self, client, world, foreign):
        """一覧(is_active 絞り込み・ページング込み)に、B のユーザーは現れない。"""
        for params in ({}, {"limit": 1}, {"is_active": "true"}, {"sort": "-created_at"}):
            body = client.get(USERS, headers=world.admin_a.headers, params=params).json()
            check.is_not_in(foreign["id"], [item["id"] for item in body["items"]])
            check.is_not_in("foreign@example.com", str(body))
        b_list = client.get(USERS, headers=world.admin_b.headers).json()["items"]
        check.is_in(foreign["id"], [item["id"] for item in b_list])

    def test_tenant_id_in_body_and_query_is_ignored(self, client, world, ap_db):
        """リクエストのボディ・クエリ・ヘッダーに B の tenant_id を混ぜても無視され、A のユーザーとして作成される。"""
        response = client.post(
            USERS,
            json={"email": "mixed@example.com", "first_name": "M", "last_name": "X", "tenant_id": str(world.b.id), "tenant_code": world.b.code},
            params={"tenant_id": str(world.b.id)},
            headers=with_csrf(world.admin_a.headers, **{"X-Tenant-ID": str(world.b.id)}),
        )
        check.equal(response.status_code, 201, response.text)
        check.equal([u["email"] for u in ap_db.users(world.a.ctx) if u["email"] == "mixed@example.com"], ["mixed@example.com"])
        check.equal([u["email"] for u in ap_db.users(world.b.ctx) if u["email"] == "mixed@example.com"], [])

    def test_session_of_a_cannot_touch_realm_of_b(self, client, world, idp):
        """A のセッションの操作では、IdP は A のレルムにしか接続しない(B のレルムの名前を使わない)。"""
        create_user(client, world.admin_a, email="only-a@example.com")
        client.get(f"{USERS}/{world.member_a.user_id}", headers=world.admin_a.headers)
        check.equal(set(idp.factory_realms), {world.a.realm})
        check.is_none(idp.user_by_email(world.b.realm, "only-a@example.com"))

    def test_deactivation_of_b_user_does_not_affect_a(self, client, world, foreign):
        """B の管理者が B のユーザーを無効化しても、A の一覧・A のユーザーの状態は変わらない。"""
        response = client.patch(f"{USERS}/{foreign['id']}", json={"is_active": False}, headers=with_csrf(world.admin_b.headers, **etag(1)))
        check.equal(response.status_code, 200, response.text)
        a_items = client.get(USERS, headers=world.admin_a.headers).json()["items"]
        check.is_true(all(item["is_active"] for item in a_items))
