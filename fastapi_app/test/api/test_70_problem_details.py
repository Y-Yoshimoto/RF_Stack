# -*- coding: utf-8 -*-
"""エラー応答の形式(RFC 9457 Problem Details。modules/errors)、リクエスト ID、OpenAPI の契約のテスト。"""
import logging
import re
import uuid

import pytest
import pytest_check as check
from sqlalchemy.exc import OperationalError

from app import app
from control_plane_app.api_tenants import router as tenants_router
from control_plane_app.models.sql_models import TENANT_CODE_PATTERN
from modules.auth import session

from .conftest import with_csrf
from .fake_redis import DownRedis

TENANTS = "/api/v1/cp/tenants"
JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
STANDARD_MEMBERS = {"type", "title", "status", "detail", "instance", "code", "request_id", "errors"}
INTERNAL_TOKENS = ("Traceback", "File \"", "sqlalchemy", "psycopg2", "SELECT ", "postgresql://", "SECRET-INTERNAL", "RuntimeError", "keycloak_c")


def assert_problem(response, *, status: int, code: str | None = None) -> dict:
    """Problem Details の共通の形式を検証し、本文を返す。"""
    check.equal(response.status_code, status)
    check.is_true(response.headers["content-type"].startswith("application/problem+json"), response.headers["content-type"])
    body = response.json()
    check.is_true(STANDARD_MEMBERS <= set(body), f"標準メンバーが足りない: {STANDARD_MEMBERS - set(body)}")
    check.equal(body["status"], status)
    check.equal(body["type"], "https://errors.rf-stack.example/" + body["code"].replace("_", "-"))
    check.is_true(re.fullmatch(r"[a-z][a-z0-9_]*", body["code"]) is not None, "code は snake_case")
    check.equal(body["instance"], response.request.url.path)
    check.equal(body["request_id"], response.headers["X-Request-ID"])
    check.is_true(isinstance(body["errors"], list))
    check.is_true(JAPANESE.search(body["title"]) is not None and JAPANESE.search(body["detail"]) is not None, "title / detail は日本語")
    for item in body["errors"]:
        check.equal(set(item), {"field", "code", "message"})
    for token in INTERNAL_TOKENS:
        check.is_not_in(token, response.text)
    if code is not None:
        check.equal(body["code"], code)
    return body


