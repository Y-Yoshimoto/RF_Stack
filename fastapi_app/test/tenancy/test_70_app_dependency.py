# -*- coding: utf-8 -*-
"""modules.tenancy.app_dependency と create_registry_tenant_context_dependency のテスト。

- 401 / 403(TenantErrorCode ごと)と ``app.dependency_overrides[get_tenant_registry]`` による差し替え(DB 不要)
- AppSessionDep で GUC がテナント ID に設定されること、RLS によるテナント分離(``app_db`` が必要。接続できなければ skip)
"""
import uuid
from collections.abc import Iterator
from typing import Annotated

import pytest
import pytest_check as check
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from modules.auth.dependency import get_current_app_user
from modules.tenancy import app_dependency, providers
from modules.tenancy.app_dependency import AppSessionDep, AppTenantContextDep, get_app_db_session, get_app_tenant_context
from modules.tenancy.context import TenantContext, TenantContextMissingError, get_tenant_context, tenant_scope
from modules.tenancy.db import _apply_context_tenant_on_begin
from modules.tenancy.dependency import create_registry_tenant_context_dependency
from modules.tenancy.providers import get_tenant_registry
from modules.tenancy.registry import TenantRecord, TenantStatus
from modules.tenancy.resolver import TenantErrorCode


class FakeRegistry:
    """realm → TenantRecord の辞書で引くレジストリ(DB 不要)。"""

    def __init__(self, *records: TenantRecord) -> None:
        self.by_realm = {record.realm_name: record for record in records}
        self.lookups: list[str] = []

    def get_by_realm(self, realm_name: str) -> TenantRecord | None:
        self.lookups.append(realm_name)
        return self.by_realm.get(realm_name)

    def get_by_code(self, tenant_code: str) -> TenantRecord | None:
        return next((r for r in self.by_realm.values() if r.tenant_code == tenant_code), None)

    def get_by_id(self, tenant_id: uuid.UUID) -> TenantRecord | None:
        return next((r for r in self.by_realm.values() if r.tenant_id == tenant_id), None)


def _record(code: str, status: str = "ACTIVE", tenant_id: uuid.UUID | None = None) -> TenantRecord:
    return TenantRecord(tenant_id=tenant_id or uuid.uuid4(), tenant_code=code, realm_name=f"tenant-{code}", status=status)


def _user(record: TenantRecord, **overrides) -> dict:
    user = {"sub": str(uuid.uuid4()), "realm": record.realm_name, "tenant_id": str(record.tenant_id), "plane": "app", "roles": ["member"]}
    user.update(overrides)
    return user


class Harness:
    """get_app_tenant_context / AppSessionDep を使うテスト用アプリ。ユーザーとレジストリは dependency_overrides で差し替える。"""

    def __init__(self, *records: TenantRecord, session_sql: str | None = None) -> None:
        self.current_user: dict | None = None
        self.registry = FakeRegistry(*records)
        self.app = FastAPI()
        app = self.app

        def fake_user() -> dict:
            if self.current_user is None:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return self.current_user

        app.dependency_overrides[get_current_app_user] = fake_user
        app.dependency_overrides[get_tenant_registry] = lambda: self.registry

        @app.get("/context")
        def context(tenant: AppTenantContextDep, tenant_id: str | None = None):
            """クエリの tenant_id は無視され、セッション由来のコンテキストが返る。"""
            current = get_tenant_context()
            return {"tenant_id": str(tenant.tenant_id), "tenant_code": tenant.tenant_code, "seen": str(current.tenant_id) if current else None, "user_id": str(tenant.user_id)}

        if session_sql is not None:
            @app.get("/query")
            def query(session: AppSessionDep):
                return {"rows": [row[0] for row in session.connection().execute(text(session_sql)).all()]}

        self.client = TestClient(app, raise_server_exceptions=False)


