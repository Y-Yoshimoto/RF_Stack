# -*- coding: utf-8 -*-
"""control_plane_app(払い出しサービス・定期ジョブ)のテスト用フィクスチャ。

- DB は開発 DB の ``control_plane_db`` を使う(接続できなければ skip)。**テストで作った行は必ず後片付けする**。
  ``alpha`` / ``beta`` には触れない(テスト用のテナントコードは ``zt-`` + 乱数で、台帳の行は ID で特定して消す)。
  監査ログ(``t_cp_audit_log``)は ``cp_runtime`` では削除できないため、``cp_owner`` のエンジンで消す。
- Keycloak は ``FakeKc``(``modules.keycloak_admin.templates`` の関数の差し替え)。外部の Keycloak には接続しない。
- 接続情報は環境変数から読む(``.env`` は読まない)。

提供するフィクスチャ:
    - ``cp_db``: 台帳の作成・参照・後片付けの補助(``CpDb``)
    - ``fake_kc``: 払い出しサービスが呼ぶ Keycloak 操作のフェイク
    - ``fake_app_data``: AP のテナントデータ削除のフェイク
    - ``clock``: 進められる時計(UTC)
    - ``make_service``: ``TenantProvisioningService`` を組み立てるファクトリ
"""
import datetime as dt
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import Engine, bindparam, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlmodel import Session

from control_plane_app.services.tenant_provisioning import InitialAdminSpec, TenantProvisioningService
from modules.keycloak_admin import templates
from modules.keycloak_admin.errors import KeycloakAdminError
from modules.keycloak_admin.models import TenantRealmResult

PROTECTED_CODES = frozenset({"alpha", "beta"})
SENTINEL_PASSWORD = "Sentinel-Passw0rd-VALUE-1!"


# ---------------------------------------------------------------------------
# 時計
# ---------------------------------------------------------------------------
class Clock:
    """進められる時計(``utcnow`` の代わり)。既定は実時刻から開始する。"""

    def __init__(self, now: dt.datetime | None = None) -> None:
        self.now = now or dt.datetime.now(dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, **kwargs: float) -> dt.datetime:
        self.now += dt.timedelta(**kwargs)
        return self.now


@pytest.fixture
def clock() -> Clock:
    """進められる時計(UTC)。"""
    return Clock()


# ---------------------------------------------------------------------------
# Keycloak のフェイク
# ---------------------------------------------------------------------------
@dataclass
class FakeKc:
    """``modules.keycloak_admin.templates`` の払い出し用関数の差し替え。

    - ``calls``: 呼び出しの記録(名前と引数。パスワードは ``passwords`` に別に残す)
    - ``realms``: レルム名 → 有効かどうか(``ensure_tenant_realm`` が作り、``delete_realm_if_exists`` が消す)
    - ``errors``: 関数名 → 次に送出する例外(1 回で消費。``persistent`` に入れると毎回)
    - ``hooks``: 関数名 → 呼び出しの先頭で実行する関数(その時点の DB の状態の確認に使う)
    """

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    realms: dict[str, bool] = field(default_factory=dict)
    passwords: list[str] = field(default_factory=list)
    errors: dict[str, list[BaseException]] = field(default_factory=dict)
    persistent: dict[str, BaseException] = field(default_factory=dict)
    hooks: dict[str, Callable[[dict[str, Any]], None]] = field(default_factory=dict)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def calls_of(self, name: str) -> list[dict[str, Any]]:
        return [kwargs for call_name, kwargs in self.calls if call_name == name]

    def fail_once(self, name: str, error: BaseException) -> None:
        self.errors.setdefault(name, []).append(error)

    def fail_always(self, name: str, error: BaseException) -> None:
        self.persistent[name] = error

    def _enter(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, kwargs))
        if name in self.hooks:
            self.hooks[name](kwargs)
        if self.errors.get(name):
            raise self.errors[name].pop(0)
        if name in self.persistent:
            raise self.persistent[name]

    # -- templates の関数 -----------------------------------------------------
    def ensure_tenant_realm(self, admin, *, tenant_code, tenant_id, display_name, enabled=True, **_ignored) -> TenantRealmResult:
        self._enter("ensure_tenant_realm", {"tenant_code": tenant_code, "tenant_id": tenant_id, "display_name": display_name, "enabled": enabled})
        realm = templates.tenant_realm_name(tenant_code)
        created = realm not in self.realms
        self.realms[realm] = enabled
        return TenantRealmResult(realm_name=realm, created=created, login_client_id="fastapi-app", user_admin_client_id="tenant-user-admin")

    def ensure_tenant_user(self, admin, *, realm_name, username, email, first_name, last_name, roles, password, temporary) -> str:
        self.passwords.append(password)
        self._enter("ensure_tenant_user", {"realm_name": realm_name, "username": username, "email": email, "first_name": first_name, "last_name": last_name, "roles": list(roles), "temporary": temporary})
        return str(uuid.uuid4())

    def set_realm_enabled(self, admin, realm_name, enabled) -> None:
        self._enter("set_realm_enabled", {"realm_name": realm_name, "enabled": enabled})
        if realm_name not in self.realms:
            raise KeycloakAdminError(f"set enabled={enabled} on realm {realm_name}", 404, "realm not found")
        self.realms[realm_name] = enabled

    def delete_realm_if_exists(self, admin, realm_name) -> bool:
        self._enter("delete_realm_if_exists", {"realm_name": realm_name})
        return self.realms.pop(realm_name, None) is not None