class TestProblemShape:
    """全エラー種別で同じ形式。"""

    def test_401(self, client):
        """未認証 401。HTTPException の英語の detail をそのまま返さない。"""
        body = assert_problem(client.get("/api/v1/me"), status=401, code="unauthenticated")
        check.is_not_in("Not authenticated", str(body))

    def test_401_invalid_cookie(self, client):
        """無効な Cookie も 401 で、理由(署名不正か期限切れか)の英語メッセージを返さない。"""
        response = client.get("/api/v1/me", headers={"Cookie": "rf_sid_app=garbage"})
        body = assert_problem(response, status=401, code="unauthenticated")
        check.is_not_in("Invalid session", str(body))

    def test_403_forbidden(self, client, viewer):
        """権限不足 403。"""
        assert_problem(client.post(f"{TENANTS}/{uuid.uuid4()}/suspend", headers=with_csrf(viewer)), status=403, code="forbidden")

    def test_403_csrf(self, client, admin):
        """CSRF 403 は専用のコード。どちらの検査で落ちたかを示さない。"""
        body = assert_problem(client.post(TENANTS, json={}, headers=admin), status=403, code="csrf_validation_failed")
        check.is_not_in("X-Requested-With", str(body))
        check.is_not_in("Origin", str(body))

    def test_404_unknown_path(self, client):
        """存在しないパスの 404 も Problem Details。"""
        assert_problem(client.get("/api/v1/does-not-exist"), status=404, code="not_found")
        assert_problem(client.get("/nope"), status=404, code="not_found")

    def test_404_resource(self, client, viewer):
        """リソースの 404(tenant_not_found)。"""
        assert_problem(client.get(f"{TENANTS}/{uuid.uuid4()}", headers=viewer), status=404, code="tenant_not_found")

    def test_405(self, client):
        """メソッド違反 405。Allow ヘッダーを保持する。"""
        response = client.put("/api/v1/public/health/live")
        assert_problem(response, status=405, code="method_not_allowed")
        check.is_in("GET", response.headers.get("allow", ""))

    def test_409_with_extensions(self, client, admin, cp_db):
        """409(状態遷移)は拡張メンバー operation / current_status を持つ。"""
        tenant_id = cp_db.insert_tenant(status="SUSPENDED")
        response = client.post(f"{TENANTS}/{tenant_id}/suspend", headers=with_csrf(admin, **{"If-Match": '"1"'}))
        body = assert_problem(response, status=409, code="invalid_tenant_transition")
        check.equal((body["operation"], body["current_status"]), ("suspend", "SUSPENDED"))

    def test_412_and_428_and_400(self, client, admin, cp_db):
        """If-Match 系の 412 / 428 / 400。"""
        tenant_id = cp_db.insert_tenant(status="ACTIVE", version=3)
        url = f"{TENANTS}/{tenant_id}/suspend"
        assert_problem(client.post(url, headers=with_csrf(admin, **{"If-Match": '"1"'})), status=412, code="tenant_version_conflict")
        assert_problem(client.post(url, headers=with_csrf(admin)), status=428, code="precondition_required")
        assert_problem(client.post(url, headers=with_csrf(admin, **{"If-Match": "oops"})), status=400, code="invalid_if_match")

    def test_422_validation_has_field_errors_without_echoing_input(self, client, admin):
        """422 は errors に項目ごとの詳細(field / code / message)。pydantic の英語メッセージや入力値は返さない。"""
        secret_input = "SECRET-INPUT-" + "z" * 80
        response = client.post(TENANTS, json={"tenant_code": secret_input, "name": 123, "initial_admin": {"email": ["x"]}}, headers=with_csrf(admin))
        body = assert_problem(response, status=422, code="validation_error")
        check.is_in("tenant_code", [e["field"] for e in body["errors"]])
        check.is_true(all(JAPANESE.search(e["message"]) for e in body["errors"]), "message は日本語の固定文言")
        check.is_not_in("SECRET-INPUT", response.text)
        check.is_not_in("Input should", response.text)

    def test_429(self, client, monkeypatch):
        """429 は Retry-After 付きの Problem Details。"""
        monkeypatch.setenv("PUBLIC_TENANT_LOOKUP_RATE_LIMIT", "1")
        client.get("/api/v1/public/tenants/x-y-z")
        response = client.get("/api/v1/public/tenants/x-y-z")
        assert_problem(response, status=429, code="too_many_requests")
        check.is_in("Retry-After", response.headers)

    def test_502_has_tenant_id_and_step(self, client, admin, cp_db, fake_kc):
        """502 は拡張メンバー tenant_id / step を持つ。"""
        from modules.keycloak_admin.errors import KeycloakAdminError

        fake_kc.fail_once("ensure_tenant_realm", KeycloakAdminError("x", 500, "SECRET-INTERNAL"))
        code = cp_db.new_code()
        response = client.post(TENANTS, json={"tenant_code": code, "name": "N", "initial_admin": {"email": "a@example.com"}}, headers=with_csrf(admin))
        cp_db.tenant_by_code(code)
        body = assert_problem(response, status=502, code="tenant_provisioning_failed")
        check.is_true(uuid.UUID(body["tenant_id"]) and body["step"] == "ensure_tenant_realm")

    def test_503_when_session_store_is_down(self, client, monkeypatch):
        """Redis(セッションストア)に接続できなければ 503(service_unavailable)。Retry-After 付きで、接続先の情報を返さない。"""
        cookie = {"Cookie": f"rf_sid_app={session.sign_session_id(session.Plane.APP, 'some-sid')}"}
        monkeypatch.setattr(session, "_redis_client", lambda: DownRedis())
        response = client.get("/api/v1/me", headers=cookie)
        assert_problem(response, status=503, code="service_unavailable")
        check.is_in("Retry-After", response.headers)
        check.is_not_in("redis", response.text.lower())

    def test_503_when_database_is_down(self, client, viewer, monkeypatch):
        """DB の接続エラー(OperationalError)は 503。SQL・接続文字列を返さない。"""

        def boom(*args, **kwargs):
            raise OperationalError("SELECT * FROM t_tenant /* SECRET-INTERNAL */", {}, Exception("connection to postgresql://u:p@db failed"))

        monkeypatch.setattr(tenants_router.repo, "get_tenant", boom)
        assert_problem(client.get(f"{TENANTS}/{uuid.uuid4()}", headers=viewer), status=503, code="service_unavailable")


