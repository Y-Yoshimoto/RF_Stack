# -*- coding: utf-8 -*-
"""払い出し API(POST /api/v1/cp/tenants、POST .../provisioning/retry)のテスト。Keycloak はフェイク。"""
import logging
import uuid

import pytest
import pytest_check as check

from modules.keycloak_admin.errors import KeycloakAdminError

from .conftest import SENTINEL_PASSWORD, with_csrf

TENANTS = "/api/v1/cp/tenants"
SECRET_DETAIL = "errorMessage=KC-INTERNAL-DETAIL-12345"


def body_for(code: str, **overrides):
    body = {"tenant_code": code, "name": "Provisioning Test", "initial_admin": {"email": "Owner@Example.com"}}
    body.update(overrides)
    return body


class TestCreate:
    """正常系。"""

    def test_created_response(self, client, admin, cp_db):
        """201。Location は詳細の URL、ETag はバージョン、Cache-Control は no-store。本文にテナントと初期管理者の一時パスワード。"""
        code = cp_db.new_code()
        response = client.post(TENANTS, json=body_for(code), headers=with_csrf(admin))
        check.equal(response.status_code, 201, response.text)
        body = response.json()
        tenant = body["tenant"]
        cp_db.tenant_by_code(code)
        check.equal(response.headers["Location"], f"/api/v1/cp/tenants/{tenant['id']}")
        check.equal(response.headers["ETag"], f'"{tenant["version"]}"')
        check.equal(response.headers["Cache-Control"], "no-store")
        check.equal((tenant["tenant_code"], tenant["status"], tenant["version"], tenant["name"]), (code, "ACTIVE", 2, "Provisioning Test"))
        check.equal(body["initial_admin"], {"username": "owner@example.com", "temporary_password": SENTINEL_PASSWORD})
        check.is_in("application/json", response.headers["content-type"])
        check.equal(set(body), {"tenant", "initial_admin", "provisioning_history_id"})
        for forbidden in ("realm_name", "created_by", "updated_by", "tier"):
            check.is_not_in(forbidden, response.text)

    def test_location_is_usable(self, client, admin, viewer, cp_db):
        """Location の URL で詳細を取得でき、同じテナントが返る。詳細に一時パスワードは含まれない。"""
        code = cp_db.new_code()
        created = client.post(TENANTS, json=body_for(code), headers=with_csrf(admin))
        cp_db.tenant_by_code(code)
        detail = client.get(created.headers["Location"], headers=viewer)
        check.equal(detail.status_code, 200)
        check.equal(detail.json()["id"], created.json()["tenant"]["id"])
        check.is_not_in(SENTINEL_PASSWORD, detail.text)

    def test_keycloak_receives_the_requested_values(self, client, admin, cp_db, fake_kc):
        """Keycloak には、リクエストのテナントコード・名前・初期管理者(姓名は既定値、ロールは tenant_admin)を渡す。"""
        code = cp_db.new_code()
        payload = body_for(code, initial_admin={"email": "boss@example.com", "first_name": "Taro", "last_name": "Yamada", "username": "boss"})
        response = client.post(TENANTS, json=payload, headers=with_csrf(admin))
        cp_db.tenant_by_code(code)
        check.equal(response.status_code, 201)
        realm_call = fake_kc.calls_of("ensure_tenant_realm")[0]
        check.equal((realm_call["tenant_code"], realm_call["display_name"], str(realm_call["tenant_id"])), (code, "Provisioning Test", response.json()["tenant"]["id"]))
        user_call = fake_kc.calls_of("ensure_tenant_user")[0]
        check.equal((user_call["username"], user_call["email"], user_call["first_name"], user_call["last_name"], user_call["roles"]), ("boss", "boss@example.com", "Taro", "Yamada", ["tenant_admin"]))

    def test_temporary_password_is_not_logged_or_stored(self, client, admin, cp_db, caplog):
        """一時パスワードは、ログ(全レベル)・台帳・履歴・監査ログのどこにも出ない。レスポンスにだけ出る。"""
        code = cp_db.new_code()
        with caplog.at_level(logging.DEBUG):
            response = client.post(TENANTS, json=body_for(code), headers=with_csrf(admin))
        row = cp_db.tenant_by_code(code)
        check.is_in(SENTINEL_PASSWORD, response.text)
        check.is_not_in(SENTINEL_PASSWORD, caplog.text)
        check.is_not_in(SENTINEL_PASSWORD, cp_db.dump_text(row["id"]))

    def test_request_id_flows_to_audit_log(self, client, admin, cp_db):
        """X-Request-ID が監査ログに残り、レスポンスヘッダーにも返る。"""
        code = cp_db.new_code()
        response = client.post(TENANTS, json=body_for(code), headers=with_csrf(admin, **{"X-Request-ID": "create-req-777"}))
        row = cp_db.tenant_by_code(code)
        check.equal(response.headers["X-Request-ID"], "create-req-777")
        check.is_true(all(a["request_id"] == "create-req-777" for a in cp_db.audits(row["id"])))

    def test_real_dependency_creates_and_closes_admin_client_per_request(self, client, admin, cp_db, monkeypatch):
        """差し替えない実際の依存関数は、リクエストごとに管理クライアントを作り、終了時に閉じる(締め切り 30 秒を 1 テナントごとに数える)。"""
        from app import app
        from control_plane_app.api_tenants import deps

        from .conftest import FakeAdmin

        app.dependency_overrides.pop(deps.get_provisioning_service)
        admins = []

        def factory():
            admins.append(FakeAdmin())
            return admins[-1]

        monkeypatch.setattr(deps, "create_provisioner_admin_client", factory)
        for _ in range(2):
            code = cp_db.new_code()
            response = client.post(TENANTS, json=body_for(code), headers=with_csrf(admin))
            cp_db.tenant_by_code(code)
            check.equal(response.status_code, 201, response.text)
            check.equal(len(response.json()["initial_admin"]["temporary_password"]), 20, "既定の生成関数")
        check.equal(len(admins), 2)
        check.is_true(all(a.closed for a in admins))


