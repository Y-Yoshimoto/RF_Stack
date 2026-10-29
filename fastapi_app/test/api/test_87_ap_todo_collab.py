# -*- coding: utf-8 -*-
"""ToDo のコメント・チェックリスト・ホームの要約・一覧の総件数(ToDoApp.md v0.6。§6、§9.5)の API のテスト。

認証・テナント判定・CSRF・ユーザーの有効確認・各サービス・DB(開発 DB の ``app_db``、RLS)はすべて実物(Keycloak は使わない)。
テナントは台帳に作る使い捨て(``ap_tenant``)で、alpha / beta には触れない。AP のデータは終了時に ``ap_db`` が削除する。
業務ルールそのもの(権限の表・上限・判定の順序の網羅)は ``todos/`` のサービス層のテストで確認しており、ここでは HTTP の契約
(ステータス・ヘッダー・ETag / If-Match・Problem Details・OpenAPI)に絞る。
"""
import datetime as dt
import re
import uuid

import pytest
import pytest_check as check
from todos.conftest import TodoFactory

from app import app
from main_app.models import TTodoChecklistItem

from .conftest import with_csrf

TODOS = "/api/v1/todos"
TODAY = dt.date(2030, 6, 15)

pytestmark = pytest.mark.usefixtures("real_active_user")


def etag(version) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def day(offset: int) -> dt.date:
    return TODAY + dt.timedelta(days=offset)


class Api:
    """リクエストの補助。``version=None`` は ``If-Match`` を付けない。"""

    def __init__(self, client) -> None:
        self.client = client

    def headers(self, actor, version=None, **extra):
        return with_csrf(actor.headers, **(etag(version) if version is not None else {}), **extra)

    def get(self, actor, path="", **params):
        return self.client.get(f"{TODOS}{path}", headers=actor.headers, params=params)

    def patch(self, actor, path, body, version=None):
        return self.client.patch(f"{TODOS}{path}", json=body, headers=self.headers(actor, version))

    def post(self, actor, path, body):
        return self.client.post(f"{TODOS}{path}", json=body, headers=self.headers(actor))

    def delete(self, actor, path, version=None):
        return self.client.delete(f"{TODOS}{path}", headers=self.headers(actor, version))

    def put(self, actor, path, body, version=None):
        return self.client.put(f"{TODOS}{path}", json=body, headers=self.headers(actor, version))


@pytest.fixture
def api(client) -> Api:
    return Api(client)


@pytest.fixture
def world(ap_tenant, ap_login, ap_db):
    """テナント A(管理者・作成者・担当者・閲覧だけの member = viewer・組織に属さない outsider)とテナント B(管理者・member)。"""

    class World:
        a = ap_tenant()
        b = ap_tenant()

    World.admin = ap_login(World.a, name="Admin")
    World.creator = ap_login(World.a, roles=("member",), name="Creator")
    World.assignee = ap_login(World.a, roles=("member",), name="Assignee")
    World.viewer = ap_login(World.a, roles=("member",), name="Viewer")
    World.outsider = ap_login(World.a, roles=("member",), name="Outsider")
    World.b_admin = ap_login(World.b, name="BAdmin")
    World.b_member = ap_login(World.b, roles=("member",), name="BMember")
    World.factory = TodoFactory(ap_db)
    World.ap_db = ap_db

    def todo(**kwargs):
        """tenant 公開の ToDo(作成者 = creator、担当者 = assignee)。"""
        kwargs.setdefault("visibility", "tenant")
        kwargs.setdefault("assignees", [World.assignee.user_id])
        return World.factory.add(World.a.ctx, World.creator.user_id, **kwargs)

    World.todo = staticmethod(todo)
    return World


@pytest.fixture
def todo(world) -> uuid.UUID:
    return world.todo()


def problem(response, *, status: int, code: str) -> dict:
    """Problem Details の共通の形(``test_70_problem_details`` と同じ標準メンバー)を確認して本文を返す。"""
    check.equal(response.status_code, status, response.text)
    check.is_true(response.headers["content-type"].startswith("application/problem+json"), response.headers.get("content-type"))
    body = response.json()
    check.is_true({"type", "title", "status", "detail", "instance", "code", "request_id", "errors"} <= set(body), sorted(body))
    check.equal((body["status"], body["code"]), (status, code))
    check.equal(body["type"], "https://errors.rf-stack.example/" + code.replace("_", "-"))
    check.equal((body["instance"], body["request_id"]), (response.request.url.path, response.headers["X-Request-ID"]))
    return body


def new_comment(api, actor, todo_id, text="hello") -> dict:
    response = api.post(actor, f"/{todo_id}/comments", {"body": text})
    assert response.status_code == 201, response.text
    return response.json()