class TestInternalServerError:
    """想定外の例外は 500。内部情報を返さず、ログにだけ残す。"""

    def break_handler(self, monkeypatch, exception):
        def boom(*args, **kwargs):
            raise exception

        monkeypatch.setattr(tenants_router.repo, "get_tenant", boom)

    def test_500_hides_internal_details(self, client, viewer, monkeypatch, caplog):
        """500 の本文は固定の文言(internal_error)で、例外のメッセージ・型・スタックトレースを含まない。詳細はログにある。"""
        self.break_handler(monkeypatch, RuntimeError("SECRET-INTERNAL password=hunter2 at /work/fastapi_app/src/x.py"))
        with caplog.at_level(logging.ERROR):
            response = client.get(f"{TENANTS}/{uuid.uuid4()}", headers=viewer)
        body = assert_problem(response, status=500, code="internal_error")
        for leaked in ("hunter2", "/work/fastapi_app", "x.py"):
            check.is_not_in(leaked, response.text)
        check.equal(set(body), STANDARD_MEMBERS, "拡張メンバーも付けない")
        check.is_in("SECRET-INTERNAL", caplog.text)
        check.is_in("Traceback", caplog.text)

    def test_500_has_request_id_header_matching_the_body(self, client, viewer, monkeypatch):
        """500 でも X-Request-ID ヘッダーが付き、本文の request_id と同じ。送ったリクエスト ID も使われる。"""
        self.break_handler(monkeypatch, ValueError("x"))
        response = client.get(f"{TENANTS}/{uuid.uuid4()}", headers={**viewer, "X-Request-ID": "trace-500-abc"})
        check.equal((response.headers["X-Request-ID"], response.json()["request_id"]), ("trace-500-abc", "trace-500-abc"))

    def test_500_in_a_mutation_does_not_leak_either(self, client, admin, monkeypatch, cp_db):
        """変更系の途中で想定外の例外が起きても、500 の固定文言で、一時パスワードや内部の値を含まない。"""
        from control_plane_app.services import tenant_provisioning

        def boom(*args, **kwargs):
            raise RuntimeError("SECRET-INTERNAL")

        monkeypatch.setattr(tenant_provisioning.TenantProvisioningService, "onboard", boom)
        response = client.post(TENANTS, json={"tenant_code": cp_db.new_code(), "name": "N", "initial_admin": {"email": "a@example.com"}}, headers=with_csrf(admin))
        assert_problem(response, status=500, code="internal_error")

    def test_unexpected_error_in_dependency_is_500(self, client, monkeypatch):
        """認証の依存関数の中の想定外の例外(Redis の応答が壊れている等)も 500 の Problem Details。"""
        class Broken:
            def get(self, key):
                return "{not json"

        monkeypatch.setattr(session, "_redis_client", lambda: Broken())
        cookie = {"Cookie": f"rf_sid_app={session.sign_session_id(session.Plane.APP, 'sid')}"}
        assert_problem(client.get("/api/v1/me", headers=cookie), status=500, code="internal_error")