class TestWiring:
    """app_dependency の組み立て。"""

    def test_types_and_aliases(self):
        """get_app_tenant_context は async の yield 依存関数で、AppSessionDep はそれに依存する。"""
        import inspect

        check.is_true(inspect.isasyncgenfunction(get_app_tenant_context))
        check.is_true(inspect.isgeneratorfunction(get_app_db_session), "セッションは同期の yield 依存(コンテキストはテナント依存が先に設定する)")
        parameters = inspect.signature(get_app_db_session).parameters
        check.equal(list(parameters), ["_tenant"], "テナント判定を引数の依存にして、判定前にセッションを開始させない")

    def test_registry_and_user_dependencies_are_the_documented_ones(self):
        """差し替え対象の依存関数(get_tenant_registry / get_current_app_user)が実際に使われている。"""
        from fastapi.dependencies.utils import get_dependant

        dependant = get_dependant(path="/x", call=get_app_tenant_context)
        calls = {sub.call for sub in dependant.dependencies}
        check.is_in(get_tenant_registry, calls)
        check.is_in(get_current_app_user, calls)


class TestUnauthenticated:
    """未認証は 401。"""

    def test_no_cookie_returns_401_without_touching_registry_or_db(self, monkeypatch):
        """Cookie が無ければ、実際の get_current_app_user が 401 を返す(Redis・レジストリ・DB へ到達しない)。"""
        registry = FakeRegistry()
        app = FastAPI()
        app.dependency_overrides[get_tenant_registry] = lambda: registry
        opened = []
        monkeypatch.setattr(app_dependency, "open_app_session", lambda: opened.append(True))

        @app.get("/q")
        def query(session: AppSessionDep):
            return {}

        response = TestClient(app, raise_server_exceptions=False).get("/q")
        check.equal(response.status_code, 401)
        check.equal(response.json(), {"detail": "Not authenticated"})
        check.equal(registry.lookups, [])
        check.equal(opened, [])

    def test_override_user_dependency_401(self):
        """差し替えたユーザー依存関数の 401 は 403 に化けずにそのまま返る。"""
        harness = Harness()
        response = harness.client.get("/context")
        check.equal(response.status_code, 401)


class TestForbidden:
    """リゾルバの拒否は 403 + TenantErrorCode のコード。"""

    def _expect_403(self, harness: Harness, code: TenantErrorCode) -> None:
        response = harness.client.get("/context")
        check.equal(response.status_code, 403)
        check.equal(response.json(), {"detail": code.value})
        check.is_none(get_tenant_context(), "拒否後にコンテキストが残らない")

    def test_claim_missing_realm(self):
        """realm が無いユーザーは tenant_claim_missing。"""
        harness = Harness(_record("alpha"))
        harness.current_user = {"sub": "s", "tenant_id": str(uuid.uuid4())}
        self._expect_403(harness, TenantErrorCode.CLAIM_MISSING)

    def test_claim_missing_tenant_id(self):
        """tenant_id クレームが無い(空文字を含む)ユーザーは tenant_claim_missing。"""
        record = _record("alpha")
        harness = Harness(record)
        for value in (None, ""):
            harness.current_user = {"sub": "s", "realm": record.realm_name, "tenant_id": value}
            self._expect_403(harness, TenantErrorCode.CLAIM_MISSING)

    @pytest.mark.parametrize("bad", ["not-a-uuid", "1234", "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz", 12345])
    def test_claim_invalid(self, bad):
        """UUID として解釈できない tenant_id は tenant_claim_invalid。"""
        record = _record("alpha")
        harness = Harness(record)
        harness.current_user = _user(record, tenant_id=bad)
        self._expect_403(harness, TenantErrorCode.CLAIM_INVALID)

    def test_not_found(self):
        """レジストリに無いレルムは tenant_not_found。"""
        ghost = _record("ghost")
        harness = Harness(_record("alpha"))
        harness.current_user = _user(ghost)
        self._expect_403(harness, TenantErrorCode.NOT_FOUND)

    def test_mismatch_hides_the_status_of_the_other_tenant(self):
        """レルムとクレームの tenant_id が食い違えば tenant_mismatch。停止中のテナントでも状態(inactive)を明かさない。"""
        record = _record("alpha", status="SUSPENDED")
        harness = Harness(record)
        harness.current_user = _user(record, tenant_id=str(uuid.uuid4()))
        self._expect_403(harness, TenantErrorCode.MISMATCH)

    @pytest.mark.parametrize("status", [s.value for s in TenantStatus if s is not TenantStatus.ACTIVE] + ["UNKNOWN_STATUS", ""])
    def test_inactive(self, status):
        """ACTIVE 以外(未知の状態を含む)は tenant_inactive。"""
        record = _record("alpha", status=status)
        harness = Harness(record)
        harness.current_user = _user(record)
        self._expect_403(harness, TenantErrorCode.INACTIVE)

    def test_every_error_code_is_covered(self):
        """TenantErrorCode の全コードが、上のテストのどれかで検証されている(コード追加時の検証漏れ防止)。"""
        covered = {TenantErrorCode.CLAIM_MISSING, TenantErrorCode.CLAIM_INVALID, TenantErrorCode.NOT_FOUND, TenantErrorCode.MISMATCH, TenantErrorCode.INACTIVE}
        check.equal(covered, set(TenantErrorCode))

    def test_forbidden_does_not_open_a_db_session(self, monkeypatch):
        """403 のリクエストでは DB セッションを開始しない(判定前にセッションを開始しない)。"""
        record = _record("alpha", status="SUSPENDED")
        harness = Harness(record, session_sql="SELECT 1")
        opened = []
        monkeypatch.setattr(app_dependency, "open_app_session", lambda: opened.append(True))
        harness.current_user = _user(record)
        response = harness.client.get("/query")
        check.equal(response.status_code, 403)
        check.equal(opened, [])


