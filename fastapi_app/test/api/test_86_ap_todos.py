# -*- coding: utf-8 -*-
"""/api/v1/todos(ToDo API。docs/spec/ToDoApp.md §6、§9.5)のテスト。

認証・テナント判定・CSRF・ユーザーの有効確認・``TodoService``・DB(開発 DB の ``app_db``、RLS)はすべて実物(Keycloak は使わない)。
テナントは台帳に作る使い捨て(``ap_tenant``)で、alpha / beta には触れない。AP のデータ(アクティビティ・監査ログを含む)は終了時に削除する。
"""
import base64
import datetime as dt
import json
import uuid

import pytest
import pytest_check as check
from todos.conftest import TodoFactory

from .conftest import with_csrf

TODOS = "/api/v1/todos"

pytestmark = pytest.mark.usefixtures("real_active_user")


def etag(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


class Api:
    """リクエストの補助。"""

    def __init__(self, client) -> None:
        self.client = client

    def get(self, actor, path="", **params):
        return self.client.get(f"{TODOS}{path}", headers=actor.headers, params=params)

    def post(self, actor, body, **kwargs):
        return self.client.post(TODOS, json=body, headers=with_csrf(actor.headers), **kwargs)

    def patch(self, actor, todo_id, body, version=1):
        headers = with_csrf(actor.headers, **(etag(version) if version is not None else {}))
        return self.client.patch(f"{TODOS}/{todo_id}", json=body, headers=headers)

    def delete(self, actor, todo_id, version=1):
        headers = with_csrf(actor.headers, **(etag(version) if version is not None else {}))
        return self.client.delete(f"{TODOS}/{todo_id}", headers=headers)

    def assignees(self, actor, todo_id, user_ids, version=1):
        headers = with_csrf(actor.headers, **(etag(version) if version is not None else {}))
        return self.client.put(f"{TODOS}/{todo_id}/assignees", json={"user_ids": [str(u) for u in user_ids]}, headers=headers)


@pytest.fixture
def api(client) -> Api:
    return Api(client)


@pytest.fixture
def world(ap_tenant, ap_login, ap_db):
    """テナント A(管理者・作成者・担当者・組織 O1 の所属者 m1・組織に属さない outsider・無効化されたユーザー)とテナント B(管理者)。"""

    class World:
        a = ap_tenant()
        b = ap_tenant()

    World.admin = ap_login(World.a, name="Admin")
    World.creator = ap_login(World.a, roles=("member",), name="Creator")
    World.assignee = ap_login(World.a, roles=("member",), name="Assignee")
    World.m1 = ap_login(World.a, roles=("member",), name="M1")
    World.outsider = ap_login(World.a, roles=("member",), name="Outsider")
    World.b_admin = ap_login(World.b, name="BAdmin")
    World.inactive_id = ap_db.add_user(World.a.ctx, is_active=False).id
    World.o1 = ap_db.add_org(World.a.ctx, "Org One", members=(World.m1.user_id,)).id
    World.o3 = ap_db.add_org(World.a.ctx, "Org Deleted", deleted=True).id
    World.b_org = ap_db.add_org(World.b.ctx, "B Org").id
    World.factory = TodoFactory(ap_db)
    return World


def problem_errors(response) -> list[tuple[str, str]]:
    return [(e["field"], e["code"]) for e in response.json()["errors"]]


class TestAuthorization:
    """認証・CSRF・ロール。"""

    def test_unauthenticated_and_wrong_plane(self, api, world, admin):
        """Cookie が無ければ 401、CP のセッションでも 401。"""
        check.equal(api.client.get(TODOS).status_code, 401)
        check.equal(api.client.get(TODOS, headers=admin).status_code, 401)
        check.equal(api.client.get(f"{TODOS}/{uuid.uuid4()}", headers=admin).status_code, 401)

    def test_write_requires_csrf(self, api, world):
        """CSRF 対策のヘッダーが無い変更系は 403 で、処理されない。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id)
        headers = {**world.creator.headers, **etag(1)}
        check.equal(api.client.post(TODOS, json={"title": "x"}, headers=world.creator.headers).status_code, 403)
        check.equal(api.client.patch(f"{TODOS}/{todo_id}", json={"title": "x"}, headers=headers).status_code, 403)
        check.equal(api.client.delete(f"{TODOS}/{todo_id}", headers=headers).status_code, 403)
        check.equal(api.client.put(f"{TODOS}/{todo_id}/assignees", json={"user_ids": []}, headers=headers).status_code, 403)
        check.equal(api.get(world.creator).json()["items"][0]["title"], "todo")

    def test_member_and_admin_can_both_use_every_endpoint(self, api, world):
        """tenant_admin も member も、全エンドポイントを使える(ロールでの制限は無く、ToDo ごとの閲覧範囲と権限で判定する)。"""
        for actor in (world.admin, world.creator):
            created = api.post(actor, {"title": f"by {actor.user_id}", "visibility": "tenant"})
            check.equal(created.status_code, 201, created.text)
            todo_id = created.json()["id"]
            check.equal(api.get(actor, f"/{todo_id}").status_code, 200)
            check.equal(api.get(actor, f"/{todo_id}/activities").status_code, 200)
            check.equal(api.get(actor).status_code, 200)

    def test_deactivated_user_is_rejected(self, api, world, ap_db):
        """無効化されたユーザーのセッションは 401(user_deactivated)で、ToDo API を使えない。"""
        with ap_db.session(world.a.ctx) as session:
            session.connection().exec_driver_sql("UPDATE t_user SET is_active = false WHERE id = %s", (world.creator.user_id,))
            session.commit()
        response = api.get(world.creator)
        check.equal((response.status_code, response.json()["code"]), (401, "user_deactivated"))


class TestCreate:
    """POST /api/v1/todos。"""

    def test_created_response(self, api, world):
        """201。Location に ToDo の URL、ETag は "1"、本文は詳細(説明・権限・担当者・公開先を含む)。作成者は操作者。"""
        response = api.post(
            world.creator,
            {"title": "  Write report ", "description": "body", "due_date": "2030-07-08", "priority": "high", "visibility": "organization", "organization_ids": [str(world.o1)], "assignee_ids": [str(world.assignee.user_id)]},
        )
        body = response.json()
        check.equal(response.status_code, 201, response.text)
        check.equal((response.headers["Location"], response.headers["ETag"]), (f"{TODOS}/{body['id']}", '"1"'))
        check.equal(
            (body["title"], body["description"], body["due_date"], body["priority"], body["status"], body["visibility"], body["effective_visibility"], body["version"]),
            ("Write report", "body", "2030-07-08", "high", "open", "organization", "organization", 1),
        )
        check.equal((body["created_by"], body["updated_by"]), (str(world.creator.user_id), str(world.creator.user_id)))
        check.equal([o["name"] for o in body["organizations"]], ["Org One"])
        check.equal([(a["user_id"], a["is_active"]) for a in body["assignees"]], [(str(world.assignee.user_id), True)])
        check.equal(body["permissions"], {"can_edit_fields": True, "can_change_status": True, "can_change_visibility": True, "can_change_assignees": True, "can_delete": True})
        check.is_true(body["created_at"].endswith("Z"))

    def test_defaults(self, api, world):
        """省略時は status=open・priority=medium・visibility=private。"""
        body = api.post(world.creator, {"title": "x"}).json()
        check.equal((body["status"], body["priority"], body["visibility"], body["description"], body["due_date"], body["assignees"], body["organizations"]), ("open", "medium", "private", None, None, [], []))

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"title": ""},
            {"title": "x" * 201},
            {"title": "t", "description": "x" * 10001},
            {"title": "t", "status": "blocked"},
            {"title": "t", "priority": "urgent"},
            {"title": "t", "visibility": "public"},
            {"title": "t", "due_date": "2030-13-40"},
            {"title": "t", "due_date": "tomorrow"},
            {"title": "t", "assignee_ids": [str(uuid.uuid4())] * 21},
            {"title": "t", "assignee_ids": ["x"]},
            {"title": "t", "organization_ids": [str(uuid.uuid4())] * 101},
            {"title": 5},
        ],
    )
    def test_shape_errors_are_validation_error_422(self, api, world, body):
        """型・長さ・enum・UUID・日付の形式の誤りは FastAPI の検証による 422(validation_error)で、サービスより先に返る。何も作られない。"""
        response = api.post(world.creator, body)
        check.equal((response.status_code, response.json()["code"]), (422, "validation_error"))
        check.greater(len(response.json()["errors"]), 0)
        check.equal(api.get(world.admin).json()["items"], [])

    def test_service_validation_is_invalid_todo_input(self, api, world):
        """サービスの検証(空白だけのタイトル、organization で組織なし、private で組織指定)は 422 invalid_todo_input で、errors に項目が入る。"""
        cases = [
            ({"title": "   "}, ("title", "required")),
            ({"title": "a\u0000b"}, ("title", "format")),
            ({"title": "t", "visibility": "organization"}, ("organization_ids", "required")),
            ({"title": "t", "visibility": "private", "organization_ids": [str(world.o1)]}, ("organization_ids", "not_allowed")),
        ]
        for body, expected in cases:
            response = api.post(world.creator, body)
            check.equal((response.status_code, response.json()["code"]), (422, "invalid_todo_input"), body)
            check.equal(problem_errors(response), [expected])

    def test_invalid_assignees_have_extension_members(self, api, world):
        """担当者の不正(無効・存在しない・他テナント)は 422 invalid_todo_assignees。拡張メンバー user_ids に該当 ID、errors[].code に reason(inactive / not_found)。"""
        ghost = uuid.uuid4()
        inactive = api.post(world.creator, {"title": "t", "assignee_ids": [str(world.inactive_id)]})
        check.equal((inactive.status_code, inactive.json()["code"], inactive.json()["user_ids"], problem_errors(inactive)), (422, "invalid_todo_assignees", [str(world.inactive_id)], [("assignee_ids", "inactive")]))
        for user_id in (ghost, world.b_admin.user_id):
            missing = api.post(world.creator, {"title": "t", "assignee_ids": [str(user_id)]})
            check.equal((missing.status_code, missing.json()["user_ids"], problem_errors(missing)), (422, [str(user_id)], [("assignee_ids", "not_found")]))

    def test_invalid_organizations_have_extension_members(self, api, world):
        """公開先の不正(存在しない・削除済み・他テナント)は 422 invalid_todo_organizations。拡張メンバー organization_ids に該当 ID。"""
        for org_id in (uuid.uuid4(), world.o3, world.b_org):
            response = api.post(world.creator, {"title": "t", "visibility": "organization", "organization_ids": [str(org_id)]})
            check.equal((response.status_code, response.json()["code"], response.json()["organization_ids"]), (422, "invalid_todo_organizations", [str(org_id)]))
        check.equal(api.get(world.admin).json()["items"], [])

    def test_request_tenant_values_are_ignored(self, api, world, ap_db):
        """ボディ・クエリ・ヘッダーに B の tenant_id / created_by を混ぜても無視され、A のテナント・操作者として作成される。"""
        response = api.client.post(
            TODOS,
            json={"title": "mixed", "tenant_id": str(world.b.id), "created_by": str(world.b_admin.user_id), "version": 99},
            params={"tenant_id": str(world.b.id)},
            headers=with_csrf(world.creator.headers, **{"X-Tenant-ID": str(world.b.id)}),
        )
        check.equal(response.status_code, 201, response.text)
        body = response.json()
        check.equal((body["created_by"], body["version"]), (str(world.creator.user_id), 1))
        check.equal([r["tenant_id"] for r in ap_db.rows(world.a.ctx, "SELECT tenant_id FROM t_todo")], [world.a.id])
        check.equal(ap_db.rows(world.b.ctx, "SELECT id FROM t_todo"), [])


class TestGet:
    """GET /api/v1/todos/{id}。"""

    def test_detail_with_etag_and_permissions(self, api, world):
        """詳細は ETag(version)・説明・操作者の権限を返す。権限は作成者 / 担当者 / 閲覧のみで異なる。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, description="desc", visibility="tenant", assignees=[world.assignee.user_id])
        expected = [
            (world.admin, (True, True, True, True, True)),
            (world.creator, (True, True, True, True, True)),
            (world.assignee, (False, True, False, True, False)),
            (world.m1, (False, False, False, False, False)),
        ]
        for actor, flags in expected:
            response = api.get(actor, f"/{todo_id}")
            body = response.json()
            check.equal((response.status_code, response.headers["ETag"], body["description"]), (200, '"1"', "desc"))
            check.equal(tuple(body["permissions"].values()), flags)

    def test_not_viewable_is_the_same_404_as_unknown(self, api, world):
        """閲覧できない ToDo(private で無関係の人・削除済み・他テナント)は、存在しない ID と同じ 404(todo_not_found)。ToDo の情報を含まない。"""
        private = world.factory.add(world.a.ctx, world.creator.user_id, title="secret title", visibility="private")
        deleted = world.factory.add(world.a.ctx, world.creator.user_id, title="gone", visibility="tenant", deleted=True)
        foreign = world.factory.add(world.b.ctx, world.b_admin.user_id, title="foreign", visibility="tenant")
        unknown = api.get(world.outsider, f"/{uuid.uuid4()}")
        for todo_id, actor in ((private, world.outsider), (private, world.m1), (deleted, world.admin), (deleted, world.creator), (foreign, world.admin)):
            response = api.get(actor, f"/{todo_id}")
            check.equal((response.status_code, response.json()["code"]), (404, "todo_not_found"))
            check.equal(response.json()["detail"], unknown.json()["detail"])
            check.equal(response.json()["title"], unknown.json()["title"])
            for hidden in ("secret title", "gone", "foreign"):
                check.is_not_in(hidden, response.text)

    def test_malformed_id_is_422(self, api, world):
        """UUID でない ID は 422。"""
        check.equal(api.get(world.admin, "/not-a-uuid").status_code, 422)