class TestRequestId:
    """X-Request-ID。"""

    def test_generated_when_absent(self, client):
        """無ければ UUIDv7 を生成して応答ヘッダーに付ける。リクエストごとに異なる。成功応答にも付く。"""
        first, second = client.get("/api/v1/public/health/live"), client.get("/api/v1/public/health/live")
        ids = [first.headers["X-Request-ID"], second.headers["X-Request-ID"]]
        check.not_equal(ids[0], ids[1])
        check.equal([uuid.UUID(i).version for i in ids], [7, 7])

    def test_valid_incoming_id_is_echoed(self, client, viewer):
        """形式が正しい X-Request-ID はそのまま使い、応答ヘッダーと Problem Details の両方に入る。"""
        response = client.get(f"{TENANTS}/{uuid.uuid4()}", headers={**viewer, "X-Request-ID": "Client.Req_ID-123"})
        check.equal((response.headers["X-Request-ID"], response.json()["request_id"]), ("Client.Req_ID-123",) * 2)

    @pytest.mark.parametrize("incoming", ["has space", "semi;colon", "x" * 129, "a/b", "<script>", ""])
    def test_invalid_incoming_id_is_replaced(self, client, incoming):
        """形式が不正(空白・記号・129 文字以上・空)な X-Request-ID は採用せず、新しく生成する(ログ・ヘッダーの汚染防止)。"""
        response = client.get("/api/v1/public/health/live", headers={"X-Request-ID": incoming})
        issued = response.headers["X-Request-ID"]
        check.not_equal(issued, incoming)
        check.equal(uuid.UUID(issued).version, 7)

    def test_boundary_length(self, client):
        """128 文字までは採用される。"""
        value = "a" * 128
        check.equal(client.get("/api/v1/public/health/live", headers={"X-Request-ID": value}).headers["X-Request-ID"], value)

    def test_present_on_all_kinds_of_responses(self, client, viewer):
        """200・401・404・405・422 のすべてに X-Request-ID が付く。"""
        responses = [
            client.get("/api/v1/public/health/live"),
            client.get("/api/v1/me"),
            client.get("/nope"),
            client.put("/api/v1/public/health/live"),
            client.get(f"{TENANTS}/not-a-uuid", headers=viewer),
        ]
        check.equal([r.status_code for r in responses], [200, 401, 404, 405, 422])
        check.is_true(all("X-Request-ID" in r.headers for r in responses))


