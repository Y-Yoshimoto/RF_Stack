# -*- coding: utf-8 -*-
"""modules.tenancy.dependency のテスト(FastAPI の TestClient と、依存関数の直接呼び出し)。"""
import threading
import uuid
from typing import Annotated

import pytest
import pytest_check as check
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from modules.tenancy.context import TenantContext, get_tenant_context
from modules.tenancy.dependency import create_tenant_context_dependency
from modules.tenancy.registry import CachedTenantRegistry, TenantRecord
from modules.tenancy.resolver import RegistryTenantResolver, TenantErrorCode, TenantResolutionError


class MapRegistry:
    """realm → TenantRecord の辞書で引くレジストリ。"""

    def __init__(self, *records: TenantRecord) -> None:
        self.by_realm = {r.realm_name: r for r in records}

    def get_by_realm(self, realm_name: str) -> TenantRecord | None:
        return self.by_realm.get(realm_name)

    def get_by_code(self, tenant_code: str) -> TenantRecord | None:
        return None

    def get_by_id(self, tenant_id: uuid.UUID) -> TenantRecord | None:
        return None


def _record(code: str, status: str = "ACTIVE") -> TenantRecord:
    return TenantRecord(tenant_id=uuid.uuid4(), tenant_code=code, realm_name=f"tenant-{code}", status=status)


def _user(record: TenantRecord) -> dict:
    return {"sub": str(uuid.uuid4()), "realm": record.realm_name, "tenant_id": str(record.tenant_id)}


class Harness:
    """依存関数・フェイクのユーザー・各種エンドポイントを持つテスト用アプリ一式。"""

    def __init__(self, *records: TenantRecord, resolver=None) -> None:
        self.current_user: dict | None = None
        self.after_exit: list[TenantContext | None] = []
        self.resolver_threads: list[int] = []
        base_resolver = resolver or RegistryTenantResolver(CachedTenantRegistry(MapRegistry(*records)))

        def resolver_spy(user):
            self.resolver_threads.append(threading.get_ident())
            return base_resolver(user)

        def fake_user() -> dict:
            if self.current_user is None:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return self.current_user

        self.dependency = create_tenant_context_dependency(resolver_spy, user_dependency=fake_user)
        self.app = self._build_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _build_app(self) -> FastAPI:
        app = FastAPI()
        dep = self.dependency
        after_exit = self.after_exit

        async def record_after_exit():
            """tenant 依存より先に登録され、LIFO で最後に終了する。終了後のコンテキストを記録する。"""
            try:
                yield
            finally:
                after_exit.append(get_tenant_context())

        @app.get("/sync", dependencies=[Depends(record_after_exit)])
        def sync_endpoint(tenant: Annotated[TenantContext, Depends(dep)]):
            current = get_tenant_context()
            return {"dep": str(tenant.tenant_id), "seen": str(current.tenant_id) if current else None, "code": tenant.tenant_code, "user_id": str(tenant.user_id), "thread": threading.get_ident()}

        @app.get("/async", dependencies=[Depends(record_after_exit)])
        async def async_endpoint(tenant: Annotated[TenantContext, Depends(dep)]):
            current = get_tenant_context()
            return {"dep": str(tenant.tenant_id), "seen": str(current.tenant_id) if current else None, "code": tenant.tenant_code, "thread": threading.get_ident()}

        @app.get("/boom-sync", dependencies=[Depends(record_after_exit)])
        def boom_sync(tenant: Annotated[TenantContext, Depends(dep)]):
            raise RuntimeError("boom")

        @app.get("/boom-async", dependencies=[Depends(record_after_exit)])
        async def boom_async(tenant: Annotated[TenantContext, Depends(dep)]):
            raise RuntimeError("boom")

        router = APIRouter(dependencies=[Depends(dep)])

        @router.get("/routed")
        def routed():
            current = get_tenant_context()
            return {"code": current.tenant_code if current else None}

        app.include_router(router, prefix="/api")

        @app.get("/open")
        def open_endpoint():
            current = get_tenant_context()
            return {"code": current.tenant_code if current else None}

        return app


@pytest.fixture
def alpha() -> TenantRecord:
    return _record("alpha")