@pytest.fixture
def fake_kc(monkeypatch) -> FakeKc:
    """払い出しサービスが使う Keycloak の操作をフェイクに差し替える(サービスは ``templates`` モジュールの属性を呼ぶ)。"""
    fake = FakeKc()
    for name in ("ensure_tenant_realm", "ensure_tenant_user", "set_realm_enabled", "delete_realm_if_exists"):
        monkeypatch.setattr(templates, name, getattr(fake, name))
    return fake


@dataclass
class FakeAppData:
    """AP のテナントデータの物理削除のフェイク(``AppTenantDataRepository`` の代わり)。"""

    calls: list[uuid.UUID] = field(default_factory=list)
    result: dict[str, int] = field(default_factory=lambda: {"t_todo": 3, "t_user": 2})
    errors: list[BaseException] = field(default_factory=list)
    hook: Callable[[uuid.UUID], None] | None = None

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> dict[str, int]:
        self.calls.append(tenant_id)
        if self.hook:
            self.hook(tenant_id)
        if self.errors:
            raise self.errors.pop(0)
        return dict(self.result)


@pytest.fixture
def fake_app_data() -> FakeAppData:
    return FakeAppData()


class FakeAdmin:
    """管理クライアントの代わり(フェイクの Keycloak 操作は ``admin`` を使わない)。コンテキストマネージャとしても使える。"""

    closed = False

    def __enter__(self) -> "FakeAdmin":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# DB(control_plane_db)
# ---------------------------------------------------------------------------
def _url(user_env: str, password_env: str) -> URL | None:
    values = {name: os.environ.get(name, "") for name in ("DB_HOST", "CONTROL_PLANE_DB_NAME", user_env, password_env)}
    if not all(values.values()):
        return None
    return URL.create("postgresql", username=values[user_env], password=values[password_env], host=values["DB_HOST"], port=int(os.environ.get("DB_PORT", "5432")), database=values["CONTROL_PLANE_DB_NAME"])


def _connectable(user_env: str, password_env: str) -> Engine:
    """接続を確認したエンジンを返す。接続できない・テーブルが無い場合は skip する(理由に資格情報を含めない)。"""
    url = _url(user_env, password_env)
    if url is None:
        pytest.skip(f"control_plane_db の接続情報の環境変数が未設定のためスキップ({user_env} など)")
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM t_tenant LIMIT 1"))
    except (OperationalError, ProgrammingError):
        engine.dispose()
        pytest.skip(f"control_plane_db に {url.username} で接続できない、またはテーブルが無いためスキップ")
    return engine


@pytest.fixture(scope="session")
def cp_runtime_engine() -> Iterator[Engine]:
    """``cp_runtime``(CP API・定期ジョブのロール)のエンジン。"""
    engine = _connectable("CP_DB_RUNTIME_USER", "CP_DB_RUNTIME_PASSWORD")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def cp_owner_engine() -> Iterator[Engine]:
    """``cp_owner``(テーブル所有者)のエンジン。``cp_runtime`` では消せない監査ログの後片付けにだけ使う。"""
    engine = _connectable("CP_DB_OWNER_USER", "CP_DB_OWNER_PASSWORD")
    yield engine
    engine.dispose()