class TestSuccess:
    """ACTIVE なテナントのユーザーはコンテキストが設定される。"""

    def test_context_comes_from_registry_and_session_user(self):
        """コンテキストはレジストリのテナント ID・コードと、ユーザーの sub から作られる。"""
        record = _record("alpha")
        harness = Harness(record)
        harness.current_user = _user(record)
        response = harness.client.get("/context")
        check.equal(response.status_code, 200)
        body = response.json()
        check.equal((body["tenant_id"], body["tenant_code"], body["seen"]), (str(record.tenant_id), "alpha", str(record.tenant_id)))
        check.equal(body["user_id"], harness.current_user["sub"])
        check.equal(harness.registry.lookups, [record.realm_name])
        check.is_none(get_tenant_context())

    def test_query_tenant_id_is_ignored(self):
        """クエリに他テナントの tenant_id を混ぜても無視され、セッション由来のテナントで処理される。"""
        mine, other = _record("alpha"), _record("beta")
        harness = Harness(mine, other)
        harness.current_user = _user(mine)
        body = harness.client.get("/context", params={"tenant_id": str(other.tenant_id)}).json()
        check.equal(body["tenant_id"], str(mine.tenant_id))

    def test_registry_override_is_honored_per_app(self):
        """app.dependency_overrides[get_tenant_registry] の差し替えがそのまま効く(差し替え後の内容で判定する)。"""
        record = _record("alpha")
        harness = Harness()
        harness.current_user = _user(record)
        check.equal(harness.client.get("/context").json(), {"detail": "tenant_not_found"})
        harness.registry.by_realm[record.realm_name] = record
        check.equal(harness.client.get("/context").status_code, 200)

    def test_status_change_is_seen_on_next_request(self):
        """レジストリの状態が SUSPENDED に変わると、次のリクエストから 403(キャッシュを挟まない差し替えレジストリの場合)。"""
        record = _record("alpha")
        harness = Harness(record)
        harness.current_user = _user(record)
        check.equal(harness.client.get("/context").status_code, 200)
        harness.registry.by_realm[record.realm_name] = _record("alpha", status="SUSPENDED", tenant_id=record.tenant_id)
        response = harness.client.get("/context")
        check.equal((response.status_code, response.json()), (403, {"detail": "tenant_inactive"}))