@pytest.fixture
def beta() -> TenantRecord:
    return _record("beta")


class TestEndpoints:
    """TestClient 経由の同期/async エンドポイント。"""

    @pytest.mark.parametrize("path", ["/sync", "/async"])
    def test_endpoint_sees_tenant_context(self, alpha, path):
        """同期/async どちらのエンドポイントからも get_tenant_context() で同じテナントが見える。"""
        harness = Harness(alpha)
        harness.current_user = _user(alpha)
        response = harness.client.get(path)
        check.equal(response.status_code, 200)
        body = response.json()
        check.equal(body["dep"], str(alpha.tenant_id))
        check.equal(body["seen"], str(alpha.tenant_id))
        check.equal(body["code"], "alpha")
        check.equal(harness.after_exit, [None], "リクエスト終了後にコンテキストが残らない")

    def test_sync_endpoint_runs_in_threadpool_and_resolver_does_not_block_loop(self, alpha):
        """リゾルバ(ブロッキング I/O を含みうる)はイベントループとは別スレッドで呼ばれる。"""
        harness = Harness(alpha)
        harness.current_user = _user(alpha)
        body = harness.client.get("/async").json()
        check.equal(len(harness.resolver_threads), 1)
        check.not_equal(harness.resolver_threads[0], body["thread"], "async エンドポイント(イベントループ)のスレッドとは別")

    def test_user_id_comes_from_sub(self, alpha):
        """sub がコンテキストの user_id になる。"""
        harness = Harness(alpha)
        harness.current_user = _user(alpha)
        body = harness.client.get("/sync").json()
        check.equal(body["user_id"], harness.current_user["sub"])

    def test_router_level_dependency(self, alpha):
        """ルーター単位の dependencies=[Depends(dep)] でも、エンドポイントからコンテキストが見える。"""
        harness = Harness(alpha)
        harness.current_user = _user(alpha)
        check.equal(harness.client.get("/api/routed").json(), {"code": "alpha"})

    def test_requests_for_different_tenants_do_not_mix(self, alpha, beta):
        """連続リクエストで別テナントのユーザーを使っても、それぞれ自分のテナントになる。"""
        harness = Harness(alpha, beta)
        for record in (alpha, beta, alpha):
            harness.current_user = _user(record)
            check.equal(harness.client.get("/sync").json()["code"], record.tenant_code)
        check.equal(harness.client.get("/open").json(), {"code": None}, "依存を使わないエンドポイントには漏れない")

    @pytest.mark.parametrize("path", ["/sync", "/async", "/api/routed"])
    def test_unauthenticated_returns_401_from_user_dependency(self, alpha, path):
        """未認証の 401 は user_dependency の結果がそのまま返る(403 に化けない)。"""
        harness = Harness(alpha)
        check.equal(harness.client.get(path).status_code, 401)

    def test_unauthenticated_with_default_user_dependency_returns_401(self, alpha):
        """既定の get_current_user を使う場合、Cookie が無ければ 401(Redis へは到達しない)。"""
        app = FastAPI()
        dep = create_tenant_context_dependency(RegistryTenantResolver(MapRegistry(alpha)))

        @app.get("/sync")
        def sync_endpoint(tenant: Annotated[TenantContext, Depends(dep)]):
            return {}

        response = TestClient(app).get("/sync")
        check.equal(response.status_code, 401)
        check.equal(response.json(), {"detail": "Not authenticated"})


