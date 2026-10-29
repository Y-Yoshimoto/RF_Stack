# -*- coding: utf-8 -*-
"""modules.auth.csrf.require_csrf_protection(カスタムヘッダー + Origin の二重検査)のテスト。"""
import pytest
import pytest_check as check
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from modules.auth import csrf
from modules.auth.csrf import CSRF_REJECTED_DETAIL, install_csrf_openapi, require_csrf_protection
from modules.auth.environment import KeyCloakEnvironmentVariables

ALLOWED_ORIGIN = "http://localhost:5173"
GOOD_HEADER = {"X-Requested-With": "rf-stack"}


@pytest.fixture
def client(config) -> TestClient:
    """全メソッドを受けるルートに require_csrf_protection をルーター単位で適用したアプリのクライアント。"""
    router = APIRouter(dependencies=[Depends(require_csrf_protection)])

    @router.api_route("/x", methods=["GET", "HEAD", "OPTIONS", "TRACE", "POST", "PUT", "PATCH", "DELETE"])
    def endpoint():
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _reload_config(monkeypatch) -> None:
    """環境変数の変更を csrf モジュールの設定に反映する。"""
    monkeypatch.setattr(csrf, "_config", KeyCloakEnvironmentVariables())


class TestSafeMethods:
    """参照系メソッドは検査しない。"""

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "TRACE"])
    def test_safe_methods_pass_without_headers(self, client, method):
        """GET / HEAD / OPTIONS / TRACE はヘッダー・Origin が無くても通る。"""
        check.equal(client.request(method, "/x").status_code, 200)


class TestUnsafeMethods:
    """変更系メソッドは X-Requested-With と許可した Origin の両方が必須。"""

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_no_headers_is_forbidden(self, client, method):
        """ヘッダーも Origin も無い変更系は 403(CSRF validation failed)。"""
        response = client.request(method, "/x")
        check.equal((response.status_code, response.json()), (403, {"detail": CSRF_REJECTED_DETAIL}))

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_allowed_origin_with_header_passes(self, client, method):
        """X-Requested-With: rf-stack と許可オリジンがあれば通る。"""
        response = client.request(method, "/x", headers={**GOOD_HEADER, "Origin": ALLOWED_ORIGIN})
        check.equal(response.status_code, 200)

    def test_missing_custom_header_is_forbidden(self, client):
        """Origin が許可されていても、カスタムヘッダーが無ければ 403。"""
        check.equal(client.post("/x", headers={"Origin": ALLOWED_ORIGIN}).status_code, 403)

    @pytest.mark.parametrize("value", ["", "true", "1", "RF-STACK", "rf-stack ", "XMLHttpRequest", "rf-stack,rf-stack"])
    def test_wrong_custom_header_value_is_forbidden(self, client, value):
        """ヘッダー値が rf-stack と正確に一致しなければ 403。"""
        response = client.post("/x", headers={"X-Requested-With": value, "Origin": ALLOWED_ORIGIN})
        check.equal(response.status_code, 403)

    def test_missing_origin_is_forbidden(self, client):
        """カスタムヘッダーがあっても Origin が無ければ 403(ブラウザは変更系で必ず Origin を送る)。"""
        check.equal(client.post("/x", headers=GOOD_HEADER).status_code, 403)

    def test_empty_origin_is_forbidden(self, client):
        """空の Origin は 403。"""
        check.equal(client.post("/x", headers={**GOOD_HEADER, "Origin": ""}).status_code, 403)

    def test_referer_is_not_a_substitute_for_origin(self, client):
        """Referer が許可オリジンでも、Origin が無ければ 403。"""
        check.equal(client.post("/x", headers={**GOOD_HEADER, "Referer": f"{ALLOWED_ORIGIN}/page"}).status_code, 403)

    @pytest.mark.parametrize(
        "origin",
        [
            "http://evil.example.com",
            "null",
            "https://localhost:5173",  # スキームが違う
            "http://localhost:5174",  # ポートが違う
            "http://localhost",  # ポート無し
            "http://localhost:5173.evil.example.com",  # 前方一致の罠
            "http://evil.example.com/http://localhost:5173",
            "http://localhost:5173@evil.example.com",
            "http://sub.localhost:5173",
        ],
    )
    def test_other_origin_is_forbidden(self, client, origin):
        """許可リストに無いオリジン(別ホスト・別スキーム・別ポート・前方一致の罠)は 403。"""
        check.equal(client.post("/x", headers={**GOOD_HEADER, "Origin": origin}).status_code, 403)

    @pytest.mark.parametrize("origin", ["http://localhost:5173/", "HTTP://LOCALHOST:5173", "Http://LocalHost:5173/"])
    def test_origin_is_normalized(self, client, origin):
        """末尾スラッシュ・大文字小文字は正規化して照合する。"""
        check.equal(client.post("/x", headers={**GOOD_HEADER, "Origin": origin}).status_code, 200)

    def test_rejection_reasons_are_not_distinguishable(self, client):
        """ヘッダー不足と Origin 不正で、レスポンスの内容を変えない(どちらの検査で落ちたか教えない)。"""
        no_header = client.post("/x", headers={"Origin": ALLOWED_ORIGIN})
        bad_origin = client.post("/x", headers={**GOOD_HEADER, "Origin": "http://evil.example.com"})
        check.equal((no_header.status_code, no_header.json()), (bad_origin.status_code, bad_origin.json()))