class TestRegistryDependencyFactory:
    """create_registry_tenant_context_dependency を独自に組み立てる場合。"""

    def test_registry_is_resolved_per_request_via_depends(self):
        """レジストリはリクエスト時に Depends で取得される(生成時には呼ばれない)。"""
        record = _record("alpha")
        calls = []

        def registry_dependency():
            calls.append(True)
            return FakeRegistry(record)

        dep = create_registry_tenant_context_dependency(registry_dependency, user_dependency=lambda: _user(record))
        check.equal(calls, [], "依存関数の生成だけではレジストリを取得しない")
        app = FastAPI()

        @app.get("/c")
        def endpoint(tenant: Annotated[TenantContext, Depends(dep)]):
            return {"code": tenant.tenant_code}

        client = TestClient(app)
        check.equal(client.get("/c").json(), {"code": "alpha"})
        check.equal(client.get("/c").json(), {"code": "alpha"})
        check.equal(len(calls), 2)


class TestOverridingTenantContext:
    """get_app_tenant_context ごと差し替える場合の注意(コンテキストを設定しないと AppSessionDep が拒否する)。"""

    def test_override_without_scope_makes_session_dependency_fail(self, monkeypatch):
        """コンテキストを設定しない関数で差し替えると、AppSessionDep は TenantContextMissingError で拒否する。"""
        app = FastAPI()
        monkeypatch.setenv("APP_DB_NAME", "x")  # 環境変数の不備ではなくコンテキスト不在で失敗することを確認する

        async def no_scope_context():
            yield TenantContext(tenant_id=uuid.uuid4(), tenant_code="alpha", plane="app")

        app.dependency_overrides[get_app_tenant_context] = no_scope_context

        @app.get("/q")
        def query(session: AppSessionDep):
            return {}

        with pytest.raises(TenantContextMissingError):
            TestClient(app).get("/q")


# ---------------------------------------------------------------------------
# DB を使うテスト(app_db / app_runtime)
# ---------------------------------------------------------------------------
@pytest.fixture
def real_providers(app_runtime_engine) -> Iterator[None]:
    """環境変数どおりの実 DB(app_runtime)をプロバイダ経由で使う。後始末でキャッシュを破棄する。"""
    providers.dispose_providers()
    # 既知の不具合の回避: dispose 後に作り直した sessionmaker に GUC リスナーが登録されないことがある
    # (test_65_providers.py の test_listener_is_installed_on_every_rebuilt_sessionmaker を参照)。
    # 本ファイルのテストは GUC の設定と RLS の分離を確認するものなので、効いていなければ直接登録して不具合の影響を受けないようにする。
    factory = providers.get_app_sessionmaker()
    if _apply_context_tenant_on_begin not in factory().dispatch.after_begin:
        event.listen(factory, "after_begin", _apply_context_tenant_on_begin)
    yield
    providers.dispose_providers()