class TestCreateErrors:
    """入力不正・重複・失敗。"""

    def test_duplicate_code_is_409(self, client, admin, cp_db):
        """同じテナントコードの 2 回目は 409(tenant_code_already_exists)。既存テナントは変わらない。"""
        code = cp_db.new_code()
        first = client.post(TENANTS, json=body_for(code), headers=with_csrf(admin))
        cp_db.tenant_by_code(code)
        second = client.post(TENANTS, json=body_for(code, name="Other"), headers=with_csrf(admin))
        body = second.json()
        check.equal((second.status_code, body["code"]), (409, "tenant_code_already_exists"))
        check.equal(body["errors"][0]["field"], "tenant_code")
        check.equal(cp_db.tenant(uuid.UUID(first.json()["tenant"]["id"]))["name"], "Provisioning Test")

    def test_existing_seed_tenant_code_is_409_without_side_effects(self, client, admin, seeded, cp_db):
        """シードの alpha と同じコードは 409。alpha は変更されない(読み取りのみ)。"""
        before = seeded("alpha")
        response = client.post(TENANTS, json=body_for("alpha"), headers=with_csrf(admin))
        check.equal((response.status_code, response.json()["code"]), (409, "tenant_code_already_exists"))
        check.equal(seeded("alpha"), before)

    @pytest.mark.parametrize(
        ("code", "reason"),
        [("ab", "format"), ("Abc-Def", "format"), ("a--b", "format"), ("-abc", "format"), ("abc\n", "format"), ("a" * 33, "format"), ("admin", "reserved"), ("dev-login", "reserved"), ("keycloak", "reserved")],
    )
    def test_invalid_tenant_code_is_422(self, client, admin, cp_db, fake_kc, code, reason):
        """形式違反・予約語は 422(invalid_tenant_code)。errors に tenant_code と理由。何も作成せず Keycloak も呼ばない。"""
        response = client.post(TENANTS, json=body_for(code), headers=with_csrf(admin))
        body = response.json()
        check.equal((response.status_code, body["code"]), (422, "invalid_tenant_code"))
        check.equal((body["errors"][0]["field"], body["errors"][0]["code"]), ("tenant_code", reason))
        check.equal(fake_kc.calls, [])
        check.is_none(cp_db.tenant_by_code(code))

    @pytest.mark.parametrize(
        ("payload", "field"),
        [
            ({}, "tenant_code"),
            ({"tenant_code": "zt-valid-code", "initial_admin": {"email": "a@example.com"}}, "name"),
            ({"tenant_code": "zt-valid-code", "name": "N"}, "initial_admin"),
            ({"tenant_code": "zt-valid-code", "name": "N", "initial_admin": {}}, "initial_admin.email"),
            ({"tenant_code": "zt-valid-code", "name": "", "initial_admin": {"email": "a@example.com"}}, "name"),
            ({"tenant_code": "zt-valid-code", "name": "x" * 101, "initial_admin": {"email": "a@example.com"}}, "name"),
            ({"tenant_code": "x" * 65, "name": "N", "initial_admin": {"email": "a@example.com"}}, "tenant_code"),
            ({"tenant_code": 123, "name": "N", "initial_admin": {"email": "a@example.com"}}, "tenant_code"),
            ({"tenant_code": "zt-valid-code", "name": "N", "initial_admin": {"email": "ab"}}, "initial_admin.email"),
        ],
    )
    def test_invalid_body_is_422_validation_error(self, client, admin, fake_kc, payload, field):
        """本文の不備(必須の欠落・長さ・型)は 422(validation_error)。errors に項目名が入り、入力値はエコーしない。"""
        response = client.post(TENANTS, json=payload, headers=with_csrf(admin))
        body = response.json()
        check.equal((response.status_code, body["code"]), (422, "validation_error"))
        check.is_in(field, [e["field"] for e in body["errors"]])
        check.is_not_in("x" * 65, response.text)
        check.equal(fake_kc.calls, [])

    @pytest.mark.parametrize("email", ["no-at-sign", "@example.com", "a@", "a b@example.com", "a@b@c"])
    def test_invalid_email_is_422(self, client, admin, cp_db, fake_kc, email):
        """メールアドレスの形式が不正なら 422(invalid_tenant_input)で、何も作成しない。"""
        code = cp_db.new_code()
        response = client.post(TENANTS, json=body_for(code, initial_admin={"email": email}), headers=with_csrf(admin))
        body = response.json()
        check.equal(response.status_code, 422)
        check.is_in(body["code"], ("invalid_tenant_input", "validation_error"))
        check.is_none(cp_db.tenant_by_code(code))

    def test_not_json_is_422(self, client, admin):
        """JSON でない本文は 422。"""
        response = client.post(TENANTS, content="not json", headers=with_csrf(admin, **{"Content-Type": "application/json"}))
        check.equal((response.status_code, response.json()["code"]), (422, "validation_error"))

    @pytest.mark.parametrize(("function", "step"), [("ensure_tenant_realm", "ensure_tenant_realm"), ("ensure_tenant_user", "ensure_initial_admin")])
    def test_provisioning_failure_is_502_with_tenant_id_and_step(self, client, admin, cp_db, fake_kc, caplog, function, step):
        """払い出しの途中で失敗したら 502(tenant_provisioning_failed)。tenant_id と step を返し、台帳は FAILED。詳細・一時パスワードは本文にもログにも出ない。"""
        code = cp_db.new_code()
        fake_kc.fail_once(function, KeycloakAdminError("create thing for owner@example.com", 500, SECRET_DETAIL))
        with caplog.at_level(logging.DEBUG):
            response = client.post(TENANTS, json=body_for(code), headers=with_csrf(admin))
        row = cp_db.tenant_by_code(code)
        body = response.json()
        check.equal((response.status_code, body["code"], body["step"], body["tenant_id"]), (502, "tenant_provisioning_failed", step, str(row["id"])))
        check.is_in("application/problem+json", response.headers["content-type"])
        check.equal(row["status"], "FAILED")
        for leaked in ("KC-INTERNAL-DETAIL", "owner@example.com", SENTINEL_PASSWORD):
            check.is_not_in(leaked, response.text)
        check.is_not_in(SENTINEL_PASSWORD, caplog.text)
        check.is_not_in(SENTINEL_PASSWORD, cp_db.dump_text(row["id"]))