class TestUpdate:
    """PATCH /api/v1/todos/{id}。"""

    def test_if_match_is_required(self, api, world):
        """If-Match が無ければ 428(precondition_required)、形式が不正なら 400(invalid_if_match)。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id)
        missing = api.patch(world.creator, todo_id, {"title": "x"}, version=None)
        check.equal((missing.status_code, missing.json()["code"]), (428, "precondition_required"))
        for value in ("*", "abc", '"1", "2"', '"0"', '""'):
            response = api.client.patch(f"{TODOS}/{todo_id}", json={"title": "x"}, headers=with_csrf(world.creator.headers, **{"If-Match": value}))
            check.equal((response.status_code, response.json()["code"]), (400, "invalid_if_match"), value)

    def test_stale_version_is_412(self, api, world):
        """版が違えば 412(todo_version_conflict)。変更されない。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, title="orig")
        response = api.patch(world.creator, todo_id, {"title": "x"}, version=7)
        check.equal((response.status_code, response.json()["code"]), (412, "todo_version_conflict"))
        check.equal(api.get(world.creator, f"/{todo_id}").json()["title"], "orig")

    def test_update_returns_new_etag_and_detail(self, api, world):
        """更新は 200、新しい ETag と詳細。weak な If-Match(W/"1")も受け付ける。連続更新は新しい版が必要。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, title="orig")
        response = api.client.patch(f"{TODOS}/{todo_id}", json={"title": "new", "status": "done"}, headers=with_csrf(world.creator.headers, **{"If-Match": 'W/"1"'}))
        body = response.json()
        check.equal((response.status_code, response.headers["ETag"], body["title"], body["status"], body["version"]), (200, '"2"', "new", "done", 2))
        check.equal(api.patch(world.creator, todo_id, {"title": "again"}, version=1).status_code, 412)
        check.equal(api.patch(world.creator, todo_id, {"title": "again"}, version=2).json()["version"], 3)

    def test_null_handling(self, api, world):
        """description と due_date の null は値を消す。title / priority / status / visibility / organization_ids の null は 422(validation_error)。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, description="d", due_date=dt.date(2030, 1, 1), visibility="tenant")
        cleared = api.patch(world.creator, todo_id, {"description": None, "due_date": None}).json()
        check.equal((cleared["description"], cleared["due_date"], cleared["version"]), (None, None, 2))
        for field in ("title", "priority", "status", "visibility", "organization_ids"):
            response = api.patch(world.creator, todo_id, {field: None}, version=2)
            check.equal((response.status_code, response.json()["code"]), (422, "validation_error"), field)
            check.is_in(field, [e["field"] for e in response.json()["errors"]])

    def test_empty_body_and_unchanged_values_change_nothing(self, api, world):
        """空のボディ・同じ値の送信は何も変えず、版も変わらない(権限が無い人でも通る)。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, title="same", visibility="tenant")
        for actor in (world.creator, world.m1):
            response = api.patch(actor, todo_id, {})
            check.equal((response.status_code, response.json()["version"], response.headers["ETag"]), (200, 1, '"1"'))
        same = api.patch(world.m1, todo_id, {"title": "same", "status": "open", "visibility": "tenant", "priority": "medium"})
        check.equal((same.status_code, same.json()["version"]), (200, 1))

    def test_forbidden_has_operation_extension(self, api, world):
        """権限の無い項目が変わる更新は 403(todo_operation_forbidden)。拡張メンバー operation に拒否した操作(edit_fields / change_status / change_visibility)。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant", assignees=[world.assignee.user_id])
        cases = [
            (world.assignee, {"title": "x"}, "edit_fields"),
            (world.assignee, {"priority": "high", "status": "done"}, "edit_fields"),
            (world.assignee, {"visibility": "private"}, "change_visibility"),
            (world.m1, {"status": "done"}, "change_status"),
            (world.m1, {"description": "x"}, "edit_fields"),
        ]
        for actor, body, operation in cases:
            response = api.patch(actor, todo_id, body)
            check.equal((response.status_code, response.json()["code"], response.json()["operation"]), (403, "todo_operation_forbidden", operation), body)
        check.equal(api.get(world.creator, f"/{todo_id}").json()["version"], 1)

    def test_assignee_can_change_status_only(self, api, world):
        """担当者は status だけの PATCH が通る(全項目を送っても、変わるのが status だけなら通る)。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, title="t", description="d", visibility="tenant", assignees=[world.assignee.user_id])
        response = api.patch(world.assignee, todo_id, {"title": "t", "description": "d", "priority": "medium", "visibility": "tenant", "organization_ids": [], "status": "in_progress"})
        check.equal((response.status_code, response.json()["status"], response.json()["version"]), (200, "in_progress", 2))

    def test_order_404_then_412_then_403_then_422(self, api, world):
        """判定の順序: 形式 422 → 見えない 404 → 版 412 → 権限 403 → 状態依存 422(§10 #8)。"""
        hidden = world.factory.add(world.a.ctx, world.creator.user_id, visibility="private")
        shared = world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant", assignees=[world.assignee.user_id])
        bad_shape = api.patch(world.outsider, hidden, {"title": ""}, version=9)
        check.equal((bad_shape.status_code, bad_shape.json()["code"]), (422, "validation_error"))
        blank = api.patch(world.outsider, hidden, {"title": "   "}, version=9)
        check.equal((blank.status_code, blank.json()["code"]), (422, "invalid_todo_input"))
        check.equal(api.patch(world.outsider, hidden, {"title": "x"}, version=9).json()["code"], "todo_not_found")
        check.equal(api.patch(world.m1, shared, {"title": "x"}, version=9).json()["code"], "todo_version_conflict")
        check.equal(api.patch(world.m1, shared, {"title": "x"}).json()["code"], "todo_operation_forbidden")
        ghost = str(uuid.uuid4())
        check.equal(api.patch(world.assignee, shared, {"visibility": "organization", "organization_ids": [ghost]}).json()["code"], "todo_operation_forbidden")
        check.equal(api.patch(world.creator, shared, {"visibility": "organization", "organization_ids": [ghost]}).json()["code"], "invalid_todo_organizations")

    def test_visibility_and_organizations(self, api, world):
        """閲覧範囲を organization にして公開先を設定すると所属者に見えるようになる。organization で組織なしは 422、private で組織指定は 422。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, visibility="private")
        check.equal(api.get(world.m1, f"/{todo_id}").status_code, 404)
        no_orgs = api.patch(world.creator, todo_id, {"visibility": "organization"})
        check.equal((no_orgs.status_code, no_orgs.json()["code"], problem_errors(no_orgs)), (422, "invalid_todo_input", [("organization_ids", "required")]))
        response = api.patch(world.creator, todo_id, {"visibility": "organization", "organization_ids": [str(world.o1)]})
        check.equal((response.status_code, response.json()["effective_visibility"]), (200, "organization"))
        check.equal(api.get(world.m1, f"/{todo_id}").status_code, 200)
        not_allowed = api.patch(world.creator, todo_id, {"visibility": "private", "organization_ids": [str(world.o1)]}, version=2)
        check.equal((not_allowed.status_code, problem_errors(not_allowed)), (422, [("organization_ids", "not_allowed")]))
        back = api.patch(world.creator, todo_id, {"visibility": "private"}, version=2)
        check.equal(back.json()["organizations"], [])
        check.equal(api.get(world.m1, f"/{todo_id}").status_code, 404)

    def test_effective_visibility_after_organization_deleted(self, api, world, ap_db):
        """公開先の組織がすべて削除されると、effective_visibility が private になり、所属者から見えなくなる(AP-VIS-08)。organizations は空。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, visibility="organization", orgs=[world.o1])
        check.equal(api.get(world.m1, f"/{todo_id}").status_code, 200)
        with ap_db.session(world.a.ctx) as session:
            session.connection().exec_driver_sql("UPDATE t_organization SET deleted_at = now() WHERE id = %s", (world.o1,))
            session.commit()
        check.equal(api.get(world.m1, f"/{todo_id}").status_code, 404)
        body = api.get(world.creator, f"/{todo_id}").json()
        check.equal((body["visibility"], body["effective_visibility"], body["organizations"]), ("organization", "private", []))

    def test_request_tenant_values_are_ignored_on_update(self, api, world):
        """更新のボディに tenant_id / created_by / version を混ぜても無視される。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, title="t")
        response = api.patch(world.creator, todo_id, {"title": "u", "tenant_id": str(world.b.id), "created_by": str(world.b_admin.user_id), "version": 50, "id": str(uuid.uuid4())})
        body = response.json()
        check.equal((response.status_code, body["id"], body["created_by"], body["version"]), (200, str(todo_id), str(world.creator.user_id), 2))


class TestDelete:
    """DELETE /api/v1/todos/{id}。"""

    def test_delete_is_204_and_soft(self, api, world, ap_db):
        """204(本文なし)。以降の詳細・一覧・アクティビティ・再削除・更新・担当者変更が 404。行は DB に残る(論理削除)。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, title="bye", visibility="tenant")
        response = api.delete(world.creator, todo_id)
        check.equal((response.status_code, response.content), (204, b""))
        for actor in (world.admin, world.creator):
            check.equal(api.get(actor, f"/{todo_id}").status_code, 404)
            check.equal(api.get(actor, f"/{todo_id}/activities").status_code, 404)
            check.equal(api.delete(actor, todo_id, version=2).status_code, 404)
            check.equal(api.patch(actor, todo_id, {"title": "x"}, version=2).status_code, 404)
            check.equal(api.assignees(actor, todo_id, [], version=2).status_code, 404)
            check.is_not_in("bye", [i["title"] for i in api.get(actor).json()["items"]])
        check.is_not_none(ap_db.rows(world.a.ctx, "SELECT deleted_at FROM t_todo WHERE id = :id", id=todo_id)[0]["deleted_at"])

    def test_requires_if_match_and_permission(self, api, world):
        """If-Match が無ければ 428、版違いは 412、担当者・閲覧のみの人は 403(operation=delete)。tenant_admin は作成者でなくても削除できる。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant", assignees=[world.assignee.user_id])
        check.equal(api.delete(world.creator, todo_id, version=None).status_code, 428)
        check.equal(api.delete(world.creator, todo_id, version=3).status_code, 412)
        for actor in (world.assignee, world.m1):
            response = api.delete(actor, todo_id)
            check.equal((response.status_code, response.json()["code"], response.json()["operation"]), (403, "todo_operation_forbidden", "delete"))
        check.equal(api.delete(world.admin, todo_id).status_code, 204)


class TestAssignees:
    """PUT /api/v1/todos/{id}/assignees。"""

    def test_replace_keeps_assigned_at_of_remaining(self, api, world):
        """全置換。200 と新しい ETag。残る担当者の assigned_at / assigned_by は保たれ、新しい担当者には操作者が入る。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant", assignees=[world.assignee.user_id], assigned_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        response = api.assignees(world.admin, todo_id, [world.assignee.user_id, world.m1.user_id])
        body = response.json()
        check.equal((response.status_code, response.headers["ETag"], body["version"]), (200, '"2"', 2))
        rows = {a["user_id"]: a for a in body["assignees"]}
        check.equal(rows[str(world.assignee.user_id)]["assigned_at"], "2026-01-01T00:00:00Z")
        check.equal(rows[str(world.assignee.user_id)]["assigned_by"], str(world.creator.user_id))
        check.equal(rows[str(world.m1.user_id)]["assigned_by"], str(world.admin.user_id))

    def test_requirements_and_errors(self, api, world):
        """If-Match が無ければ 428、版違いは 412、閲覧のみの人は 403(operation=change_assignees)、担当者は変更できる。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant", assignees=[world.assignee.user_id])
        check.equal(api.assignees(world.creator, todo_id, [], version=None).status_code, 428)
        check.equal(api.assignees(world.creator, todo_id, [], version=8).status_code, 412)
        denied = api.assignees(world.m1, todo_id, [])
        check.equal((denied.status_code, denied.json()["operation"]), (403, "change_assignees"))
        check.equal(api.assignees(world.assignee, todo_id, [world.m1.user_id]).status_code, 200)

    def test_invalid_assignees_are_422_with_user_ids(self, api, world):
        """無効なユーザーの新規割り当ては 422 invalid_todo_assignees(reason=inactive)。存在しない・他テナントは not_found。拡張メンバー user_ids に該当 ID。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant")
        inactive = api.assignees(world.creator, todo_id, [world.inactive_id])
        check.equal((inactive.status_code, inactive.json()["code"], inactive.json()["user_ids"], problem_errors(inactive)), (422, "invalid_todo_assignees", [str(world.inactive_id)], [("user_ids", "inactive")]))
        for user_id in (uuid.uuid4(), world.b_admin.user_id):
            missing = api.assignees(world.creator, todo_id, [user_id])
            check.equal((missing.status_code, missing.json()["user_ids"], problem_errors(missing)), (422, [str(user_id)], [("user_ids", "not_found")]))
        check.equal(api.get(world.creator, f"/{todo_id}").json()["assignees"], [])

    def test_inactive_assignee_stays_and_can_be_removed(self, api, world):
        """既に担当者の無効ユーザーは残せる(新規ではない)・外せる。詳細では is_active=false で表示される。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant", assignees=[world.inactive_id])
        kept = api.assignees(world.creator, todo_id, [world.inactive_id])
        check.equal((kept.status_code, kept.json()["version"], [(a["user_id"], a["is_active"]) for a in kept.json()["assignees"]]), (200, 1, [(str(world.inactive_id), False)]))
        removed = api.assignees(world.admin, todo_id, [])
        check.equal((removed.status_code, removed.json()["assignees"]), (200, []))

    def test_limit_of_twenty(self, api, world, ap_db):
        """21 人以上は 422(validation_error。リクエストの形式)。20 人は設定できる。"""
        people = [ap_db.add_user(world.a.ctx).id for _ in range(21)]
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant")
        too_many = api.assignees(world.creator, todo_id, people)
        check.equal((too_many.status_code, too_many.json()["code"]), (422, "validation_error"))
        ok = api.assignees(world.creator, todo_id, people[:20])
        check.equal((ok.status_code, len(ok.json()["assignees"])), (200, 20))

    def test_invalid_body_is_422(self, api, world):
        """user_ids の欠落・UUID でない値は 422。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant")
        headers = with_csrf(world.creator.headers, **etag(1))
        for body in ({}, {"user_ids": ["x"]}, {"user_ids": "x"}, {"user_ids": None}):
            check.equal(api.client.put(f"{TODOS}/{todo_id}/assignees", json=body, headers=headers).status_code, 422, body)