class TestOpenApiContract:
    """OpenAPI(/openapi.json)が契約の正。エンドポイントの一覧とエラー応答の形式。"""

    EXPECTED = {
        ("get", "/api/v1/me"),
        ("get", "/api/v1/users"),
        ("post", "/api/v1/users"),
        ("get", "/api/v1/users/{user_id}"),
        ("patch", "/api/v1/users/{user_id}"),
        ("get", "/api/v1/organizations"),
        ("post", "/api/v1/organizations"),
        ("get", "/api/v1/organizations/{organization_id}"),
        ("patch", "/api/v1/organizations/{organization_id}"),
        ("delete", "/api/v1/organizations/{organization_id}"),
        ("put", "/api/v1/organizations/{organization_id}/members"),
        ("get", "/api/v1/todos"),
        ("post", "/api/v1/todos"),
        ("get", "/api/v1/todos/{todo_id}"),
        ("patch", "/api/v1/todos/{todo_id}"),
        ("delete", "/api/v1/todos/{todo_id}"),
        ("put", "/api/v1/todos/{todo_id}/assignees"),
        ("get", "/api/v1/todos/{todo_id}/activities"),
        ("get", "/api/v1/todos/summary"),
        ("get", "/api/v1/todos/{todo_id}/comments"),
        ("post", "/api/v1/todos/{todo_id}/comments"),
        ("patch", "/api/v1/todos/{todo_id}/comments/{comment_id}"),
        ("delete", "/api/v1/todos/{todo_id}/comments/{comment_id}"),
        ("get", "/api/v1/todos/{todo_id}/checklist"),
        ("post", "/api/v1/todos/{todo_id}/checklist/items"),
        ("patch", "/api/v1/todos/{todo_id}/checklist/items/{item_id}"),
        ("delete", "/api/v1/todos/{todo_id}/checklist/items/{item_id}"),
        ("put", "/api/v1/todos/{todo_id}/checklist/order"),
        ("get", "/api/v1/cp/tenants"),
        ("post", "/api/v1/cp/tenants"),
        ("get", "/api/v1/cp/tenants/{tenant_id}"),
        ("delete", "/api/v1/cp/tenants/{tenant_id}"),
        ("post", "/api/v1/cp/tenants/{tenant_id}/suspend"),
        ("post", "/api/v1/cp/tenants/{tenant_id}/resume"),
        ("post", "/api/v1/cp/tenants/{tenant_id}/provisioning/retry"),
        ("get", "/api/v1/cp/tenants/{tenant_id}/metrics"),
        ("get", "/api/v1/cp/metrics/summary"),
        ("get", "/api/v1/public/health/live"),
        ("get", "/api/v1/public/health/ready"),
        ("get", "/api/v1/public/tenants/{tenant_code}"),
    }

    @pytest.fixture(scope="class")
    def spec(self):
        return app.openapi()

    def test_documented_endpoints_exist(self, spec):
        """02 §5.6 のエンドポイントがすべて OpenAPI にある。"""
        operations = {(method, path) for path, item in spec["paths"].items() for method in item if path.startswith("/api/v1")}
        check.equal(self.EXPECTED - operations, set())
        check.equal(operations - self.EXPECTED, set(), "文書に無いエンドポイントが /api/v1 にある")

    def test_sample_routes_are_not_registered(self, spec):
        """参考用のサンプル(/RestSample・/sample・/api/demo)はアプリに登録されず、OpenAPI にも実ルートにも無い。"""
        check.equal([path for path in spec["paths"] if not path.startswith(("/api/v1", "/api/auth"))], [])
        registered = {route.path for route in app.routes}
        check.equal({path for path in registered if path.startswith(("/RestSample", "/sample", "/api/demo"))}, set())

    def test_tenant_code_schema_matches_implementation(self, spec):
        """TenantCreate.tenant_code の OpenAPI は、実装(01 §5.1。3〜32 文字の英小文字・数字・ハイフン)と同じ制約を示す。検証(422)は変えない。"""
        prop = spec["components"]["schemas"]["TenantCreate"]["properties"]["tenant_code"]
        check.equal((prop["minLength"], prop["maxLength"]), (3, 32))
        check.equal(prop["pattern"], TENANT_CODE_PATTERN)
        pattern = re.compile(prop["pattern"])
        check.is_true(all(pattern.fullmatch(code) for code in ("abc", "a-b", "a" * 32)))
        check.is_true(not any(pattern.fullmatch(code) for code in ("ab", "a" * 33, "-ab", "ab-", "a--b", "Abc")))

    def test_if_match_operations_document_400(self, spec):
        """If-Match を受け取る全操作(CP・AP)は、形式不正の 400 を application/problem+json の ProblemDetails で載せる。"""
        found = []
        for path, item in spec["paths"].items():
            for method, operation in item.items():
                if any(p["in"] == "header" and p["name"] == "If-Match" for p in operation.get("parameters", [])):
                    found.append((method, path))
                    content = operation["responses"].get("400", {}).get("content", {})
                    check.equal(set(content), {"application/problem+json"}, f"{method} {path}")
                    check.is_in("ProblemDetails", str(content), f"{method} {path}")
        check.equal(len(found), 16)
        check.is_true(any(path.startswith("/api/v1/cp/") for _, path in found) and any(not path.startswith("/api/v1/cp/") for _, path in found))

    def test_error_responses_are_problem_json(self, spec):
        """/api/v1 のエラー応答(4xx / 5xx)は、application/problem+json だけで ProblemDetails を参照する(ready の 503 を除く)。"""
        problems = []
        for path, item in spec["paths"].items():
            if not path.startswith("/api/v1"):
                continue
            for method, operation in item.items():
                for status, response in operation["responses"].items():
                    if int(status) < 400 or (path.endswith("/health/ready") and status == "503"):
                        continue
                    content = response.get("content", {})
                    if set(content) != {"application/problem+json"} or "ProblemDetails" not in str(content):
                        problems.append((method, path, status, list(content)))
        check.equal(problems, [])

    def test_mutations_document_precondition_responses(self, spec):
        """停止・再開・削除要求は 412 と 428 を、作成は 409 / 502 を文書化している。"""
        suspend = spec["paths"]["/api/v1/cp/tenants/{tenant_id}/suspend"]["post"]["responses"]
        check.is_true({"200", "401", "403", "404", "409", "412", "428", "502"} <= set(suspend))
        create = spec["paths"]["/api/v1/cp/tenants"]["post"]["responses"]
        check.is_true({"201", "409", "422", "502"} <= set(create))

    def test_auth_documents_status_and_logout_only(self, spec):
        """BFF(/api/auth)は status / logout だけを載せる。login / callback / dev-login はリダイレクトのため載せない。"""
        operations = {(method, path) for path, item in spec["paths"].items() for method in item if path.startswith("/api/auth")}
        check.equal(operations, {("get", "/api/auth/app/status"), ("get", "/api/auth/cp/status"), ("post", "/api/auth/app/logout"), ("post", "/api/auth/cp/logout")})
        check.is_true(all(spec["paths"][path][method]["tags"] == ["auth"] for method, path in operations))

    def test_auth_error_responses_are_problem_json(self, spec):
        """/api/auth の status は 401、logout は 403 を Problem Details で記述する。"""
        for path, method, status in (
            ("/api/auth/app/status", "get", "401"),
            ("/api/auth/cp/status", "get", "401"),
            ("/api/auth/app/logout", "post", "403"),
            ("/api/auth/cp/logout", "post", "403"),
        ):
            content = spec["paths"][path][method]["responses"][status]["content"]
            check.equal(set(content), {"application/problem+json"}, path)

    def test_session_cookies_are_security_schemes(self, spec):
        """セッション Cookie は cookie パラメータではなく、セキュリティスキーム(AppSession / CpSession)で表す。"""
        cookie_params = [(path, p["name"]) for path, item in spec["paths"].items() for op in item.values() for p in op.get("parameters", []) if p["in"] == "cookie"]
        check.equal(cookie_params, [])
        check.equal(spec["paths"]["/api/v1/me"]["get"]["security"], [{"AppSession": []}])
        check.equal(spec["paths"]["/api/v1/cp/tenants"]["get"]["security"], [{"CpSession": []}])
        check.is_not_in("security", spec["paths"]["/api/v1/public/health/live"]["get"])

    def test_csrf_header_only_on_mutations(self, spec):
        """X-Requested-With は変更系(POST / PUT / PATCH / DELETE)だけに必須で載り、参照系には載らない。"""
        missing, unexpected = [], []
        for path, item in spec["paths"].items():
            if not path.startswith("/api/") or path.startswith("/api/v1/public"):
                continue
            for method, operation in item.items():
                names = [p["name"] for p in operation.get("parameters", []) if p["in"] == "header" and p.get("required")]
                if method in {"post", "put", "patch", "delete"} and "X-Requested-With" not in names:
                    missing.append((method, path))
                if method == "get" and any(p["name"] == "X-Requested-With" for p in operation.get("parameters", [])):
                    unexpected.append((method, path))
        check.equal(missing, [])
        check.equal(unexpected, [])

    def test_if_match_is_required_header_on_every_update(self, spec):
        """更新系の If-Match は OpenAPI で必須のヘッダー(払い出しの再実行だけ任意)。openapi() を繰り返し呼んでも変わらない。"""
        optional = {("post", "/api/v1/cp/tenants/{tenant_id}/provisioning/retry")}
        for _ in range(3):
            current = app.openapi()
            found = {}
            for path, item in current["paths"].items():
                for method, operation in item.items():
                    for parameter in operation.get("parameters", []):
                        if parameter["in"] == "header" and parameter["name"].lower() == "if-match":
                            found[(method, path)] = parameter["required"]
            check.equal({key for key, required in found.items() if not required}, optional)
            check.equal(len(found), 16)

    def test_etag_headers_are_documented_on_success_responses(self, spec):
        """ETag を返す成功レスポンスは、CP / AP とも responses.headers に ETag を載せている(作成系は Location も)。"""
        cp = "/api/v1/cp/tenants"
        cases = [
            ("get", f"{cp}/{{tenant_id}}", "200", {"ETag"}),
            ("post", cp, "201", {"ETag", "Location", "Cache-Control"}),
            ("post", f"{cp}/{{tenant_id}}/suspend", "200", {"ETag"}),
            ("post", f"{cp}/{{tenant_id}}/resume", "200", {"ETag"}),
            ("delete", f"{cp}/{{tenant_id}}", "200", {"ETag"}),
            ("post", f"{cp}/{{tenant_id}}/provisioning/retry", "200", {"ETag", "Cache-Control"}),
            ("get", "/api/v1/todos/{todo_id}", "200", {"ETag"}),
            ("patch", "/api/v1/todos/{todo_id}", "200", {"ETag"}),
        ]
        for method, path, status, names in cases:
            headers = spec["paths"][path][method]["responses"][status].get("headers", {})
            check.is_true(names <= set(headers), f"{method} {path}: {sorted(headers)}")