def new_item(api, actor, todo_id, title="item", **extra) -> dict:
    response = api.post(actor, f"/{todo_id}/checklist/items", {"title": title, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def seed_items(world, todo_id, count, *, start=0) -> None:
    """項目を直接 ``count`` 件作る(上限の確認用。``position`` は ``start`` から)。"""
    with world.ap_db.session(world.a.ctx) as session:
        session.add_all(
            [TTodoChecklistItem(tenant_id=world.a.ctx.tenant_id, todo_id=todo_id, title=f"s{i}", position=start + i, created_by=world.creator.user_id, updated_by=world.creator.user_id) for i in range(count)]
        )
        session.commit()


# ---------------------------------------------------------------------------
# コメント
# ---------------------------------------------------------------------------
class TestCommentList:
    """GET /todos/{id}/comments。"""

    def test_oldest_first_with_cursor(self, api, world, todo):
        """古い順で返り、limit で区切ると next_cursor で続きを取得できる(重複・欠落なし)。最後は next_cursor が null。"""
        base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        ids = [str(world.factory.comment(world.a.ctx, todo, world.creator.user_id, body=f"c{i}", created_at=base + dt.timedelta(minutes=i))) for i in range(5)]
        seen, cursor, pages = [], None, 0
        while True:
            params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
            body = api.get(world.viewer, f"/{todo}/comments", **params).json()
            seen += [c["id"] for c in body["items"]]
            pages += 1
            cursor = body["next_cursor"]
            if cursor is None:
                break
        check.equal((seen, pages), (ids, 3))

    def test_item_shape_and_permissions(self, api, world, todo):
        """各コメントは author(id / display_name / is_active)・version・edited_at・permissions を持つ。permissions は閲覧者ごと(投稿者 = 編集・削除可、admin = 削除のみ、他 = 不可)。deleted は出ない。"""
        comment = new_comment(api, world.viewer, todo, "mine")
        gone = new_comment(api, world.viewer, todo, "gone")
        check.equal(api.delete(world.viewer, f"/{todo}/comments/{gone['id']}", 1).status_code, 204)
        per_viewer = {name: api.get(actor, f"/{todo}/comments").json()["items"] for name, actor in (("viewer", world.viewer), ("admin", world.admin), ("creator", world.creator))}
        item = per_viewer["viewer"][0]
        check.equal(set(item), {"id", "todo_id", "author", "body", "version", "created_at", "updated_at", "edited_at", "permissions"})
        check.equal((item["id"], item["body"], item["version"], item["edited_at"], item["author"]), (comment["id"], "mine", 1, None, {"id": str(world.viewer.user_id), "display_name": "Viewer Actor", "is_active": True}))
        check.equal({name: (len(items), items[0]["permissions"]) for name, items in per_viewer.items()}, {
            "viewer": (1, {"can_edit": True, "can_delete": True}),
            "admin": (1, {"can_edit": False, "can_delete": True}),
            "creator": (1, {"can_edit": False, "can_delete": False}),
        })
        check.is_true(item["created_at"].endswith("Z"))
        check.is_none(api.get(world.viewer, f"/{todo}/comments").json()["next_cursor"])

    def test_invalid_cursors_are_422(self, api, world, todo):
        """壊れたカーソル・別の一覧(ToDo 一覧)のカーソルは 422(validation_error、errors[].code = invalid_cursor)。"""
        new_comment(api, world.creator, todo)
        new_comment(api, world.creator, todo)
        world.todo()
        todo_cursor = api.get(world.admin, limit=1).json()
        check.is_not_none(todo_cursor["next_cursor"])
        for cursor in ("!!!", "e30", "x" * 30):
            body = problem(api.get(world.viewer, f"/{todo}/comments", cursor=cursor), status=422, code="validation_error")
            check.is_in(("cursor", "invalid_cursor"), [(e["field"], e["code"]) for e in body["errors"]])
        body = problem(api.get(world.viewer, f"/{todo}/comments", cursor=todo_cursor["next_cursor"]), status=422, code="validation_error")
        check.is_in("invalid_cursor", [e["code"] for e in body["errors"]])

    @pytest.mark.parametrize("limit", [0, 201, "x"])
    def test_invalid_limit_is_422(self, api, world, todo, limit):
        """limit が範囲外(0・201)・数値でないときは 422。"""
        problem(api.get(world.viewer, f"/{todo}/comments", limit=limit), status=422, code="validation_error")

    def test_total_is_always_null_in_the_comment_page(self, api, world, todo):
        """コメント一覧は総件数を数えない(total は常に null。include_total を付けても同じ)。"""
        for params in ({}, {"include_total": "true"}):
            body = api.get(world.viewer, f"/{todo}/comments", **params).json()
            check.equal((set(body), body["total"]), ({"items", "next_cursor", "total"}, None), params)


class TestCommentCreate:
    """POST /todos/{id}/comments。"""

    def test_created_response(self, api, world, todo):
        """201。Location にコメントの URL、ETag は "1"(コメントの版)、本文は前後の空白を除いたもの。投稿者は操作者。"""
        response = api.post(world.viewer, f"/{todo}/comments", {"body": "  確認しました  "})
        body = response.json()
        check.equal(response.status_code, 201, response.text)
        check.equal((response.headers["Location"], response.headers["ETag"]), (f"{TODOS}/{todo}/comments/{body['id']}", '"1"'))
        check.equal((body["body"], body["version"], body["edited_at"], body["todo_id"], body["author"]["id"]), ("確認しました", 1, None, str(todo), str(world.viewer.user_id)))
        check.equal(body["permissions"], {"can_edit": True, "can_delete": True})

    @pytest.mark.parametrize("who", ["admin", "creator", "assignee", "viewer", "outsider"])
    def test_anyone_who_can_view_can_post(self, api, world, todo, who):
        """tenant 公開の ToDo には、admin・作成者・担当者・閲覧だけの member がコメントできる。"""
        check.equal(api.post(getattr(world, who), f"/{todo}/comments", {"body": "hi"}).status_code, 201)

    @pytest.mark.parametrize("body", [{"body": ""}, {"body": "x" * 4001}, {}, {"body": None}, {"body": 5}])
    def test_invalid_body_is_422_validation_error(self, api, world, todo, body):
        """空・4,001 文字・未指定・null・数値は 422(validation_error。errors[].field に body)。何も保存しない。"""
        response = api.post(world.creator, f"/{todo}/comments", body)
        problem(response, status=422, code="validation_error")
        check.is_in("body", [e["field"] for e in response.json()["errors"]])
        check.equal(api.get(world.creator, f"/{todo}/comments").json()["items"], [])

    @pytest.mark.parametrize("text", ["   ", "\n\t ", "a\x00b"])
    def test_whitespace_only_or_control_characters_are_422(self, api, world, todo, text):
        """空白だけ・制御文字を含む本文は 422(invalid_todo_input。errors に body)。"""
        response = api.post(world.creator, f"/{todo}/comments", {"body": text})
        body = problem(response, status=422, code="invalid_todo_input")
        check.is_in("body", [e["field"] for e in body["errors"]])

    def test_boundary_4000_characters(self, api, world, todo):
        """ちょうど 4,000 文字は受け付ける。"""
        check.equal(api.post(world.creator, f"/{todo}/comments", {"body": "x" * 4000}).status_code, 201)

    def test_csrf_header_is_required(self, api, world, todo):
        """CSRF 対策のヘッダーが無い POST は 403 で、処理されない。"""
        response = api.client.post(f"{TODOS}/{todo}/comments", json={"body": "x"}, headers=world.creator.headers)
        check.equal(response.status_code, 403)
        check.equal(api.get(world.creator, f"/{todo}/comments").json()["items"], [])

    def test_unauthenticated_is_401(self, api, todo):
        """Cookie が無ければ 401。"""
        response = api.client.get(f"{TODOS}/{todo}/comments")
        check.equal(response.status_code, 401)
        check.is_true(response.headers["content-type"].startswith("application/problem+json"))


class TestCommentUpdate:
    """PATCH /todos/{id}/comments/{comment_id}。"""

    def test_edit_returns_new_etag_and_edited_at(self, api, world, todo):
        """200。ETag は新しい版 "2"、本文が変わり edited_at が付く。"""
        comment = new_comment(api, world.viewer, todo, "before")
        response = api.patch(world.viewer, f"/{todo}/comments/{comment['id']}", {"body": "  after "}, 1)
        body = response.json()
        check.equal(response.status_code, 200, response.text)
        check.equal((response.headers["ETag"], body["body"], body["version"], body["edited_at"] is not None, body["created_at"]), ('"2"', "after", 2, True, comment["created_at"]))
        listed = api.get(world.viewer, f"/{todo}/comments").json()["items"][0]
        check.equal((listed["body"], listed["edited_at"] is not None), ("after", True))

    def test_same_body_keeps_version_and_etag(self, api, world, todo):
        """同じ本文での編集は 200 で、版も ETag も edited_at も変わらない。"""
        comment = new_comment(api, world.viewer, todo, "same")
        response = api.patch(world.viewer, f"/{todo}/comments/{comment['id']}", {"body": "same"}, 1)
        check.equal((response.status_code, response.headers["ETag"], response.json()["version"], response.json()["edited_at"]), (200, '"1"', 1, None))

    def test_if_match_is_required_and_validated(self, api, world, todo):
        """If-Match が無ければ 428(precondition_required)、形式不正は 400(invalid_if_match)。コメントは変わらない。"""
        comment = new_comment(api, world.viewer, todo, "x")
        path = f"/{todo}/comments/{comment['id']}"
        problem(api.patch(world.viewer, path, {"body": "y"}), status=428, code="precondition_required")
        problem(api.client.patch(f"{TODOS}{path}", json={"body": "y"}, headers=with_csrf(world.viewer.headers, **{"If-Match": "oops"})), status=400, code="invalid_if_match")
        check.equal(api.get(world.viewer, f"/{todo}/comments").json()["items"][0]["body"], "x")

    def test_stale_version_is_412(self, api, world, todo):
        """古い版は 412(todo_comment_version_conflict。ToDo の todo_version_conflict ではない)。"""
        comment = new_comment(api, world.viewer, todo, "x")
        api.patch(world.viewer, f"/{todo}/comments/{comment['id']}", {"body": "y"}, 1)
        body = problem(api.patch(world.viewer, f"/{todo}/comments/{comment['id']}", {"body": "z"}, 1), status=412, code="todo_comment_version_conflict")
        check.is_not_in("target", body)

    def test_todo_etag_cannot_be_used_for_comment(self, api, world, todo):
        """ToDo 本体の版(例: 3)をコメントの If-Match に使っても通らない(別の版)。"""
        for index in range(2):
            api.patch(world.creator, f"/{todo}", {"title": f"t{index}"}, index + 1)
        comment = new_comment(api, world.viewer, todo)
        problem(api.patch(world.viewer, f"/{todo}/comments/{comment['id']}", {"body": "z"}, 3), status=412, code="todo_comment_version_conflict")

    @pytest.mark.parametrize("who", ["creator", "assignee", "outsider", "admin"])
    def test_non_author_cannot_edit(self, api, world, todo, who):
        """投稿者以外(ToDo の作成者・担当者・tenant_admin を含む)の編集は 403(todo_operation_forbidden、operation = edit_comment)。"""
        comment = new_comment(api, world.viewer, todo, "x")
        body = problem(api.patch(getattr(world, who), f"/{todo}/comments/{comment['id']}", {"body": "hack"}, 1), status=403, code="todo_operation_forbidden")
        check.equal(body["operation"], "edit_comment")
        check.equal(api.get(world.viewer, f"/{todo}/comments").json()["items"][0]["body"], "x")

    def test_invalid_body_is_422(self, api, world, todo):
        """本文が空・空白だけなら 422。"""
        comment = new_comment(api, world.viewer, todo)
        problem(api.patch(world.viewer, f"/{todo}/comments/{comment['id']}", {"body": ""}, 1), status=422, code="validation_error")
        problem(api.patch(world.viewer, f"/{todo}/comments/{comment['id']}", {"body": "  "}, 1), status=422, code="invalid_todo_input")

    def test_csrf_is_required(self, api, world, todo):
        """CSRF 対策のヘッダーが無い PATCH は 403。"""
        comment = new_comment(api, world.viewer, todo)
        response = api.client.patch(f"{TODOS}/{todo}/comments/{comment['id']}", json={"body": "y"}, headers={**world.viewer.headers, **etag(1)})
        check.equal(response.status_code, 403)


class TestCommentDelete:
    """DELETE /todos/{id}/comments/{comment_id}。"""

    def test_author_deletes_with_204_and_no_body(self, api, world, todo):
        """投稿者の削除は 204(本文なし)。一覧から消え、以降の編集・削除は 404(todo_comment_not_found)。"""
        comment = new_comment(api, world.viewer, todo)
        response = api.delete(world.viewer, f"/{todo}/comments/{comment['id']}", 1)
        check.equal((response.status_code, response.content), (204, b""))
        check.equal(api.get(world.viewer, f"/{todo}/comments").json()["items"], [])
        problem(api.delete(world.viewer, f"/{todo}/comments/{comment['id']}", 2), status=404, code="todo_comment_not_found")
        problem(api.patch(world.viewer, f"/{todo}/comments/{comment['id']}", {"body": "x"}, 2), status=404, code="todo_comment_not_found")

    def test_admin_can_delete_others(self, api, world, todo):
        """tenant_admin は他人のコメントを削除できる(204)。"""
        comment = new_comment(api, world.viewer, todo)
        check.equal(api.delete(world.admin, f"/{todo}/comments/{comment['id']}", 1).status_code, 204)

    @pytest.mark.parametrize("who", ["creator", "assignee", "outsider"])
    def test_other_members_get_403(self, api, world, todo, who):
        """投稿者でも tenant_admin でもない人(ToDo の作成者・担当者を含む)は 403(operation = delete_comment)。コメントは残る。"""
        comment = new_comment(api, world.viewer, todo)
        body = problem(api.delete(getattr(world, who), f"/{todo}/comments/{comment['id']}", 1), status=403, code="todo_operation_forbidden")
        check.equal(body["operation"], "delete_comment")
        check.equal(len(api.get(world.viewer, f"/{todo}/comments").json()["items"]), 1)

    def test_if_match_is_required(self, api, world, todo):
        """If-Match が無ければ 428、版が違えば 412(todo_comment_version_conflict)。"""
        comment = new_comment(api, world.viewer, todo)
        problem(api.delete(world.viewer, f"/{todo}/comments/{comment['id']}"), status=428, code="precondition_required")
        problem(api.delete(world.viewer, f"/{todo}/comments/{comment['id']}", 9), status=412, code="todo_comment_version_conflict")
        check.equal(len(api.get(world.viewer, f"/{todo}/comments").json()["items"]), 1)

    def test_csrf_is_required(self, api, world, todo):
        """CSRF 対策のヘッダーが無い DELETE は 403。"""
        comment = new_comment(api, world.viewer, todo)
        check.equal(api.client.delete(f"{TODOS}/{todo}/comments/{comment['id']}", headers={**world.viewer.headers, **etag(1)}).status_code, 403)


class TestCommentNotFound:
    """閲覧範囲外・他テナント・別の ToDo のコメントは 404。"""

    def all_calls(self, api, actor, todo_id, comment_id):
        return {
            "list": lambda: api.get(actor, f"/{todo_id}/comments"),
            "create": lambda: api.post(actor, f"/{todo_id}/comments", {"body": "x"}),
            "update": lambda: api.patch(actor, f"/{todo_id}/comments/{comment_id}", {"body": "y"}, 1),
            "delete": lambda: api.delete(actor, f"/{todo_id}/comments/{comment_id}", 1),
        }

    def test_private_todo_is_404_for_non_viewers(self, api, world):
        """private の ToDo(作成者・担当者以外は閲覧できない)のコメントは、一覧・投稿・編集・削除とも 404 todo_not_found。"""
        private = world.todo(visibility="private")
        comment = world.factory.comment(world.a.ctx, private, world.creator.user_id, body="SECRET-COMMENT")
        for name, call in self.all_calls(api, world.outsider, private, comment).items():
            response = call()
            problem(response, status=404, code="todo_not_found")
            check.is_not_in("SECRET-COMMENT", response.text, name)

    def test_deleted_todo_is_404_even_for_admin(self, api, world, todo):
        """削除した ToDo のコメントは、管理者でも 404 todo_not_found。"""
        comment = new_comment(api, world.creator, todo)
        check.equal(api.delete(world.creator, f"/{todo}", 1).status_code, 204)
        for name, call in self.all_calls(api, world.admin, todo, comment["id"]).items():
            problem(call(), status=404, code="todo_not_found")

    def test_other_tenant_todo_is_404_for_every_operation(self, api, world):
        """テナント A の管理者が B の ToDo のコメントを操作しても、4 操作とも 404 todo_not_found。B のコメントは変わらない。"""
        foreign = world.factory.add(world.b.ctx, world.b_member.user_id, visibility="tenant")
        foreign_comment = world.factory.comment(world.b.ctx, foreign, world.b_member.user_id, body="B comment")
        for name, call in self.all_calls(api, world.admin, foreign, foreign_comment).items():
            response = call()
            problem(response, status=404, code="todo_not_found")
            check.is_not_in("B comment", response.text, name)
        rows = world.ap_db.rows(world.b.ctx, "SELECT body, version, deleted_at FROM t_todo_comment")
        check.equal([(r["body"], r["version"], r["deleted_at"]) for r in rows], [("B comment", 1, None)])

    def test_other_tenant_comment_id_on_own_todo(self, api, world, todo):
        """自テナントの ToDo に他テナントのコメント ID を指定すると 404 todo_comment_not_found(存在を明かさない)。"""
        foreign = world.factory.add(world.b.ctx, world.b_member.user_id, visibility="tenant")
        foreign_comment = world.factory.comment(world.b.ctx, foreign, world.b_member.user_id)
        problem(api.patch(world.admin, f"/{todo}/comments/{foreign_comment}", {"body": "x"}, 1), status=404, code="todo_comment_not_found")
        problem(api.delete(world.admin, f"/{todo}/comments/{foreign_comment}", 1), status=404, code="todo_comment_not_found")

    def test_comment_of_another_todo_in_same_tenant(self, api, world, todo):
        """同じテナントの別の ToDo のコメント ID は 404 todo_comment_not_found。存在しない ID も同じ。"""
        other = world.todo()
        other_comment = new_comment(api, world.creator, other)
        for comment_id in (other_comment["id"], uuid.uuid4()):
            problem(api.patch(world.creator, f"/{todo}/comments/{comment_id}", {"body": "x"}, 1), status=404, code="todo_comment_not_found")
            problem(api.delete(world.creator, f"/{todo}/comments/{comment_id}", 1), status=404, code="todo_comment_not_found")
        check.equal(api.get(world.creator, f"/{other}/comments").json()["items"][0]["body"], "hello")

    def test_malformed_ids_are_422(self, api, world, todo):
        """UUID でない ID は 422(validation_error。パスの形式の誤り)。"""
        problem(api.get(world.creator, "/not-a-uuid/comments"), status=422, code="validation_error")
        problem(api.delete(world.creator, f"/{todo}/comments/nope", 1), status=422, code="validation_error")


# ---------------------------------------------------------------------------
# チェックリスト
# ---------------------------------------------------------------------------
class TestChecklistGet:
    """GET /todos/{id}/checklist。"""

    def test_empty_checklist_and_etag(self, api, world, todo):
        """空のチェックリスト: ETag は "1"(チェックリストの版)、items は空、進捗 0/0、権限つき。"""
        response = api.get(world.viewer, f"/{todo}/checklist")
        body = response.json()
        check.equal(response.status_code, 200)
        check.equal(response.headers["ETag"], '"1"')
        check.equal((body["todo_id"], body["version"], body["items"], body["done_count"], body["total_count"]), (str(todo), 1, [], 0, 0))
        check.equal(set(body), {"todo_id", "version", "items", "done_count", "total_count", "permissions"})

    def test_etag_is_the_checklist_version_not_the_todo_version(self, api, world, todo):
        """ETag はチェックリストの版(項目を 2 件追加して "3")。ToDo 本体の ETag("1")とは別。"""
        new_item(api, world.creator, todo, "a")
        new_item(api, world.creator, todo, "b")
        response = api.get(world.creator, f"/{todo}/checklist")
        check.equal((response.headers["ETag"], response.json()["version"]), ('"3"', 3))
        check.equal(api.get(world.creator, f"/{todo}").headers["ETag"], '"1"')

    def test_items_in_order_with_item_shape(self, api, world, todo):
        """項目は position の順で、id / title / position / is_done / done_at / done_by / version / created_at / updated_at を持つ。"""
        new_item(api, world.creator, todo, "a")
        new_item(api, world.creator, todo, "b")
        new_item(api, world.creator, todo, "first", position=0)
        body = api.get(world.viewer, f"/{todo}/checklist").json()
        check.equal([(i["title"], i["position"]) for i in body["items"]], [("first", 0), ("a", 1), ("b", 2)])
        item = body["items"][0]
        check.equal(set(item), {"id", "title", "position", "is_done", "done_at", "done_by", "version", "created_at", "updated_at"})
        check.equal((item["is_done"], item["done_at"], item["done_by"], item["version"]), (False, None, None, 1))

    @pytest.mark.parametrize(
        ("who", "expected"),
        [("admin", {"can_edit": True, "can_check": True}), ("creator", {"can_edit": True, "can_check": True}), ("assignee", {"can_edit": False, "can_check": True}), ("viewer", {"can_edit": False, "can_check": False})],
    )
    def test_permissions_per_viewer(self, api, world, todo, who, expected):
        """permissions: 作成者・admin = 編集もチェックも可、担当者 = チェックのみ、閲覧だけ = 不可。"""
        check.equal(api.get(getattr(world, who), f"/{todo}/checklist").json()["permissions"], expected)

    def test_done_by_is_the_user(self, api, world, todo):
        """完了した項目の done_by は表示名つきのユーザー、done_at は UTC(Z)。進捗は 1/2。"""
        first = new_item(api, world.creator, todo, "a")["items"][0]
        new_item(api, world.creator, todo, "b")
        response = api.patch(world.assignee, f"/{todo}/checklist/items/{first['id']}", {"is_done": True}, 1)
        done = response.json()["items"][0]
        check.equal((response.json()["done_count"], response.json()["total_count"]), (1, 2))
        check.equal(done["done_by"], {"id": str(world.assignee.user_id), "display_name": "Assignee Actor", "is_active": True})
        check.is_true(done["done_at"].endswith("Z"))

    def test_not_found_variants(self, api, world):
        """閲覧できない ToDo・他テナントの ToDo・削除済みの ToDo は 404 todo_not_found。"""
        private = world.todo(visibility="private")
        problem(api.get(world.outsider, f"/{private}/checklist"), status=404, code="todo_not_found")
        foreign = world.factory.add(world.b.ctx, world.b_member.user_id, visibility="tenant")
        problem(api.get(world.admin, f"/{foreign}/checklist"), status=404, code="todo_not_found")
        problem(api.get(world.admin, f"/{uuid.uuid4()}/checklist"), status=404, code="todo_not_found")


class TestChecklistAdd:
    """POST /todos/{id}/checklist/items。"""

    def test_created_with_whole_checklist_and_etag(self, api, world, todo):
        """201。If-Match は不要。応答はチェックリスト全体で、ETag は新しいチェックリストの版("2")。position 指定で挿入できる。"""
        response = api.post(world.creator, f"/{todo}/checklist/items", {"title": "  first  "})
        body = response.json()
        check.equal(response.status_code, 201, response.text)
        check.equal((response.headers["ETag"], body["version"], [i["title"] for i in body["items"]], body["total_count"]), ('"2"', 2, ["first"], 1))
        inserted = api.post(world.admin, f"/{todo}/checklist/items", {"title": "head", "position": 0}).json()
        check.equal([(i["title"], i["position"]) for i in inserted["items"]], [("head", 0), ("first", 1)])

    @pytest.mark.parametrize("who", ["assignee", "viewer", "outsider"])
    def test_only_creator_and_admin_can_add(self, api, world, todo, who):
        """作成者・admin 以外(担当者を含む)の追加は 403(operation = edit_checklist)。"""
        body = problem(api.post(getattr(world, who), f"/{todo}/checklist/items", {"title": "x"}), status=403, code="todo_operation_forbidden")
        check.equal(body["operation"], "edit_checklist")
        check.equal(api.get(world.creator, f"/{todo}/checklist").json()["items"], [])

    @pytest.mark.parametrize("body", [{"title": ""}, {"title": "x" * 201}, {}, {"title": "a", "position": -1}, {"title": "a", "position": "x"}])
    def test_invalid_input_is_422(self, api, world, todo, body):
        """項目名が空・201 文字・未指定、position が負・数値でないとき 422 validation_error。"""
        problem(api.post(world.creator, f"/{todo}/checklist/items", body), status=422, code="validation_error")

    def test_whitespace_title_is_422_invalid_todo_input(self, api, world, todo):
        """空白だけの項目名は 422(invalid_todo_input。errors に title)。"""
        body = problem(api.post(world.creator, f"/{todo}/checklist/items", {"title": "   "}), status=422, code="invalid_todo_input")
        check.is_in(("title", "required"), [(e["field"], e["code"]) for e in body["errors"]])

    def test_limit_of_one_hundred_items(self, api, world, todo):
        """項目は 100 件まで: 100 件目は 201、101 件目は 422(invalid_todo_input、errors = items / too_many)。件数は 100 のまま。"""
        seed_items(world, todo, 99)
        check.equal(api.post(world.creator, f"/{todo}/checklist/items", {"title": "100th"}).json()["total_count"], 100)
        body = problem(api.post(world.creator, f"/{todo}/checklist/items", {"title": "101st"}), status=422, code="invalid_todo_input")
        check.equal([(e["field"], e["code"]) for e in body["errors"]], [("items", "too_many")])
        check.equal(api.get(world.creator, f"/{todo}/checklist").json()["total_count"], 100)

    def test_csrf_and_not_found(self, api, world, todo):
        """CSRF 対策のヘッダーが無い POST は 403、閲覧できない ToDo・他テナントの ToDo は 404 todo_not_found。"""
        check.equal(api.client.post(f"{TODOS}/{todo}/checklist/items", json={"title": "x"}, headers=world.creator.headers).status_code, 403)
        private = world.todo(visibility="private")
        problem(api.post(world.outsider, f"/{private}/checklist/items", {"title": "x"}), status=404, code="todo_not_found")
        foreign = world.factory.add(world.b.ctx, world.b_member.user_id, visibility="tenant")
        problem(api.post(world.admin, f"/{foreign}/checklist/items", {"title": "x"}), status=404, code="todo_not_found")


class TestChecklistUpdate:
    """PATCH /todos/{id}/checklist/items/{item_id}。If-Match は項目の版。"""

    @pytest.fixture
    def item(self, api, world, todo):
        return new_item(api, world.creator, todo, "one")["items"][0]

    def test_rename_bumps_item_version_not_checklist_version(self, api, world, todo, item):
        """名前変更は 200。項目の版が 2 になり、ETag(チェックリストの版)は変わらない("2")。応答は全体。"""
        response = api.patch(world.creator, f"/{todo}/checklist/items/{item['id']}", {"title": "renamed"}, item["version"])
        body = response.json()
        check.equal(response.status_code, 200, response.text)
        check.equal((response.headers["ETag"], body["version"], body["items"][0]["title"], body["items"][0]["version"]), ('"2"', 2, "renamed", 2))

    def test_assignee_can_check_but_not_rename(self, api, world, todo, item):
        """担当者はチェックだけ通る(200)。名前の変更は 403(operation = edit_checklist)で、チェックも同時には適用されない。"""
        path = f"/{todo}/checklist/items/{item['id']}"
        body = problem(api.patch(world.assignee, path, {"title": "renamed", "is_done": True}, 1), status=403, code="todo_operation_forbidden")
        check.equal(body["operation"], "edit_checklist")
        current = api.get(world.creator, f"/{todo}/checklist").json()["items"][0]
        check.equal((current["title"], current["is_done"], current["version"]), ("one", False, 1))
        response = api.patch(world.assignee, path, {"is_done": True}, 1)
        check.equal((response.status_code, response.json()["items"][0]["is_done"], response.json()["done_count"]), (200, True, 1))

    def test_assignee_edit_screen_sending_the_same_title_passes(self, api, world, todo, item):
        """編集画面が名前も一緒に送っても、名前が同じなら変更とみなさず、担当者のチェックは通る(§10 #18)。"""
        response = api.patch(world.assignee, f"/{todo}/checklist/items/{item['id']}", {"title": "one", "is_done": True}, 1)
        check.equal((response.status_code, response.json()["items"][0]["title"], response.json()["items"][0]["is_done"]), (200, "one", True))

    def test_viewer_cannot_check(self, api, world, todo, item):
        """閲覧だけの member のチェックは 403(operation = check_checklist_item)。"""
        body = problem(api.patch(world.viewer, f"/{todo}/checklist/items/{item['id']}", {"is_done": True}, 1), status=403, code="todo_operation_forbidden")
        check.equal(body["operation"], "check_checklist_item")

    def test_same_value_patch_changes_nothing(self, api, world, todo, item):
        """値が変わらない PATCH(同じ名前・同じ完了状態・空のボディ)は 200 で、項目の版も ETag も変わらない。閲覧だけの人でも通る。"""
        path = f"/{todo}/checklist/items/{item['id']}"
        for actor, body in ((world.creator, {"title": "one"}), (world.creator, {"is_done": False}), (world.creator, {}), (world.viewer, {"title": "one", "is_done": False})):
            response = api.patch(actor, path, body, 1)
            check.equal((response.status_code, response.headers["ETag"], response.json()["items"][0]["version"]), (200, '"2"', 1), body)

    def test_uncheck_clears_done_fields(self, api, world, todo, item):
        """未完了に戻すと done_at / done_by が消える。"""
        path = f"/{todo}/checklist/items/{item['id']}"
        api.patch(world.assignee, path, {"is_done": True}, 1)
        body = api.patch(world.assignee, path, {"is_done": False}, 2).json()
        check.equal((body["items"][0]["is_done"], body["items"][0]["done_at"], body["items"][0]["done_by"], body["items"][0]["version"]), (False, None, None, 3))

    def test_if_match_required_invalid_and_stale(self, api, world, todo, item):
        """If-Match が無ければ 428、形式不正は 400(invalid_if_match)、古い項目の版は 412(todo_checklist_version_conflict、target = item)。"""
        path = f"/{todo}/checklist/items/{item['id']}"
        problem(api.patch(world.creator, path, {"title": "x"}), status=428, code="precondition_required")
        problem(api.client.patch(f"{TODOS}{path}", json={"title": "x"}, headers=with_csrf(world.creator.headers, **{"If-Match": "oops"})), status=400, code="invalid_if_match")
        api.patch(world.creator, path, {"title": "two"}, 1)
        body = problem(api.patch(world.creator, path, {"title": "three"}, 1), status=412, code="todo_checklist_version_conflict")
        check.equal(body["target"], "item")
        check.equal(api.get(world.creator, f"/{todo}/checklist").json()["items"][0]["title"], "two")

    @pytest.mark.parametrize("body", [{"title": None}, {"is_done": None}, {"title": ""}, {"title": "x" * 201}, {"is_done": "maybe"}, {"is_done": 2}])
    def test_invalid_body_is_422(self, api, world, todo, item, body):
        """null・空・201 文字・真偽値として解釈できない値は 422 validation_error(null は未指定と区別して拒否する)。"""
        problem(api.patch(world.creator, f"/{todo}/checklist/items/{item['id']}", body, 1), status=422, code="validation_error")

    def test_item_of_another_todo_and_unknown_item(self, api, world, todo, item):
        """別の ToDo の項目 ID・存在しない ID・他テナントの項目 ID は 404 todo_checklist_item_not_found。"""
        other = world.todo()
        other_item = new_item(api, world.creator, other, "other")["items"][0]
        foreign = world.factory.add(world.b.ctx, world.b_member.user_id, visibility="tenant")
        world.factory.item(world.b.ctx, foreign, world.b_member.user_id)
        foreign_item = world.ap_db.rows(world.b.ctx, "SELECT id FROM t_todo_checklist_item")[0]["id"]
        for item_id in (other_item["id"], uuid.uuid4(), foreign_item):
            problem(api.patch(world.creator, f"/{todo}/checklist/items/{item_id}", {"title": "x"}, 1), status=404, code="todo_checklist_item_not_found")
        check.equal(api.get(world.creator, f"/{other}/checklist").json()["items"][0]["title"], "other")

    def test_invisible_todo_is_404_todo_not_found(self, api, world):
        """閲覧できない ToDo では、項目が存在しても 404 todo_not_found(項目の存在を明かさない)。"""
        private = world.todo(visibility="private")
        world.factory.item(world.a.ctx, private, world.creator.user_id)
        item_id = world.ap_db.rows(world.a.ctx, "SELECT id FROM t_todo_checklist_item WHERE todo_id = :t", t=private)[0]["id"]
        problem(api.patch(world.outsider, f"/{private}/checklist/items/{item_id}", {"is_done": True}, 1), status=404, code="todo_not_found")

    def test_csrf_is_required(self, api, world, todo, item):
        """CSRF 対策のヘッダーが無い PATCH は 403。"""
        check.equal(api.client.patch(f"{TODOS}/{todo}/checklist/items/{item['id']}", json={"title": "x"}, headers={**world.creator.headers, **etag(1)}).status_code, 403)


class TestChecklistDelete:
    """DELETE /todos/{id}/checklist/items/{item_id}。"""

    def test_returns_200_with_whole_checklist(self, api, world, todo):
        """200 で削除後のチェックリスト全体を返す(204 ではない)。position は詰め直され、ETag(チェックリストの版)は +1。"""
        view = None
        for title in ("a", "b", "c"):
            view = new_item(api, world.creator, todo, title)
        first = view["items"][0]
        response = api.delete(world.creator, f"/{todo}/checklist/items/{first['id']}", first["version"])
        body = response.json()
        check.equal(response.status_code, 200, response.text)
        check.equal(([(i["title"], i["position"]) for i in body["items"]], body["total_count"], response.headers["ETag"], body["version"]), ([("b", 0), ("c", 1)], 2, f'"{view["version"] + 1}"', view["version"] + 1))

    def test_if_match_required_and_stale_is_item_target(self, api, world, todo):
        """If-Match が無ければ 428、古い項目の版は 412(target = item)。項目は残る。"""
        item = new_item(api, world.creator, todo, "x")["items"][0]
        path = f"/{todo}/checklist/items/{item['id']}"
        problem(api.delete(world.creator, path), status=428, code="precondition_required")
        body = problem(api.delete(world.creator, path, 9), status=412, code="todo_checklist_version_conflict")
        check.equal(body["target"], "item")
        check.equal(api.get(world.creator, f"/{todo}/checklist").json()["total_count"], 1)

    @pytest.mark.parametrize("who", ["assignee", "viewer"])
    def test_non_owner_gets_403(self, api, world, todo, who):
        """作成者・admin 以外の削除は 403(operation = edit_checklist)。"""
        item = new_item(api, world.creator, todo, "x")["items"][0]
        body = problem(api.delete(getattr(world, who), f"/{todo}/checklist/items/{item['id']}", 1), status=403, code="todo_operation_forbidden")
        check.equal(body["operation"], "edit_checklist")

    def test_deleted_item_is_404_afterwards(self, api, world, todo):
        """削除済み(物理削除)の項目の再削除・更新は 404 todo_checklist_item_not_found。"""
        item = new_item(api, world.creator, todo, "x")["items"][0]
        path = f"/{todo}/checklist/items/{item['id']}"
        check.equal(api.delete(world.admin, path, 1).status_code, 200)
        problem(api.delete(world.admin, path, 1), status=404, code="todo_checklist_item_not_found")
        problem(api.patch(world.admin, path, {"title": "x"}, 1), status=404, code="todo_checklist_item_not_found")

    def test_csrf_is_required(self, api, world, todo):
        """CSRF 対策のヘッダーが無い DELETE は 403。"""
        item = new_item(api, world.creator, todo, "x")["items"][0]
        check.equal(api.client.delete(f"{TODOS}/{todo}/checklist/items/{item['id']}", headers={**world.creator.headers, **etag(1)}).status_code, 403)


class TestChecklistOrder:
    """PUT /todos/{id}/checklist/order。If-Match はチェックリスト全体の版。"""

    @pytest.fixture
    def checklist(self, api, world, todo):
        view = None
        for title in ("a", "b", "c"):
            view = new_item(api, world.creator, todo, title)
        return view

    def test_reorder_returns_whole_checklist_and_bumps_version(self, api, world, todo, checklist):
        """200。並びが変わり、ETag(チェックリストの版)が +1。項目の版は変わらない。"""
        ids = [i["id"] for i in reversed(checklist["items"])]
        response = api.put(world.creator, f"/{todo}/checklist/order", {"item_ids": ids}, checklist["version"])
        body = response.json()
        check.equal(response.status_code, 200, response.text)
        check.equal(([i["id"] for i in body["items"]], [i["position"] for i in body["items"]], response.headers["ETag"]), (ids, [0, 1, 2], f'"{checklist["version"] + 1}"'))
        check.equal([i["version"] for i in body["items"]], [1, 1, 1])

    def test_if_match_required_invalid_and_stale_is_checklist_target(self, api, world, todo, checklist):
        """If-Match が無ければ 428、形式不正は 400、古いチェックリストの版は 412(target = checklist)。項目の版を渡しても通らない。"""
        ids = [i["id"] for i in reversed(checklist["items"])]
        path = f"/{todo}/checklist/order"
        problem(api.put(world.creator, path, {"item_ids": ids}), status=428, code="precondition_required")
        problem(api.client.put(f"{TODOS}{path}", json={"item_ids": ids}, headers=with_csrf(world.creator.headers, **{"If-Match": "oops"})), status=400, code="invalid_if_match")
        body = problem(api.put(world.creator, path, {"item_ids": ids}, checklist["version"] - 1), status=412, code="todo_checklist_version_conflict")
        check.equal(body["target"], "checklist")
        check.equal([i["title"] for i in api.get(world.creator, f"/{todo}/checklist").json()["items"]], ["a", "b", "c"])

    def test_other_changes_make_the_order_version_stale(self, api, world, todo, checklist):
        """項目の追加でチェックリストの版が上がるため、その前に取得した版での並べ替えは 412(target = checklist)。"""
        ids = [i["id"] for i in reversed(checklist["items"])]
        new_item(api, world.creator, todo, "d")
        body = problem(api.put(world.creator, f"/{todo}/checklist/order", {"item_ids": ids}, checklist["version"]), status=412, code="todo_checklist_version_conflict")
        check.equal(body["target"], "checklist")

    @pytest.mark.parametrize("case", ["missing", "unknown", "duplicate", "empty"])
    def test_mismatching_set_is_422(self, api, world, todo, checklist, case):
        """項目の集合と一致しない item_ids(不足・未知の ID・重複・空)は 422(invalid_todo_input、errors = item_ids / mismatch)。何も変わらない。"""
        ids = [i["id"] for i in checklist["items"]]
        wrong = {"missing": ids[:2], "unknown": [*ids, str(uuid.uuid4())], "duplicate": [ids[0], ids[0], ids[1]], "empty": []}[case]
        body = problem(api.put(world.creator, f"/{todo}/checklist/order", {"item_ids": wrong}, checklist["version"]), status=422, code="invalid_todo_input")
        check.equal([(e["field"], e["code"]) for e in body["errors"]], [("item_ids", "mismatch")])
        check.equal(api.get(world.creator, f"/{todo}/checklist").json()["version"], checklist["version"])

    @pytest.mark.parametrize("body", [{"item_ids": ["x"]}, {"item_ids": "abc"}, {}, {"item_ids": None}])
    def test_malformed_item_ids_are_422_validation_error(self, api, world, todo, checklist, body):
        """UUID でない要素・配列でない・未指定は 422 validation_error。"""
        problem(api.put(world.creator, f"/{todo}/checklist/order", body, checklist["version"]), status=422, code="validation_error")

    @pytest.mark.parametrize("who", ["assignee", "viewer"])
    def test_non_owner_gets_403(self, api, world, todo, checklist, who):
        """作成者・admin 以外の並べ替えは 403(operation = edit_checklist)。"""
        ids = [i["id"] for i in reversed(checklist["items"])]
        body = problem(api.put(getattr(world, who), f"/{todo}/checklist/order", {"item_ids": ids}, checklist["version"]), status=403, code="todo_operation_forbidden")
        check.equal(body["operation"], "edit_checklist")

    def test_same_order_is_a_noop(self, api, world, todo, checklist):
        """現在と同じ並びの PUT は 200 で、チェックリストの版は変わらない。"""
        ids = [i["id"] for i in checklist["items"]]
        response = api.put(world.creator, f"/{todo}/checklist/order", {"item_ids": ids}, checklist["version"])
        check.equal((response.status_code, response.headers["ETag"]), (200, f'"{checklist["version"]}"'))

    def test_csrf_and_not_found(self, api, world, todo, checklist):
        """CSRF 対策のヘッダーが無い PUT は 403。閲覧できない ToDo・他テナントの ToDo は 404。"""
        check.equal(api.client.put(f"{TODOS}/{todo}/checklist/order", json={"item_ids": []}, headers={**world.creator.headers, **etag(1)}).status_code, 403)
        foreign = world.factory.add(world.b.ctx, world.b_member.user_id, visibility="tenant")
        problem(api.put(world.admin, f"/{foreign}/checklist/order", {"item_ids": []}, 1), status=404, code="todo_not_found")


# ---------------------------------------------------------------------------
# ToDo 本体の ETag
# ---------------------------------------------------------------------------
class TestTodoEtagIsUntouched:
    """コメント・チェックリストの操作は ToDo 本体の ETag(version)・updated_at を変えない(§10 #16)。"""

    def test_todo_etag_and_updated_at_do_not_change(self, api, world, todo):
        """コメントの投稿・編集・削除とチェックリストの追加・名前変更・チェック・並べ替え・削除の後でも、ToDo の ETag と updated_at は同じで、古い If-Match での PATCH が通る。"""
        before = api.get(world.creator, f"/{todo}")
        comment = new_comment(api, world.viewer, todo, "a")
        api.patch(world.viewer, f"/{todo}/comments/{comment['id']}", {"body": "b"}, 1)
        new_comment(api, world.creator, todo, "c")
        api.delete(world.admin, f"/{todo}/comments/{comment['id']}", 2)
        view = new_item(api, world.creator, todo, "x")
        view = new_item(api, world.creator, todo, "y")
        api.patch(world.creator, f"/{todo}/checklist/items/{view['items'][0]['id']}", {"title": "x2"}, 1)
        api.patch(world.assignee, f"/{todo}/checklist/items/{view['items'][1]['id']}", {"is_done": True}, 1)
        view = api.get(world.creator, f"/{todo}/checklist").json()
        reordered = api.put(world.creator, f"/{todo}/checklist/order", {"item_ids": [i["id"] for i in reversed(view["items"])]}, view["version"]).json()
        api.delete(world.creator, f"/{todo}/checklist/items/{reordered['items'][0]['id']}", reordered["items"][0]["version"])
        after = api.get(world.creator, f"/{todo}")
        check.equal((after.headers["ETag"], after.json()["version"], after.json()["updated_at"], after.json()["updated_by"]), (before.headers["ETag"], 1, before.json()["updated_at"], before.json()["updated_by"]))
        patched = api.patch(world.creator, f"/{todo}", {"title": "still editable"}, 1)
        check.equal((patched.status_code, patched.headers["ETag"]), (200, '"2"'))

    def test_todo_edit_does_not_change_comment_or_checklist_etag(self, api, world, todo):
        """逆に、ToDo 本体の編集ではコメントの版・チェックリストの版は変わらない。"""
        comment = new_comment(api, world.viewer, todo, "a")
        view = new_item(api, world.creator, todo, "x")
        api.patch(world.creator, f"/{todo}", {"title": "renamed"}, 1)
        check.equal(api.get(world.viewer, f"/{todo}/comments").json()["items"][0]["version"], comment["version"])
        check.equal(api.get(world.viewer, f"/{todo}/checklist").headers["ETag"], f'"{view["version"]}"')

    def test_detail_shows_counters_and_permissions(self, api, world, todo):
        """詳細にはチェックリストの進捗・コメント数・8 項目の権限が反映される(閲覧だけの人は can_comment のみ true)。"""
        new_comment(api, world.viewer, todo)
        item = new_item(api, world.creator, todo, "x")["items"][0]
        api.patch(world.assignee, f"/{todo}/checklist/items/{item['id']}", {"is_done": True}, 1)
        body = api.get(world.viewer, f"/{todo}").json()
        check.equal((body["checklist"], body["comment_count"]), ({"done_count": 1, "total_count": 1}, 1))
        check.equal(
            body["permissions"],
            {"can_edit_fields": False, "can_change_status": False, "can_change_visibility": False, "can_change_assignees": False, "can_delete": False, "can_comment": True, "can_edit_checklist": False, "can_check_checklist": False},
        )


# ---------------------------------------------------------------------------
# 一覧の総件数・作成者・件数
# ---------------------------------------------------------------------------
class TestListExtras:
    """GET /todos の include_total と、creator / updater / checklist / comment_count。"""

    def test_include_total(self, api, world):
        """include_total を省略または false にすると total は null、true にすると絞り込み後の総件数(ページサイズ・カーソルに依存しない)。"""
        for index in range(5):
            world.todo(title=f"t{index}", status="open" if index < 3 else "done")
        check.is_none(api.get(world.admin).json()["total"])
        check.is_none(api.get(world.admin, include_total="false").json()["total"])
        first = api.get(world.admin, include_total="true", limit=2).json()
        second = api.get(world.admin, include_total="true", limit=2, cursor=first["next_cursor"]).json()
        check.equal((first["total"], second["total"], len(first["items"])), (5, 5, 2))
        check.equal(api.get(world.admin, include_total="true", status="open").json()["total"], 3)
        check.equal(api.get(world.admin, include_total="true", status="open", limit=1).json()["total"], 3)

    def test_total_respects_visibility_scope_and_tenant(self, api, world):
        """総件数は閲覧範囲・表示範囲を適用し、論理削除済みと他テナントを数えない。"""
        world.todo(title="visible")
        world.todo(title="private", visibility="private", assignees=[])
        world.todo(title="deleted", deleted=True)
        world.factory.add(world.b.ctx, world.b_member.user_id, title="B", visibility="tenant")
        check.equal(api.get(world.outsider, include_total="true").json()["total"], 1)
        check.equal(api.get(world.creator, include_total="true").json()["total"], 2)
        check.equal(api.get(world.admin, include_total="true").json()["total"], 2)
        check.equal(api.get(world.assignee, include_total="true", scope="assigned").json()["total"], 2 - 1)
        check.equal(api.get(world.b_admin, include_total="true").json()["total"], 1)

    def test_invalid_include_total_is_422(self, api, world):
        """include_total が真偽値でなければ 422。"""
        problem(api.get(world.admin, include_total="maybe"), status=422, code="validation_error")

    def test_creator_updater_checklist_and_comment_count(self, api, world, todo):
        """一覧の各要素は creator / updater(id・display_name・is_active)・checklist(done_count / total_count)・comment_count を持つ。更新者は最後に本体を更新した人。コメント数は削除済みを数えない。"""
        new_comment(api, world.viewer, todo, "a")
        gone = new_comment(api, world.viewer, todo, "b")
        api.delete(world.viewer, f"/{todo}/comments/{gone['id']}", 1)
        first = new_item(api, world.creator, todo, "x")["items"][0]
        new_item(api, world.creator, todo, "y")
        api.patch(world.assignee, f"/{todo}/checklist/items/{first['id']}", {"is_done": True}, 1)
        api.patch(world.admin, f"/{todo}", {"title": "edited by admin"}, 1)
        item = api.get(world.viewer, limit=10).json()["items"][0]
        check.equal(item["creator"], {"id": str(world.creator.user_id), "display_name": "Creator Actor", "is_active": True})
        check.equal(item["updater"], {"id": str(world.admin.user_id), "display_name": "Admin Actor", "is_active": True})
        check.equal((item["checklist"], item["comment_count"]), ({"done_count": 1, "total_count": 2}, 1))

    def test_zero_counts_and_detail_matches_list(self, api, world, todo):
        """何も無い ToDo は 0/0・コメント 0。詳細(permissions を除く)と一覧の要素の creator / updater / checklist / comment_count が同じ。"""
        listed = api.get(world.viewer).json()["items"][0]
        detail = api.get(world.viewer, f"/{todo}").json()
        check.equal((listed["checklist"], listed["comment_count"]), ({"done_count": 0, "total_count": 0}, 0))
        for key in ("creator", "updater", "checklist", "comment_count", "version", "updated_at"):
            check.equal(listed[key], detail[key], key)
        check.is_in("permissions", detail)
        check.is_not_in("permissions", listed)


# ---------------------------------------------------------------------------
# ホームの要約
# ---------------------------------------------------------------------------
SUMMARY = f"{TODOS}/summary"


class TestSummary:
    """GET /todos/summary。"""

    def get(self, api, actor, **params):
        return api.client.get(SUMMARY, headers=actor.headers, params=params)

    def test_summary_is_not_swallowed_by_todo_id_route(self, api, world, todo):
        """/todos/summary は /{todo_id} と解釈されない(UUID の 422 や 404 にならず、要約を返す)。/{todo_id} は従来どおり ToDo の詳細。"""
        response = self.get(api, world.assignee, today=TODAY.isoformat())
        check.equal(response.status_code, 200, response.text)
        check.equal(set(response.json()), {"today", "due_soon_until", "assigned", "created"})
        check.equal(api.get(world.assignee, f"/{todo}").json()["id"], str(todo))
        check.equal(api.get(world.assignee, "/summaryx").status_code, 422)

    def test_response_shape_and_dates(self, api, world):
        """today を返し、due_soon_until は today + due_soon_days(既定 7 日)。assigned は 4 項目、created は 3 項目。"""
        body = self.get(api, world.assignee, today="2030-06-15").json()
        check.equal((body["today"], body["due_soon_until"]), ("2030-06-15", "2030-06-22"))
        check.equal(set(body["assigned"]), {"open", "in_progress", "overdue", "due_soon"})
        check.equal(set(body["created"]), {"open", "in_progress", "overdue"})
        custom = self.get(api, world.assignee, today="2030-06-15", due_soon_days=30).json()
        check.equal(custom["due_soon_until"], "2030-07-15")

    def test_omitted_today_uses_a_utc_date(self, api, world):
        """today を省略するとサーバーの UTC の日付。"""
        before = dt.datetime.now(dt.UTC).date()
        body = self.get(api, world.assignee).json()
        check.is_in(body["today"], {before.isoformat(), dt.datetime.now(dt.UTC).date().isoformat()})

    @pytest.mark.parametrize(
        ("offset", "overdue", "due_soon"),
        [(-1, 1, 0), (0, 0, 1), (7, 0, 1), (8, 0, 0)],
    )
    def test_boundaries(self, api, world, offset, overdue, due_soon):
        """担当 ToDo の期限: 前日 = 期限切れ、当日・+7 日 = 期限間近、+8 日 = どちらでもない。"""
        world.todo(due_date=day(offset))
        body = self.get(api, world.assignee, today=TODAY.isoformat()).json()
        check.equal((body["assigned"]["open"], body["assigned"]["overdue"], body["assigned"]["due_soon"]), (1, overdue, due_soon))

    def test_counts_assigned_and_created(self, api, world):
        """担当と作成を別々に数える。完了・論理削除は数えない。担当かつ作成の ToDo は両方に入る。"""
        world.factory.add(world.a.ctx, world.creator.user_id, status="in_progress", due_date=day(-3), assignees=[world.creator.user_id], visibility="tenant")
        world.todo(due_date=day(2))
        world.todo(status="done", due_date=day(-9))
        world.todo(due_date=day(-1), deleted=True)
        world.todo(visibility="private", assignees=[world.assignee.user_id], due_date=day(1))
        body = self.get(api, world.creator, today=TODAY.isoformat()).json()
        check.equal(body["assigned"], {"open": 0, "in_progress": 1, "overdue": 1, "due_soon": 0})
        check.equal(body["created"], {"open": 2, "in_progress": 1, "overdue": 1})
        mine = self.get(api, world.assignee, today=TODAY.isoformat()).json()
        check.equal(mine["assigned"], {"open": 2, "in_progress": 0, "overdue": 0, "due_soon": 2})
        check.equal(mine["created"], {"open": 0, "in_progress": 0, "overdue": 0})

    def test_does_not_count_out_of_scope_or_other_tenants(self, api, world):
        """閲覧範囲外(他人の private)・他テナント・自分に関係の無い tenant 公開の ToDo は数えない。管理者も自分が担当・作成したものだけ。"""
        world.todo(visibility="private", assignees=[], due_date=day(-1))
        world.todo(due_date=day(-1))
        world.factory.add(world.b.ctx, world.b_member.user_id, due_date=day(-1), assignees=[world.b_member.user_id], visibility="tenant")
        for actor in (world.outsider, world.viewer, world.admin):
            body = self.get(api, actor, today=TODAY.isoformat()).json()
            check.equal((body["assigned"], body["created"]), ({"open": 0, "in_progress": 0, "overdue": 0, "due_soon": 0}, {"open": 0, "in_progress": 0, "overdue": 0}), str(actor.user_id))
        theirs = self.get(api, world.b_member, today=TODAY.isoformat()).json()
        check.equal((theirs["assigned"]["open"], theirs["assigned"]["overdue"], theirs["created"]["open"]), (1, 1, 1))

    @pytest.mark.parametrize("days", [0, 31, -1, 100, "x", "1.5"])
    def test_due_soon_days_out_of_range_is_422(self, api, world, days):
        """due_soon_days が 1〜30 の範囲外・数値でないときは 422(validation_error、errors[].field に due_soon_days)。"""
        response = self.get(api, world.assignee, due_soon_days=days)
        body = problem(response, status=422, code="validation_error")
        check.is_in("due_soon_days", [e["field"] for e in body["errors"]])

    @pytest.mark.parametrize("days", [1, 30])
    def test_due_soon_days_bounds_are_accepted(self, api, world, days):
        """1 と 30 は受け付ける。"""
        check.equal(self.get(api, world.assignee, today=TODAY.isoformat(), due_soon_days=days).status_code, 200)

    @pytest.mark.parametrize("today", ["abc", "2030-02-30", "2030-13-01", "15/06/2030", "", "2030-06-15T10:00:00"])
    def test_invalid_today_is_422(self, api, world, today):
        """today が日付として不正(文字列・存在しない日付・時刻つき)なら 422(errors[].field に today)。"""
        body = problem(self.get(api, world.assignee, today=today), status=422, code="validation_error")
        check.is_in("today", [e["field"] for e in body["errors"]])

    def test_today_at_the_date_limit_is_422(self, api, world):
        """today + due_soon_days が日付の上限を超える場合は 422(サーバーエラーにしない)。"""
        response = self.get(api, world.assignee, today="9999-12-31")
        check.equal(response.status_code, 422, response.text)
        check.equal(response.headers["content-type"].split(";")[0], "application/problem+json")

    def test_unauthenticated_and_wrong_plane(self, api, admin):
        """Cookie が無い・CP のセッションでは 401。"""
        check.equal(api.client.get(SUMMARY).status_code, 401)
        check.equal(api.client.get(SUMMARY, headers=admin).status_code, 401)


# ---------------------------------------------------------------------------
# Problem Details の形・OpenAPI
# ---------------------------------------------------------------------------
class TestProblemExtensions:
    """新しいエラーの Problem Details(拡張メンバー)。共通の形そのものは ``test_70_problem_details`` が確認している。"""

    def test_403_and_412_extension_members(self, api, world, todo):
        """403 は operation、チェックリストの 412 は target を持つ。コメントの 412 には target が無い。type は code のケバブケース。"""
        comment = new_comment(api, world.viewer, todo)
        forbidden = problem(api.patch(world.creator, f"/{todo}/comments/{comment['id']}", {"body": "x"}, 1), status=403, code="todo_operation_forbidden")
        check.equal(forbidden["operation"], "edit_comment")
        item = new_item(api, world.creator, todo, "x")["items"][0]
        conflict = problem(api.patch(world.creator, f"/{todo}/checklist/items/{item['id']}", {"title": "y"}, 9), status=412, code="todo_checklist_version_conflict")
        check.equal((conflict["target"], conflict["type"]), ("item", "https://errors.rf-stack.example/todo-checklist-version-conflict"))
        stale = problem(api.patch(world.viewer, f"/{todo}/comments/{comment['id']}", {"body": "x"}, 9), status=412, code="todo_comment_version_conflict")
        check.is_not_in("target", stale)

    def test_404_codes_and_texts(self, api, world, todo):
        """404 は todo_not_found / todo_comment_not_found / todo_checklist_item_not_found の 3 種で、title・detail は日本語の固定文言。内部情報や ID を含まない。"""
        missing = uuid.uuid4()
        responses = [
            problem(api.get(world.admin, f"/{missing}/comments"), status=404, code="todo_not_found"),
            problem(api.delete(world.admin, f"/{todo}/comments/{missing}", 1), status=404, code="todo_comment_not_found"),
            problem(api.delete(world.admin, f"/{todo}/checklist/items/{missing}", 1), status=404, code="todo_checklist_item_not_found"),
        ]
        for body in responses:
            check.is_true(re.search(r"[぀-ヿ一-鿿]", body["title"]) and re.search(r"[぀-ヿ一-鿿]", body["detail"]))
            check.is_not_in(str(missing), body["title"] + body["detail"])
        check.equal(len({body["title"] for body in responses}), 3)

    def test_422_mismatch_and_too_many_have_japanese_messages(self, api, world, todo):
        """mismatch / too_many の errors[].message は日本語の固定文言(入力値を返さない)。"""
        view = new_item(api, world.creator, todo, "x")
        mismatch = problem(api.put(world.creator, f"/{todo}/checklist/order", {"item_ids": [str(uuid.uuid4())]}, view["version"]), status=422, code="invalid_todo_input")
        seed_items(world, todo, 99, start=1)
        too_many = problem(api.post(world.creator, f"/{todo}/checklist/items", {"title": "x"}), status=422, code="invalid_todo_input")
        for body in (mismatch, too_many):
            check.is_true(all(re.search(r"[぀-ヿ一-鿿]", e["message"]) for e in body["errors"]), body["errors"])
        check.equal([e["code"] for e in too_many["errors"]], ["too_many"])

    def test_every_error_carries_the_request_id_header(self, api, world, todo):
        """送ったリクエスト ID がヘッダーと本文の request_id に使われる。"""
        response = api.client.get(f"{TODOS}/{uuid.uuid4()}/checklist", headers={**world.admin.headers, "X-Request-ID": "collab-req-1"})
        check.equal((response.status_code, response.headers["X-Request-ID"], response.json()["request_id"]), (404, "collab-req-1", "collab-req-1"))


class TestOpenApi:
    """OpenAPI に新しいスキーマ・必須の If-Match・エラー応答がある(エンドポイントの一覧と If-Match の本数は ``test_70_problem_details`` が確認している)。"""

    @pytest.fixture(scope="class")
    def spec(self):
        return app.openapi()

    def operation(self, spec, method, path):
        return spec["paths"][f"/api/v1/todos{path}"][method]

    def test_new_schemas_exist_with_the_documented_fields(self, spec):
        """コメント・チェックリスト・要約のスキーマが components にあり、主なプロパティを持つ。"""
        schemas = spec["components"]["schemas"]
        expected = {
            "TodoCommentRead": {"id", "todo_id", "author", "body", "version", "created_at", "updated_at", "edited_at", "permissions"},
            "TodoCommentPermissionsRead": {"can_edit", "can_delete"},
            "TodoCommentWrite": {"body"},
            "TodoChecklistRead": {"todo_id", "version", "items", "done_count", "total_count", "permissions"},
            "TodoChecklistItemRead": {"id", "title", "position", "is_done", "done_at", "done_by", "version", "created_at", "updated_at"},
            "TodoChecklistItemCreate": {"title", "position"},
            "TodoChecklistItemUpdate": {"title", "is_done"},
            "TodoChecklistOrder": {"item_ids"},
            "TodoSummaryRead": {"today", "due_soon_until", "assigned", "created"},
            "TodoPermissionsRead": {"can_edit_fields", "can_change_status", "can_change_visibility", "can_change_assignees", "can_delete", "can_comment", "can_edit_checklist", "can_check_checklist"},
        }
        for name, properties in expected.items():
            check.is_in(name, schemas)
            check.equal(set(schemas[name]["properties"]), properties, name)
        check.is_true({"creator", "updater", "checklist", "comment_count"} <= set(schemas["TodoRead"]["properties"]))
        check.is_true({"creator", "updater", "checklist", "comment_count", "permissions"} <= set(schemas["TodoDetail"]["properties"]))

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("patch", "/{todo_id}/comments/{comment_id}"),
            ("delete", "/{todo_id}/comments/{comment_id}"),
            ("patch", "/{todo_id}/checklist/items/{item_id}"),
            ("delete", "/{todo_id}/checklist/items/{item_id}"),
            ("put", "/{todo_id}/checklist/order"),
        ],
    )
    def test_if_match_is_required_and_preconditions_are_documented(self, spec, method, path):
        """新しい更新系は If-Match が必須ヘッダーで、403 / 404 / 412 / 428 / 400 を application/problem+json で文書化している。"""
        operation = self.operation(spec, method, path)
        headers = [p for p in operation["parameters"] if p["in"] == "header" and p["name"].lower() == "if-match"]
        check.equal([p["required"] for p in headers], [True])
        check.is_true({"400", "403", "404", "412", "428"} <= set(operation["responses"]), sorted(operation["responses"]))
        for status in ("403", "404", "412", "428"):
            check.equal(set(operation["responses"][status]["content"]), {"application/problem+json"}, status)

    @pytest.mark.parametrize(
        ("method", "path"),
        [("post", "/{todo_id}/comments"), ("get", "/{todo_id}/comments"), ("get", "/{todo_id}/checklist"), ("post", "/{todo_id}/checklist/items")],
    )
    def test_creates_and_reads_do_not_require_if_match(self, spec, method, path):
        """コメントの投稿・一覧、チェックリストの取得・項目の追加は If-Match を要求しない。"""
        operation = self.operation(spec, method, path)
        check.equal([p for p in operation.get("parameters", []) if p["name"].lower() == "if-match"], [])

    def test_success_statuses_and_etag_headers(self, spec):
        """成功応答: コメントの投稿 201(Location・ETag)、編集 200(ETag)、削除 204(本文なし)、チェックリストの取得・追加・更新・削除・並べ替えは ETag つき(追加は 201、削除は 200)。"""
        cases = [
            ("post", "/{todo_id}/comments", "201", {"ETag", "Location"}),
            ("patch", "/{todo_id}/comments/{comment_id}", "200", {"ETag"}),
            ("get", "/{todo_id}/checklist", "200", {"ETag"}),
            ("post", "/{todo_id}/checklist/items", "201", {"ETag"}),
            ("patch", "/{todo_id}/checklist/items/{item_id}", "200", {"ETag"}),
            ("delete", "/{todo_id}/checklist/items/{item_id}", "200", {"ETag"}),
            ("put", "/{todo_id}/checklist/order", "200", {"ETag"}),
        ]
        for method, path, status, names in cases:
            responses = self.operation(spec, method, path)["responses"]
            check.is_in(status, responses, f"{method} {path}")
            check.is_true(names <= set(responses[status].get("headers", {})), f"{method} {path}: {sorted(responses[status].get('headers', {}))}")
        delete = self.operation(spec, "delete", "/{todo_id}/comments/{comment_id}")["responses"]
        check.is_in("204", delete)
        check.is_not_in("content", delete["204"])

    def test_validation_and_forbidden_documented_for_writes(self, spec):
        """項目の追加は 403 / 404 / 422、コメントの投稿は 404 / 422 を文書化している。"""
        check.is_true({"403", "404", "422"} <= set(self.operation(spec, "post", "/{todo_id}/checklist/items")["responses"]))
        check.is_true({"404", "422"} <= set(self.operation(spec, "post", "/{todo_id}/comments")["responses"]))

    def test_summary_parameters_and_ordering(self, spec):
        """要約の due_soon_days は 1〜30(OpenAPI に minimum / maximum)、today は date。/summary は /{todo_id} より前に宣言されている(ルート定義の順)。"""
        operation = self.operation(spec, "get", "/summary")
        parameters = {p["name"]: p for p in operation["parameters"]}
        days = parameters["due_soon_days"]["schema"]
        check.equal((days["minimum"], days["maximum"], days["default"]), (1, 30, 7))
        today_types = {s.get("format") for s in parameters["today"]["schema"].get("anyOf", [parameters["today"]["schema"]])}
        check.is_in("date", today_types)
        paths = [route.path for route in app.routes if route.path.startswith("/api/v1/todos") and "GET" in getattr(route, "methods", set())]
        check.less(paths.index("/api/v1/todos/summary"), paths.index("/api/v1/todos/{todo_id}"))

    def test_include_total_is_documented_on_list(self, spec):
        """一覧に include_total が(真偽値・既定 false で)ある。"""
        parameters = {p["name"]: p for p in self.operation(spec, "get", "")["parameters"]}
        check.is_in("include_total", parameters)
        check.equal(parameters["include_total"]["schema"].get("default"), False)

    def test_openapi_is_stable_across_calls(self):
        """openapi() を繰り返し呼んでもパスの数が変わらない。"""
        counts = {len(app.openapi()["paths"]) for _ in range(3)}
        check.equal(len(counts), 1)