class TestActivities:
    """GET /api/v1/todos/{id}/activities。"""

    def build(self, api, world):
        created = api.post(world.creator, {"title": "a", "visibility": "tenant"}).json()
        todo_id = created["id"]
        api.patch(world.creator, todo_id, {"title": "b"}, version=1)
        api.patch(world.creator, todo_id, {"title": "c", "status": "done", "visibility": "private"}, version=2)
        api.assignees(world.creator, todo_id, [world.assignee.user_id], version=3)
        return todo_id

    def test_newest_first_with_payloads(self, api, world):
        """新しい順(同じ操作の行は記録順の逆)。種別ごとに payload の形が仕様どおり。操作者の ID と表示名が入る。"""
        todo_id = self.build(api, world)
        body = api.get(world.creator, f"/{todo_id}/activities").json()
        check.equal([a["action"] for a in body["items"]], ["assignees_changed", "visibility_changed", "status_changed", "updated", "updated", "created"])
        by_action = {a["action"]: a for a in reversed(body["items"])}
        check.equal(by_action["assignees_changed"]["payload"], {"added": [str(world.assignee.user_id)], "removed": []})
        check.equal(by_action["visibility_changed"]["payload"], {"changes": {"visibility": {"before": "tenant", "after": "private"}}})
        check.equal(by_action["status_changed"]["payload"], {"changes": {"status": {"before": "open", "after": "done"}}})
        check.equal(by_action["created"]["payload"]["values"]["title"], "a")
        first = body["items"][0]
        check.equal((first["actor_id"], first["actor_display_name"], first["todo_id"]), (str(world.creator.user_id), "Creator Actor", todo_id))
        check.is_none(body["next_cursor"])
        stamps = [a["created_at"] for a in body["items"]]
        check.equal(stamps, sorted(stamps, reverse=True))

    def test_cursor_pagination(self, api, world):
        """limit=2 でカーソルを辿ると、全件が重複・欠落なく同じ順序で並ぶ。"""
        todo_id = self.build(api, world)
        full = [a["id"] for a in api.get(world.creator, f"/{todo_id}/activities").json()["items"]]
        collected, cursor = [], None
        for _ in range(10):
            params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
            body = api.get(world.creator, f"/{todo_id}/activities", **params).json()
            collected.extend(a["id"] for a in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break
        check.equal(collected, full)

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"cursor": "garbage"}, {"limit": "x"}])
    def test_invalid_query_is_422(self, api, world, params):
        """limit の範囲外・壊れたカーソルは 422。"""
        todo_id = self.build(api, world)
        check.equal(api.get(world.creator, f"/{todo_id}/activities", **params).status_code, 422)

    def test_cursor_of_a_list_endpoint_is_rejected(self, api, world):
        """ToDo 一覧のカーソル(別の sort)をアクティビティに使うと 422(並び替えの指定が違う)。"""
        self.build(api, world)
        cursor = api.get(world.creator, limit=1, sort="due_date").json()["next_cursor"]
        todo_id = api.get(world.creator).json()["items"][0]["id"]
        if cursor:
            check.equal(api.get(world.creator, f"/{todo_id}/activities", cursor=cursor).status_code, 422)

    def test_hidden_todo_is_404(self, api, world):
        """閲覧できない ToDo のアクティビティは 404(todo_not_found)。閲覧できる人(担当者・作成者・管理者)は読める。"""
        todo_id = world.factory.add(world.a.ctx, world.creator.user_id, visibility="private", assignees=[world.assignee.user_id])
        api.patch(world.creator, todo_id, {"title": "x"}, version=1)
        for actor in (world.outsider, world.m1):
            response = api.get(actor, f"/{todo_id}/activities")
            check.equal((response.status_code, response.json()["code"]), (404, "todo_not_found"))
        for actor in (world.admin, world.creator, world.assignee):
            check.equal(len(api.get(actor, f"/{todo_id}/activities").json()["items"]), 1)

    def test_activity_log_is_separate_from_audit_log(self, api, world, ap_db):
        """アクティビティは API で読め、監査ログ(t_ap_audit_log)の行は別に記録される。説明の本文は監査ログに残らない。"""
        created = api.post(world.creator, {"title": "audited", "description": "TOP-SECRET-BODY", "visibility": "tenant"}).json()
        api.patch(world.creator, created["id"], {"description": "TOP-SECRET-BODY-2"}, version=1)
        audits = [a for a in ap_db.audits(world.a.ctx) if a["target_type"] == "todo"]
        check.equal([a["action"] for a in audits], ["todo.create", "todo.update"])
        check.is_not_in("TOP-SECRET-BODY", json.dumps([a["payload"] for a in audits]))
        check.equal([a["action"] for a in api.get(world.creator, f"/{created['id']}/activities").json()["items"]], ["updated", "created"])