@pytest.mark.usefixtures("real_providers")
class TestAppSessionDepWithDatabase:
    """AppSessionDep: GUC の設定と RLS による分離(app_db)。"""

    GUC_SQL = "SELECT current_setting('app.current_tenant', true)"

    def test_guc_is_set_to_the_tenant_id(self):
        """AppSessionDep のセッションでは GUC app.current_tenant がテナント ID に設定されている。"""
        record = _record("alpha")
        harness = Harness(record, session_sql=self.GUC_SQL)
        harness.current_user = _user(record)
        response = harness.client.get("/query")
        check.equal(response.status_code, 200, response.text[:200])
        check.equal(response.json(), {"rows": [str(record.tenant_id)]})

    def test_guc_follows_the_tenant_per_request_and_does_not_leak(self):
        """リクエストごとに GUC は各テナントの ID になり、接続プールの再利用で前のテナントが残らない。"""
        alpha, beta = _record("alpha"), _record("beta")
        harness = Harness(alpha, beta, session_sql=self.GUC_SQL)
        for record in (alpha, beta, alpha, beta, beta, alpha, beta, alpha):
            harness.current_user = _user(record)
            check.equal(harness.client.get("/query").json(), {"rows": [str(record.tenant_id)]})

    def test_rls_isolates_tenants_through_the_dependency(self, seeded_rls_table, tenant_a, tenant_b):
        """AppSessionDep 越しのクエリは自テナントの行だけを返し、他テナントの行は見えない。"""
        record_a = _record("alpha", tenant_id=tenant_a.tenant_id)
        record_b = _record("beta", tenant_id=tenant_b.tenant_id)
        harness = Harness(record_a, record_b, session_sql=f"SELECT title FROM {seeded_rls_table.qualified} ORDER BY title")
        harness.current_user = _user(record_a)
        check.equal(harness.client.get("/query").json(), {"rows": ["a1", "a2"]})
        harness.current_user = _user(record_b)
        check.equal(harness.client.get("/query").json(), {"rows": ["b1"]})

    def test_forged_tenant_id_claim_cannot_read_other_tenant_rows(self, seeded_rls_table, tenant_a, tenant_b):
        """alpha のレルムのまま beta の tenant_id を名乗っても、tenant_mismatch で 403(行は見えない)。"""
        record_a = _record("alpha", tenant_id=tenant_a.tenant_id)
        record_b = _record("beta", tenant_id=tenant_b.tenant_id)
        harness = Harness(record_a, record_b, session_sql=f"SELECT title FROM {seeded_rls_table.qualified}")
        harness.current_user = _user(record_a, tenant_id=str(tenant_b.tenant_id))
        response = harness.client.get("/query")
        check.equal((response.status_code, response.json()), (403, {"detail": "tenant_mismatch"}))

    def test_session_is_closed_and_context_restored_after_request(self, tenant_a):
        """リクエスト後にコンテキストが残らず、同じプロセスで続けてコンテキスト無しの open_app_session が拒否される。"""
        record = _record("alpha", tenant_id=tenant_a.tenant_id)
        harness = Harness(record, session_sql=self.GUC_SQL)
        harness.current_user = _user(record)
        check.equal(harness.client.get("/query").status_code, 200)
        check.is_none(get_tenant_context())
        with pytest.raises(TenantContextMissingError):
            with providers.open_app_session():
                pass


@pytest.mark.usefixtures("real_providers")
class TestOpenAppSessionWithDatabase:
    """open_app_session(バッチ・CLI 用)を実 DB で確認する。"""

    def test_guc_follows_tenant_scope(self, tenant_a, tenant_b):
        """tenant_scope の中で開いたセッションは、そのテナントの GUC が設定される。"""
        for tenant in (tenant_a, tenant_b):
            with tenant_scope(tenant), providers.open_app_session() as session:
                value = session.connection().execute(text("SELECT current_setting('app.current_tenant', true)")).scalar()
                check.equal(value, str(tenant.tenant_id))

    def test_no_rows_for_context_less_session_obtained_directly(self, seeded_rls_table):
        """コンテキスト無しで sessionmaker から直接セッションを作ると、RLS により 0 件(open_app_session を使う理由)。"""
        with providers.get_app_sessionmaker()() as session:
            rows = session.connection().execute(text(f"SELECT title FROM {seeded_rls_table.qualified}")).all()
        check.equal(rows, [])

    def test_uncommitted_changes_are_discarded_on_exit(self, rls_table, tenant_a, app_runtime_engine):
        """open_app_session はコミットしない。ブロックを抜けると未コミットの変更は破棄される。"""
        with tenant_scope(tenant_a), providers.open_app_session() as session:
            session.connection().execute(text(f"INSERT INTO {rls_table.qualified} (tenant_id, title) VALUES (:t, 'temp')"), {"t": str(tenant_a.tenant_id)})
        check.equal(rls_table.titles(app_runtime_engine, tenant_a), [])

    def test_writes_for_another_tenant_are_rejected_by_rls(self, rls_table, tenant_a, tenant_b):
        """テナント A のコンテキストで B の tenant_id を持つ行は書けない(WITH CHECK)。"""
        from sqlalchemy.exc import DBAPIError

        with tenant_scope(tenant_a), providers.open_app_session() as session:
            with pytest.raises(DBAPIError):
                session.connection().execute(text(f"INSERT INTO {rls_table.qualified} (tenant_id, title) VALUES (:t, 'x')"), {"t": str(tenant_b.tenant_id)})