class CpDb:
    """control_plane_db の補助。作成した行を記録し、``cleanup`` で片付ける。

    読み取りはサービスのセッションとは別の接続で行う(コミット済みの内容を確認するため)。
    """

    def __init__(self, runtime: Engine, owner: Engine) -> None:
        self.runtime = runtime
        self.owner = owner
        self.tenant_ids: list[uuid.UUID] = []
        self.codes: list[str] = []
        self.job_run_ids: list[uuid.UUID] = []

    # -- 作成 ---------------------------------------------------------------
    def new_code(self) -> str:
        """テスト用のテナントコード(``zt-`` + 乱数。形式を満たし、予約語・alpha / beta と衝突しない)を払い出す。"""
        code = f"zt-{uuid.uuid4().hex[:10]}"
        self.codes.append(code)
        return code

    def session(self) -> Session:
        """``cp_runtime`` のセッション(サービスに渡す)。"""
        return Session(self.runtime)

    def insert_tenant(
        self,
        *,
        status: str = "ACTIVE",
        code: str | None = None,
        version: int = 1,
        name: str = "Test Tenant",
        deletion_requested_at: dt.datetime | None = None,
        with_running_history: bool = False,
    ) -> uuid.UUID:
        """台帳に直接テナントを作る(任意の状態から操作を試すための準備。外部呼び出しはしない)。"""
        code = code or self.new_code()
        assert code not in PROTECTED_CODES
        tenant_id = uuid.uuid7()
        self.tenant_ids.append(tenant_id)
        with self.runtime.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO t_tenant (id, tenant_code, name, status, realm_name, version, created_by, updated_by, deletion_requested_at) "
                    "VALUES (:id, :code, :name, :status, :realm, :version, 'pytest', 'pytest', :requested)"
                ),
                {"id": tenant_id, "code": code, "name": name, "status": status, "realm": f"tenant-{code}", "version": version, "requested": deletion_requested_at},
            )
            if with_running_history:
                connection.execute(
                    text("INSERT INTO t_provisioning_history (tenant_id, type, status, step, started_at) VALUES (:id, 'onboard', 'RUNNING', 'ensure_tenant_realm', :started)"),
                    {"id": tenant_id, "started": dt.datetime.now(dt.UTC)},
                )
        return tenant_id

    # -- 参照 ---------------------------------------------------------------
    def tenant(self, tenant_id: uuid.UUID) -> dict[str, Any] | None:
        with self.runtime.connect() as connection:
            row = connection.execute(text("SELECT * FROM t_tenant WHERE id = :id"), {"id": tenant_id}).mappings().first()
        return dict(row) if row else None

    def tenant_by_code(self, code: str) -> dict[str, Any] | None:
        with self.runtime.connect() as connection:
            row = connection.execute(text("SELECT * FROM t_tenant WHERE tenant_code = :code"), {"code": code}).mappings().first()
        if row and row["id"] not in self.tenant_ids:
            self.tenant_ids.append(row["id"])
        return dict(row) if row else None

    def histories(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        with self.runtime.connect() as connection:
            rows = connection.execute(text("SELECT * FROM t_provisioning_history WHERE tenant_id = :id ORDER BY started_at, id"), {"id": tenant_id}).mappings().all()
        return [dict(row) for row in rows]

    def audits(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        with self.runtime.connect() as connection:
            rows = connection.execute(text("SELECT * FROM t_cp_audit_log WHERE target_tenant_id = :id ORDER BY created_at, id"), {"id": tenant_id}).mappings().all()
        return [dict(row) for row in rows]

    def audit_actions(self, tenant_id: uuid.UUID) -> list[str]:
        return [row["action"] for row in self.audits(tenant_id)]

    def dump_text(self, tenant_id: uuid.UUID) -> str:
        """テナントに関する台帳・履歴・監査ログの全内容を 1 つの文字列にする(秘匿値が残っていないことの確認用)。"""
        return repr([self.tenant(tenant_id), self.histories(tenant_id), self.audits(tenant_id)])

    def job_run(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        with self.runtime.connect() as connection:
            row = connection.execute(text("SELECT * FROM t_scheduled_job_run WHERE id = :id"), {"id": run_id}).mappings().first()
        return dict(row) if row else None

    def foreign_tenants_in(self, statuses: tuple[str, ...]) -> list[str]:
        """このテストが作ったもの以外で、指定の状態にあるテナントのコード(ジョブが巻き込むと危険な行の検出用)。"""
        with self.runtime.connect() as connection:
            rows = connection.execute(text("SELECT id, tenant_code FROM t_tenant WHERE status IN :statuses").bindparams(bindparam("statuses", expanding=True)), {"statuses": list(statuses)}).all()
        return [code for tenant_id, code in rows if tenant_id not in self.tenant_ids]

    # -- 後片付け -------------------------------------------------------------
    def cleanup(self) -> None:
        """作成した行を削除する(日次メトリクス・履歴 → 台帳は ``cp_runtime``、監査ログは ``cp_owner``)。alpha / beta には触れない。"""
        ids = list(dict.fromkeys(self.tenant_ids))
        if self.codes:
            with self.runtime.connect() as connection:
                found = connection.execute(text("SELECT id FROM t_tenant WHERE tenant_code IN :codes").bindparams(bindparam("codes", expanding=True)), {"codes": self.codes}).scalars().all()
            ids.extend(i for i in found if i not in ids)
        if ids:
            with self.runtime.connect() as connection:
                protected = connection.execute(text("SELECT tenant_code FROM t_tenant WHERE id IN :ids AND tenant_code IN ('alpha', 'beta')").bindparams(bindparam("ids", expanding=True)), {"ids": ids}).all()
            assert not protected, "alpha / beta は後片付けの対象にしてはならない"
            with self.owner.begin() as connection:
                connection.execute(text("DELETE FROM t_cp_audit_log WHERE target_tenant_id IN :ids").bindparams(bindparam("ids", expanding=True)), {"ids": ids})
            with self.runtime.begin() as connection:
                connection.execute(text("DELETE FROM t_tenant_daily_metric WHERE tenant_id IN :ids").bindparams(bindparam("ids", expanding=True)), {"ids": ids})
                connection.execute(text("DELETE FROM t_provisioning_history WHERE tenant_id IN :ids").bindparams(bindparam("ids", expanding=True)), {"ids": ids})
                connection.execute(text("DELETE FROM t_tenant WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)), {"ids": ids})
        if self.job_run_ids:
            with self.runtime.begin() as connection:
                connection.execute(text("DELETE FROM t_scheduled_job_run WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)), {"ids": self.job_run_ids})


@pytest.fixture
def cp_db(cp_runtime_engine, cp_owner_engine) -> Iterator[CpDb]:
    """control_plane_db の補助。テスト終了時に、作成した行を必ず削除する。"""
    db = CpDb(cp_runtime_engine, cp_owner_engine)
    try:
        yield db
    finally:
        db.cleanup()


# ---------------------------------------------------------------------------
# サービス
# ---------------------------------------------------------------------------
@pytest.fixture
def make_service(cp_db, fake_kc, fake_app_data, clock) -> Iterator[Callable[..., TenantProvisioningService]]:
    """``TenantProvisioningService`` を組み立てるファクトリ(フェイクの Keycloak・AP データ・時計・固定の一時パスワード付き)。"""
    sessions: list[Session] = []

    def build(**overrides: Any) -> TenantProvisioningService:
        session = overrides.pop("session", None) or cp_db.session()
        sessions.append(session)
        kwargs: dict[str, Any] = {"app_data": fake_app_data, "clock": clock, "password_generator": lambda: SENTINEL_PASSWORD}
        kwargs.update(overrides)
        return TenantProvisioningService(session, FakeAdmin(), **kwargs)

    yield build
    for session in sessions:
        session.close()


def initial_admin(email: str = "Admin@Example.com", **kwargs: Any) -> InitialAdminSpec:
    """テスト用の初期管理者。"""
    return InitialAdminSpec(email=email, **kwargs)


class JobEnvironmentGuard:
    """ジョブ(回収・物理削除)を実行しても、他の人のテナントを巻き込まないことを確認する。"""

    @staticmethod
    def require_clean(cp_db: CpDb, statuses: tuple[str, ...]) -> None:
        foreign = cp_db.foreign_tenants_in(statuses)
        if foreign:
            pytest.skip(f"開発 DB に {', '.join(statuses)} のテナントが他にあるため、ジョブのテストをスキップ(巻き込み防止)")