# ---------------------------------------------------------------------------
# 一覧
# ---------------------------------------------------------------------------
T0 = dt.datetime(2026, 3, 1, 9, 0, tzinfo=dt.UTC)
RANK = {"low": 1, "medium": 2, "high": 3}


@pytest.fixture
def listing(world):
    """値が重複する 12 件(tenant 公開)。ID → 期待値。"""
    specs = [
        ("Alpha report", "open", "low", None, 0, 0),
        ("Beta report", "open", "medium", 0, 0, 5),
        ("Gamma", "in_progress", "high", 0, 1, 5),
        ("Delta", "done", "low", 1, 1, 9),
        ("Epsilon report", "done", "medium", 1, 2, 9),
        ("Zeta", "open", "high", 2, 2, 9),
        ("Eta", "in_progress", "low", None, 3, 3),
        ("Theta report", "in_progress", "medium", None, 3, 3),
        ("Iota", "done", "high", 3, 4, 4),
        ("Kappa", "open", "low", 3, 4, 8),
        ("Lambda report", "open", "medium", 4, 5, 8),
        ("Mu", "done", "high", 5, 5, 8),
    ]
    rows = {}
    for title, status, priority, due, created, updated in specs:
        due_date = None if due is None else dt.date(2030, 6, 10) + dt.timedelta(days=due)
        todo_id = world.factory.add(
            world.a.ctx, world.creator.user_id, title=title, status=status, priority=priority, due_date=due_date, visibility="tenant",
            created_at=T0 + dt.timedelta(seconds=created), updated_at=T0 + dt.timedelta(seconds=updated),
        )
        rows[str(todo_id)] = {"title": title, "status": status, "priority": priority, "due_date": due_date, "created_at": T0 + dt.timedelta(seconds=created), "updated_at": T0 + dt.timedelta(seconds=updated), "id": todo_id}
    return rows