class TestForbidden:
    """リゾルバが拒否した場合は 403 で detail にコード文字列。"""

    def test_inactive_tenant_returns_403_with_code(self, alpha):
        """停止中のテナントは 403 / detail=tenant_inactive で、エンドポイント本体は実行されない。"""
        suspended = _record("sus", status="SUSPENDED")
        harness = Harness(suspended)
        harness.current_user = _user(suspended)
        response = harness.client.get("/sync")
        check.equal(response.status_code, 403)
        check.equal(response.json(), {"detail": "tenant_inactive"})
        check.equal(harness.after_exit, [None])

    @pytest.mark.parametrize(
        ("user_factory", "code"),
        [
            (lambda a, b: {"sub": str(uuid.uuid4())}, TenantErrorCode.CLAIM_MISSING),
            (lambda a, b: {**_user(a), "tenant_id": "zzz"}, TenantErrorCode.CLAIM_INVALID),
            (lambda a, b: {"realm": "tenant-unknown", "tenant_id": str(uuid.uuid4())}, TenantErrorCode.NOT_FOUND),
            (lambda a, b: {**_user(a), "tenant_id": str(b.tenant_id)}, TenantErrorCode.MISMATCH),
        ],
    )
    def test_each_resolution_error_becomes_403(self, alpha, beta, user_factory, code):
        """リゾルバの各エラーコードが 403 の detail としてそのまま返る(同期/async 両方)。"""
        harness = Harness(alpha, beta)
        harness.current_user = user_factory(alpha, beta)
        for path in ("/sync", "/async", "/api/routed"):
            response = harness.client.get(path)
            check.equal(response.status_code, 403, path)
            check.equal(response.json(), {"detail": code.value}, path)

    def test_forbidden_leaves_no_context(self, alpha):
        """403 の後に続くリクエストにもコンテキストが残らない。"""
        harness = Harness(alpha)
        harness.current_user = {"realm": "x"}
        harness.client.get("/sync")
        check.equal(harness.client.get("/open").json(), {"code": None})

    def test_non_resolution_error_from_resolver_is_500_and_leaves_no_context(self, alpha):
        """リゾルバが想定外の例外を出したら 500 になり(403 に化けない)、コンテキストは残らない。"""

        def broken_resolver(user):
            raise ConnectionError("registry down")

        harness = Harness(alpha, resolver=broken_resolver)
        harness.current_user = _user(alpha)
        check.equal(harness.client.get("/sync").status_code, 500)
        check.equal(harness.client.get("/open").json(), {"code": None})


class TestRestoreAfterException:
    """エンドポイントが例外を出してもコンテキストが元に戻る。"""

    @pytest.mark.parametrize("path", ["/boom-sync", "/boom-async"])
    def test_context_is_reset_after_endpoint_exception(self, alpha, path):
        """エンドポイントの例外(500)後、依存の終了処理でコンテキストが None に戻る。"""
        harness = Harness(alpha)
        harness.current_user = _user(alpha)
        response = harness.client.get(path)
        check.equal(response.status_code, 500)
        check.equal(harness.after_exit, [None])

    @pytest.mark.asyncio
    async def test_dependency_generator_sets_and_restores(self, alpha):
        """依存関数(async ジェネレータ)を直接駆動: 開始で設定、終了で None に戻る。"""
        harness = Harness(alpha)
        generator = harness.dependency(user=_user(alpha))
        ctx = await generator.__anext__()
        check.is_(get_tenant_context(), ctx)
        check.equal(ctx.tenant_code, "alpha")
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()
        check.is_none(get_tenant_context())

    @pytest.mark.asyncio
    async def test_dependency_generator_restores_on_athrow(self, alpha):
        """依存関数に例外を投げ込んでも(エンドポイント例外の再現)、コンテキストが None に戻り例外は再送出される。"""
        harness = Harness(alpha)
        generator = harness.dependency(user=_user(alpha))
        await generator.__anext__()
        with pytest.raises(RuntimeError, match="boom"):
            await generator.athrow(RuntimeError("boom"))
        check.is_none(get_tenant_context())

    @pytest.mark.asyncio
    async def test_dependency_generator_raises_http_403_without_setting_context(self, alpha):
        """拒否時は HTTPException(403) を送出し、コンテキストは設定されない。"""
        harness = Harness(alpha)
        generator = harness.dependency(user={})
        with pytest.raises(HTTPException) as exc_info:
            await generator.__anext__()
        check.equal(exc_info.value.status_code, 403)
        check.equal(exc_info.value.detail, "tenant_claim_missing")
        check.is_none(get_tenant_context())

    @pytest.mark.asyncio
    async def test_exception_chain_is_resolution_error(self, alpha):
        """HTTPException の原因は TenantResolutionError(ログで追跡できる)。"""
        harness = Harness(alpha)
        with pytest.raises(HTTPException) as exc_info:
            await harness.dependency(user={}).__anext__()
        check.is_instance(exc_info.value.__cause__, TenantResolutionError)