class TestRetry:
    """払い出しの再実行。"""

    def failed_tenant(self, client, admin, cp_db, fake_kc):
        code = cp_db.new_code()
        fake_kc.fail_once("ensure_tenant_realm", KeycloakAdminError("x", 500, SECRET_DETAIL))
        response = client.post(TENANTS, json=body_for(code), headers=with_csrf(admin))
        assert response.status_code == 502
        return response.json()["tenant_id"], code

    def test_retry_with_tenant_id_from_the_error(self, client, admin, viewer, cp_db, fake_kc):
        """502 の本文の tenant_id で再実行でき、ACTIVE になる。新しい一時パスワードは再実行のレスポンスにだけ出て、no-store。"""
        tenant_id, code = self.failed_tenant(client, admin, cp_db, fake_kc)
        response = client.post(f"{TENANTS}/{tenant_id}/provisioning/retry", json={"initial_admin": {"email": "Owner@Example.com"}}, headers=with_csrf(admin))
        check.equal(response.status_code, 200, response.text)
        body = response.json()
        check.equal((body["tenant"]["status"], body["tenant"]["version"], response.headers["ETag"], response.headers["Cache-Control"]), ("ACTIVE", 4, '"4"', "no-store"))
        check.equal(body["initial_admin"], {"username": "owner@example.com", "temporary_password": SENTINEL_PASSWORD})
        detail = client.get(f"{TENANTS}/{tenant_id}", headers=viewer).json()
        check.equal([(h["status"]) for h in detail["provisioning_history"]], ["SUCCEEDED", "FAILED"], "新しい順")
        check.is_not_in(SENTINEL_PASSWORD, str(detail))

    def test_retry_failure_is_502_again(self, client, admin, cp_db, fake_kc):
        """再実行も失敗したら 502(tenant_provisioning_failed)。さらに再実行できる。"""
        tenant_id, _ = self.failed_tenant(client, admin, cp_db, fake_kc)
        fake_kc.fail_once("ensure_tenant_user", KeycloakAdminError("x", 503, SECRET_DETAIL))
        url = f"{TENANTS}/{tenant_id}/provisioning/retry"
        payload = {"initial_admin": {"email": "owner@example.com"}}
        failed = client.post(url, json=payload, headers=with_csrf(admin))
        check.equal((failed.status_code, failed.json()["code"], failed.json()["step"]), (502, "tenant_provisioning_failed", "ensure_initial_admin"))
        check.equal(client.post(url, json=payload, headers=with_csrf(admin)).status_code, 200)

    def test_retry_on_active_tenant_is_409(self, client, admin, cp_db):
        """ACTIVE のテナントの再実行は 409(invalid_tenant_transition)。operation=retry、current_status=ACTIVE。"""
        tenant_id = cp_db.insert_tenant(status="ACTIVE")
        response = client.post(f"{TENANTS}/{tenant_id}/provisioning/retry", json={"initial_admin": {"email": "a@example.com"}}, headers=with_csrf(admin))
        body = response.json()
        check.equal((response.status_code, body["code"], body["operation"], body["current_status"]), (409, "invalid_tenant_transition", "retry", "ACTIVE"))

    def test_retry_unknown_tenant_is_404(self, client, admin):
        """存在しないテナントは 404。"""
        response = client.post(f"{TENANTS}/{uuid.uuid4()}/provisioning/retry", json={"initial_admin": {"email": "a@example.com"}}, headers=with_csrf(admin))
        check.equal((response.status_code, response.json()["code"]), (404, "tenant_not_found"))

    @pytest.mark.parametrize("payload", [{}, {"initial_admin": {}}, {"initial_admin": {"email": "ab"}}])
    def test_retry_requires_initial_admin(self, client, admin, cp_db, payload):
        """初期管理者の指定が無い・不正なら 422(状態は変えない)。"""
        tenant_id = cp_db.insert_tenant(status="FAILED")
        response = client.post(f"{TENANTS}/{tenant_id}/provisioning/retry", json=payload, headers=with_csrf(admin))
        check.equal((response.status_code, response.json()["code"]), (422, "validation_error"))
        check.equal(cp_db.tenant(tenant_id)["status"], "FAILED")