def expected_order(rows, key, descending):
    def sort_key(item):
        todo_id, row = item
        value = row[key]
        if key == "due_date":
            return (value is None, value or dt.date.min, row["id"])
        if key == "priority":
            return (RANK[value], row["id"])
        return (value, row["id"])

    return [todo_id for todo_id, _ in sorted(rows.items(), key=sort_key, reverse=descending)]


def walk(api, actor, limit, **params):
    """カーソルを最後まで辿った ID。"""
    ids, cursor = [], None
    for _ in range(100):
        query = {"limit": limit, **params, **({"cursor": cursor} if cursor else {})}
        response = api.get(actor, **query)
        assert response.status_code == 200, response.text
        body = response.json()
        ids.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return ids
    raise AssertionError("カーソルが終わらない")


class TestList:
    """GET /api/v1/todos。"""

    @pytest.mark.parametrize("limit", [1, 3, 5, 12, 50])
    @pytest.mark.parametrize("key", ["due_date", "priority", "created_at", "updated_at"])
    @pytest.mark.parametrize("descending", [False, True])
    def test_every_sort_key_pages_without_gaps_or_duplicates(self, api, world, listing, key, descending, limit):
        """全ソートキー・昇降順・ページサイズで、カーソルを辿ると期待どおりの順序で重複・欠落が無い(期限なし・同順位を含む)。"""
        sort = f"{'-' if descending else ''}{key}"
        ids = walk(api, world.admin, limit, sort=sort)
        check.equal(ids, expected_order(listing, key, descending))

    def test_default_sort_and_response_shape(self, api, world, listing):
        """既定は -created_at。要素は説明を含まず、version・担当者・公開先・effective_visibility を含む。total は常に null。include_total は無視される。"""
        body = api.get(world.admin, limit=50, include_total="true").json()
        check.equal([i["id"] for i in body["items"]], expected_order(listing, "created_at", True))
        check.is_none(body["total"])
        item = body["items"][0]
        check.equal(set(item), {"id", "title", "status", "priority", "due_date", "visibility", "effective_visibility", "organizations", "assignees", "created_by", "updated_by", "version", "created_at", "updated_at"})
        check.is_not_in("description", item)

    def test_nulls_in_due_date_cursor_round_trip(self, api, world, listing):
        """期限なしの行でページが切れても、カーソル(due_date が null)で続きを取得できる。"""
        for sort in ("due_date", "-due_date"):
            ids = walk(api, world.admin, 1, sort=sort)
            check.equal(ids, expected_order(listing, "due_date", sort.startswith("-")), sort)

    def test_status_and_priority_comma_separated(self, api, world, listing):
        """status / priority はカンマ区切りで複数指定できる(空要素・前後の空白は無視)。AND で組み合わせる。"""
        def titles(**params):
            return {i["title"] for i in api.get(world.admin, limit=200, **params).json()["items"]}

        check.equal(titles(status="open,done"), {r["title"] for r in listing.values() if r["status"] in ("open", "done")})
        check.equal(titles(status=" open , done ,"), {r["title"] for r in listing.values() if r["status"] in ("open", "done")})
        check.equal(titles(priority="high,low"), {r["title"] for r in listing.values() if r["priority"] in ("high", "low")})
        check.equal(titles(status="open", priority="low,high"), {r["title"] for r in listing.values() if r["status"] == "open" and r["priority"] in ("low", "high")})
        check.equal(titles(status=""), {r["title"] for r in listing.values()})

    @pytest.mark.parametrize("params", [{"status": "bogus"}, {"status": "open,bogus"}, {"priority": "urgent"}, {"priority": "high,"+"x"}])
    def test_invalid_enum_filter_is_422(self, api, world, listing, params):
        """status / priority の不正値(カンマ区切りの一部だけ不正な場合を含む)は 422(invalid_todo_input)。errors に項目が入る。"""
        response = api.get(world.admin, **params)
        check.equal((response.status_code, response.json()["code"]), (422, "invalid_todo_input"))
        check.equal(problem_errors(response)[0][0], next(iter(params)))

    @pytest.mark.parametrize(
        "params",
        [
            {"scope": "everything"}, {"sort": "title"}, {"sort": "-title"}, {"sort": "due_date,-priority"}, {"sort": ""}, {"assignee_id": "x"}, {"organization_id": "x"},
            {"due_before": "2030-02-30"}, {"due_after": "soon"}, {"q": "x" * 201}, {"limit": 0}, {"limit": 201}, {"limit": "abc"},
        ],
    )
    def test_invalid_query_is_422(self, api, world, listing, params):
        """scope・sort(複数キーを含む)・UUID・日付・q の長さ・limit の不正は 422。"""
        check.equal(api.get(world.admin, **params).status_code, 422)

    def test_due_filters_are_inclusive_and_exclude_null(self, api, world, listing):
        """due_before / due_after は指定日を含み、期限なしは除く。"""
        def titles(**params):
            return {i["title"] for i in api.get(world.admin, limit=200, **params).json()["items"]}

        day = dt.date(2030, 6, 10)
        check.equal(titles(due_before=str(day + dt.timedelta(days=1))), {r["title"] for r in listing.values() if r["due_date"] is not None and r["due_date"] <= day + dt.timedelta(days=1)})
        check.equal(titles(due_after=str(day + dt.timedelta(days=3))), {r["title"] for r in listing.values() if r["due_date"] is not None and r["due_date"] >= day + dt.timedelta(days=3)})
        check.equal(titles(due_after=str(day + dt.timedelta(days=2)), due_before=str(day + dt.timedelta(days=2))), {"Zeta"})
        check.equal(titles(due_after="2030-06-14", due_before="2030-06-10"), set())

    def test_q_filter(self, api, world, listing):
        """q はタイトルの部分一致(大文字小文字を区別しない)。"""
        titles = {i["title"] for i in api.get(world.admin, limit=200, q="REPORT").json()["items"]}
        check.equal(titles, {r["title"] for r in listing.values() if "report" in r["title"].lower()})

    def test_scope_values(self, api, world):
        """mine / assigned / shared / all が、閲覧できるものに限って期待どおりに分かれる。"""
        mine = world.factory.add(world.a.ctx, world.m1.user_id, title="mine", visibility="private")
        assigned = world.factory.add(world.a.ctx, world.creator.user_id, title="assigned", visibility="private", assignees=[world.m1.user_id])
        shared = world.factory.add(world.a.ctx, world.creator.user_id, title="shared", visibility="tenant")
        world.factory.add(world.a.ctx, world.creator.user_id, title="hidden", visibility="private")

        def titles(scope):
            return {i["title"] for i in api.get(world.m1, limit=200, scope=scope).json()["items"]}

        check.equal(titles("mine"), {"mine"})
        check.equal(titles("assigned"), {"assigned"})
        check.equal(titles("shared"), {"shared"})
        check.equal(titles("all"), {"mine", "assigned", "shared"})
        check.equal({i["title"] for i in api.get(world.m1, limit=200).json()["items"]}, titles("all"))
        del mine, assigned, shared

    def test_member_list_matches_single_get(self, api, world):
        """一覧に出る ToDo は詳細で 200、出ない ToDo は詳細で 404(一覧と単体の閲覧範囲が一致する)。"""
        cases = {
            "private": world.factory.add(world.a.ctx, world.creator.user_id, visibility="private"),
            "tenant": world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant"),
            "org": world.factory.add(world.a.ctx, world.creator.user_id, visibility="organization", orgs=[world.o1]),
            "org_deleted": world.factory.add(world.a.ctx, world.creator.user_id, visibility="organization", orgs=[world.o3]),
            "assigned": world.factory.add(world.a.ctx, world.creator.user_id, visibility="private", assignees=[world.m1.user_id]),
            "deleted": world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant", deleted=True),
        }
        for actor in (world.admin, world.creator, world.m1, world.outsider, world.assignee):
            listed = {i["id"] for i in api.get(actor, limit=200).json()["items"]}
            for name, todo_id in cases.items():
                status = api.get(actor, f"/{todo_id}").status_code
                check.equal(status == 200, str(todo_id) in listed, f"{name} / {actor.user_id}")

    def test_corrupted_and_mismatched_cursors_are_422(self, api, world, listing):
        """壊れたカーソル・別の sort のカーソル・日付の形式が不正なカーソルは 422(validation_error。errors[].code=invalid_cursor)。"""
        first = api.get(world.admin, limit=1, sort="due_date").json()["next_cursor"]
        assert first
        responses = [
            api.get(world.admin, cursor="garbage"),
            api.get(world.admin, cursor=first, sort="priority"),
            api.get(world.admin, cursor=first, sort="-due_date"),
            api.get(world.admin, cursor=first, sort="created_at"),
            api.get(world.admin, cursor=make_cursor({"s": "due_date", "k": "not-a-date", "i": str(uuid.uuid4())}), sort="due_date"),
            api.get(world.admin, cursor=make_cursor({"s": "created_at", "k": "2026-01-01T00:00:00", "i": str(uuid.uuid4())}), sort="created_at"),
            api.get(world.admin, cursor=make_cursor({"s": "priority", "k": 3, "i": str(uuid.uuid4())}), sort="priority"),
            api.get(world.admin, cursor=make_cursor({"s": "priority", "k": "low", "i": "not-a-uuid"}), sort="priority"),
            api.get(world.admin, cursor=make_cursor({"k": "low"}), sort="priority"),
        ]
        for response in responses:
            check.equal((response.status_code, problem_errors(response)), (422, [("cursor", "invalid_cursor")]), response.text)

    def test_unknown_priority_value_in_cursor_is_invalid_cursor(self, api, world, listing):
        """priority のカーソルに未知の値が入っていても、壊れたカーソルとして 422 の validation_error(errors[].code=invalid_cursor)になる(§9.5)。"""
        response = api.get(world.admin, cursor=make_cursor({"s": "priority", "k": "urgent", "i": str(uuid.uuid4())}), sort="priority")
        check.equal((response.status_code, response.json()["code"], problem_errors(response)), (422, "validation_error", [("cursor", "invalid_cursor")]))

    def test_unknown_priority_value_in_cursor_is_still_422(self, api, world, listing):
        """(現状の挙動)priority のカーソルに未知の値が入っていても 422 で拒否される(結果は返さない)。"""
        response = api.get(world.admin, cursor=make_cursor({"s": "priority", "k": "urgent", "i": str(uuid.uuid4())}), sort="priority")
        check.equal(response.status_code, 422)

    def test_invalid_cursor_has_invalid_cursor_code(self, api, world, listing):
        """壊れたカーソルの errors[].code は invalid_cursor。"""
        response = api.get(world.admin, cursor="garbage")
        check.equal((response.status_code, response.json()["code"], problem_errors(response)), (422, "validation_error", [("cursor", "invalid_cursor")]))