class TestTrustedOrigins:
    """FRONTEND_URL と CSRF_TRUSTED_ORIGINS。"""

    def test_trusted_origins_env_adds_origins(self, client, monkeypatch):
        """CSRF_TRUSTED_ORIGINS(カンマ区切り)のオリジンも許可される。FRONTEND_URL は引き続き許可。"""
        monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "http://localhost:4173, https://preview.example.com/ ,,")
        _reload_config(monkeypatch)
        for origin in ("http://localhost:4173", "https://preview.example.com", ALLOWED_ORIGIN):
            check.equal(client.post("/x", headers={**GOOD_HEADER, "Origin": origin}).status_code, 200, origin)
        check.equal(client.post("/x", headers={**GOOD_HEADER, "Origin": "http://localhost:9999"}).status_code, 403)

    def test_origin_without_scheme_in_env_is_ignored(self, client, monkeypatch):
        """スキームの無い設定値(例: example.com)は許可リストに入らない。"""
        monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "example.com, //example.org")
        _reload_config(monkeypatch)
        config = csrf._config
        check.equal(config.trusted_origins(), frozenset({ALLOWED_ORIGIN}))

    def test_frontend_url_with_path_is_reduced_to_origin(self, client, monkeypatch):
        """FRONTEND_URL にパスが付いていても、許可されるのはオリジン部分だけ。"""
        monkeypatch.setenv("FRONTEND_URL", "https://app.example.com/some/path/")
        _reload_config(monkeypatch)
        check.equal(client.post("/x", headers={**GOOD_HEADER, "Origin": "https://app.example.com"}).status_code, 200)
        check.equal(client.post("/x", headers={**GOOD_HEADER, "Origin": ALLOWED_ORIGIN}).status_code, 403)


class TestAsEndpointDependency:
    """エンドポイント単位の適用(ログアウトなど)。"""

    def test_endpoint_level_dependency(self, config):
        """エンドポイント単位の dependencies でも、変更系だけ検査される。"""
        app = FastAPI()

        @app.post("/logout", dependencies=[Depends(require_csrf_protection)])
        def logout():
            return {"ok": True}

        @app.get("/status", dependencies=[Depends(require_csrf_protection)])
        def status():
            return {"ok": True}

        test_client = TestClient(app)
        check.equal(test_client.get("/status").status_code, 200)
        check.equal(test_client.post("/logout").status_code, 403)
        check.equal(test_client.post("/logout", headers={**GOOD_HEADER, "Origin": ALLOWED_ORIGIN}).status_code, 200)


class TestOpenApi:
    """OpenAPI での表現(変更系だけの必須ヘッダー)。"""

    @pytest.fixture
    def spec(self, config) -> dict:
        """ルーター単位で require_csrf_protection を付けた、メソッドごとに別の関数を持つアプリの OpenAPI。"""
        router = APIRouter(dependencies=[Depends(require_csrf_protection)])
        for method in ("GET", "HEAD", "OPTIONS", "TRACE", "POST", "PUT", "PATCH", "DELETE"):
            router.add_api_route("/x", lambda: {"ok": True}, methods=[method], operation_id=f"x_{method.lower()}")
        app = FastAPI()
        app.include_router(router)
        install_csrf_openapi(app)
        return app.openapi()

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_unsafe_methods_require_the_header(self, spec, method):
        """変更系は X-Requested-With を必須(値は rf-stack のみ)として載せ、ヘッダーしか入力が無いので 422 は載せない。"""
        operation = spec["paths"]["/x"][method]
        check.equal([(p["in"], p["name"], p["required"], p["schema"]["enum"]) for p in operation["parameters"]], [("header", "X-Requested-With", True, ["rf-stack"])])
        check.is_in("Origin", operation["parameters"][0]["description"])
        check.is_not_in("422", operation["responses"])

    @pytest.mark.parametrize("method", ["get", "head", "options", "trace"])
    def test_safe_methods_do_not_show_the_header(self, spec, method):
        """参照系は検査しないので載せない。"""
        operation = spec["paths"]["/x"][method]
        check.is_not_in("parameters", operation)
        check.is_not_in("422", operation["responses"])

    def test_rewrite_is_idempotent_and_keeps_other_parameters(self, config):
        """何度 openapi() を呼んでも同じ結果。他のパラメータと、それによる 422 は残す。"""
        app = FastAPI()

        @app.post("/items/{item_id}", dependencies=[Depends(require_csrf_protection)])
        def update(item_id: int):
            return {"id": item_id}

        @app.get("/items/{item_id}", dependencies=[Depends(require_csrf_protection)])
        def read(item_id: int):
            return {"id": item_id}

        install_csrf_openapi(app)
        first = app.openapi()
        second = app.openapi()
        check.equal(first, second)
        post = first["paths"]["/items/{item_id}"]["post"]
        get = first["paths"]["/items/{item_id}"]["get"]
        check.equal(sorted(p["name"] for p in post["parameters"]), ["X-Requested-With", "item_id"])
        check.equal([p["name"] for p in get["parameters"]], ["item_id"])
        check.is_in("422", post["responses"])
        check.is_in("422", get["responses"])

    def test_first_header_value_is_used(self, client):
        """ヘッダーが複数ある場合は先頭の値で判定する(Header 引数にしても request.headers.get と同じ)。"""
        good_first = [("X-Requested-With", "rf-stack"), ("X-Requested-With", "other"), ("Origin", ALLOWED_ORIGIN)]
        bad_first = [("X-Requested-With", "other"), ("X-Requested-With", "rf-stack"), ("Origin", ALLOWED_ORIGIN)]
        check.equal(client.post("/x", headers=good_first).status_code, 200)
        check.equal(client.post("/x", headers=bad_first).status_code, 403)