def make_cursor(payload) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


class TestCrossTenant:
    """クロステナント(tenant-isolation §5.1)を、実際のサービス・DB(RLS)で確認する。"""

    @pytest.fixture
    def foreign(self, world):
        """テナント B の tenant 公開の ToDo(担当者・説明つき)。"""
        todo_id = world.factory.add(world.b.ctx, world.b_admin.user_id, title="B secret", description="b body", visibility="tenant", assignees=[world.b_admin.user_id])
        return todo_id

    def test_every_endpoint_is_404_for_other_tenant(self, api, world, foreign, ap_db):
        """A の tenant_admin が B の ToDo を ID 指定すると、取得・更新・削除・担当者変更・アクティビティのすべてが 404(todo_not_found)。B の ToDo は変わらない。"""
        before = ap_db.rows(world.b.ctx, "SELECT * FROM t_todo WHERE id = :id", id=foreign)[0]
        responses = [
            api.get(world.admin, f"/{foreign}"),
            api.get(world.admin, f"/{foreign}/activities"),
            api.patch(world.admin, foreign, {"title": "hijack", "status": "done"}),
            api.delete(world.admin, foreign),
            api.assignees(world.admin, foreign, [world.admin.user_id]),
        ]
        for response in responses:
            check.equal((response.status_code, response.json()["code"]), (404, "todo_not_found"))
            check.is_not_in("B secret", response.text)
        check.equal(ap_db.rows(world.b.ctx, "SELECT * FROM t_todo WHERE id = :id", id=foreign)[0], before)
        check.equal(len(ap_db.rows(world.b.ctx, "SELECT * FROM t_todo_assignee WHERE todo_id = :id", id=foreign)), 1)
        check.equal(ap_db.rows(world.b.ctx, "SELECT * FROM t_todo_activity"), [])

    def test_lists_never_include_other_tenant(self, api, world, foreign):
        """一覧(scope・絞り込み・ページング・並び替え込み)に B の ToDo は現れず、件数にも影響しない。B の一覧にも A の ToDo は現れない。"""
        world.factory.add(world.a.ctx, world.creator.user_id, title="A todo", visibility="tenant")
        for params in ({}, {"scope": "shared"}, {"scope": "assigned"}, {"limit": 1}, {"sort": "-priority"}, {"q": "secret"}, {"status": "open"}, {"assignee_id": str(world.b_admin.user_id)}):
            body = api.get(world.admin, **params).json()
            check.is_not_in(str(foreign), [i["id"] for i in body["items"]], params)
            check.is_not_in("B secret", str(body))
        check.equal([i["title"] for i in api.get(world.admin).json()["items"]], ["A todo"])
        check.equal([i["title"] for i in api.get(world.b_admin).json()["items"]], ["B secret"])

    def test_cannot_assign_or_publish_across_tenants(self, api, world, foreign):
        """A の ToDo に B のユーザーを担当者にする・B の組織を公開先にすると 422(not_found)。"""
        mine = world.factory.add(world.a.ctx, world.creator.user_id, visibility="tenant")
        assign = api.assignees(world.creator, mine, [world.b_admin.user_id])
        check.equal((assign.status_code, assign.json()["code"], problem_errors(assign)), (422, "invalid_todo_assignees", [("user_ids", "not_found")]))
        publish = api.patch(world.creator, mine, {"visibility": "organization", "organization_ids": [str(world.b_org)]})
        check.equal((publish.status_code, publish.json()["code"], publish.json()["organization_ids"]), (422, "invalid_todo_organizations", [str(world.b_org)]))
        check.equal(api.get(world.creator, f"/{mine}").json()["version"], 1)

    def test_tenant_id_in_request_is_ignored(self, api, world, foreign):
        """ヘッダー・クエリ・ボディの B の tenant_id は無視される(一覧は A のまま、更新は B に及ばない)。"""
        response = api.client.get(TODOS, params={"tenant_id": str(world.b.id), "tenant_code": world.b.code}, headers={**world.admin.headers, "X-Tenant-ID": str(world.b.id), "X-Tenant-Code": world.b.code})
        check.equal(response.status_code, 200)
        check.is_not_in(str(foreign), [i["id"] for i in response.json()["items"]])
        patch = api.client.patch(
            f"{TODOS}/{foreign}", json={"title": "x", "tenant_id": str(world.b.id)}, params={"tenant_id": str(world.b.id)}, headers=with_csrf(world.admin.headers, **etag(1), **{"X-Tenant-ID": str(world.b.id)})
        )
        check.equal(patch.status_code, 404)

    def test_session_of_tenant_b_cannot_see_a(self, api, world):
        """B の管理者のセッションでは、A の ToDo(tenant 公開でも)は見えない。"""
        mine = world.factory.add(world.a.ctx, world.creator.user_id, title="A only", visibility="tenant")
        check.equal(api.get(world.b_admin, f"/{mine}").status_code, 404)
        check.equal(api.get(world.b_admin).json()["items"], [])
