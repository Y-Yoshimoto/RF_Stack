# -*- coding: utf-8 -*-
"""dev_tools.e2e_cleanup(E2E データの後片付け。開発専用)のテスト用フィクスチャ。

**開発 DB の他のデータを消さないための分離**:

- ``E2EDataCleaner`` は本来、台帳の全テナントを走査する。テストでは ``ScopedCleaner`` が ``_list_tenants`` の結果を
  「このテストが作ったテナント」に絞る(実装は変えない。台帳の問い合わせ自体は実物)。開発 DB に本物の ``e2e-*`` テナントや
  alpha / beta があっても触れない。
- AP 側の走査対象は ``PROTECTED_TENANT_CODES``(alpha / beta)のうち ACTIVE なものだけ。使い捨てテナントの AP 側の後片付けを確認する場合は、
  ``scan_as_seed(...)`` でそのテナントコードを一時的に走査対象に加える(``monkeypatch``。終了時に元へ戻る)。
- Keycloak は ``TenantRealmIdp``(ユーザーの管理)と ``FakeKc``(払い出しのレルム操作)のフェイク。外部の Keycloak には接続しない。
- 排他ロックは既定でインメモリ(``MemoryLock``)。実際の advisory lock を使うテストだけ、キーを一意にして使う。
- 環境は ``APP_ENV=development`` / ``AUTH_DEV_LOGIN_ENABLED=true`` に固定する(コンテナの実環境値に依存しない)。

提供するフィクスチャ:
    - ``make_cleaner``: ``ScopedCleaner`` を組み立てるファクトリ(``scope`` に台帳のテナント ID を渡す)
    - ``new_e2e_code``: ``e2e-<8桁>`` のテナントコードを払い出す
    - ``scan_as_seed``: 使い捨てテナントを AP 側の走査対象にする
    - ``e2e_tenant``: 台帳に E2E の命名のテナントを作り、フェイクの Keycloak にレルムを用意する
"""
import datetime as dt
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from ap_services.conftest import ApDb, ap_db, app_cp_agent_engine, app_owner_engine, app_runtime_engine, idp  # noqa: F401
from control_plane.conftest import Clock, CpDb, FakeAdmin, FakeKc, clock, cp_db, cp_owner_engine, cp_runtime_engine, fake_kc  # noqa: F401
from sqlalchemy import text

from dev_tools import e2e_cleanup
from dev_tools.e2e_cleanup import E2EDataCleaner

__all__ = ["MemoryLock", "ScopedCleaner", "ap_db", "app_cp_agent_engine", "app_owner_engine", "app_runtime_engine", "clock", "cp_db", "cp_owner_engine", "cp_runtime_engine", "fake_kc", "idp"]


class MemoryLock:
    """``OperationLock`` のインメモリ実装(``held`` に入れたキーは取得できない)。取得の記録を ``acquired`` に残す。"""

    def __init__(self, held: set[str] | None = None) -> None:
        self.held: set[str] = set(held or ())
        self.acquired: list[str] = []

    @contextmanager
    def try_acquire(self, key: str) -> Iterator[bool]:
        if key in self.held:
            yield False
            return
        self.held.add(key)
        self.acquired.append(key)
        try:
            yield True
        finally:
            self.held.discard(key)


class ScopedCleaner(E2EDataCleaner):
    """台帳の走査対象を ``scope``(テナント ID)に絞った ``E2EDataCleaner``(テスト専用。開発 DB の他のテナントに触れないため)。"""

    def __init__(self, scope: set[uuid.UUID], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.scope = scope

    def _list_tenants(self, session):  # noqa: ANN001, ANN202
        return [tenant for tenant in super()._list_tenants(session) if tenant.id in self.scope]


class Calls:
    """差し替えた依存の呼び出しの記録。"""

    def __init__(self) -> None:
        self.provisioner = 0
        self.tenant_user_admin: list[str] = []
        self.admins: list[FakeAdmin] = []


@pytest.fixture(autouse=True)
def _dev_env(monkeypatch) -> None:
    """開発環境(``APP_ENV=development``、開発用ログイン有効)に固定する。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", "true")


@pytest.fixture
def calls() -> Calls:
    return Calls()


@pytest.fixture
def new_e2e_code() -> Callable[[], str]:
    """``e2e-<小文字英数字 8 桁>`` のテナントコードを払い出す関数。"""
    return lambda: f"e2e-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def make_cleaner(cp_db: CpDb, ap_db: ApDb, idp, calls: Calls, clock: Clock):  # noqa: F811
    """``ScopedCleaner`` を組み立てるファクトリ。``scope`` は走査対象の台帳のテナント ID(省略時は ``cp_db`` が作った全部)。

    既定の依存: CP のセッションは ``cp_runtime``、AP のエンジンは ``app_cp_agent``、払い出し用の管理クライアントは ``FakeAdmin``、
    ``tenant-user-admin`` は ``idp.factory``(レルム名を ``calls.tenant_user_admin`` に記録)、ロックは ``MemoryLock``。時計は実時刻。
    """

    def tenant_user_admin(realm: str):
        calls.tenant_user_admin.append(realm)
        return idp.factory(realm)

    def provisioner():
        calls.provisioner += 1
        admin = FakeAdmin()
        calls.admins.append(admin)
        return admin

    def build(scope: set[uuid.UUID] | None = None, **overrides: Any) -> ScopedCleaner:
        kwargs: dict[str, Any] = {
            "cp_session_factory": cp_db.session,
            "app_engine_factory": lambda: ap_db.agent,
            "provisioner_admin_factory": provisioner,
            "tenant_user_admin_factory": tenant_user_admin,
            "lock": MemoryLock(),
        }
        kwargs.update(overrides)
        return ScopedCleaner(set(scope) if scope is not None else set(cp_db.tenant_ids), **kwargs)

    return build


@pytest.fixture
def scan_as_seed(monkeypatch):
    """テナントコードを AP 側の走査対象(``PROTECTED_TENANT_CODES``)に加える関数。同時に保護対象にもなる(``is_e2e_tenant_code`` は False)。"""

    def add(*codes: str) -> None:
        monkeypatch.setattr(e2e_cleanup, "PROTECTED_TENANT_CODES", frozenset({*e2e_cleanup.PROTECTED_TENANT_CODES, *codes}))

    return add


@pytest.fixture
def e2e_tenant(cp_db: CpDb, fake_kc: FakeKc, new_e2e_code) -> Callable[..., uuid.UUID]:  # noqa: F811
    """台帳に E2E の命名(``e2e-<8桁>``)のテナントを作るファクトリ。ACTIVE / SUSPENDED / PENDING_DELETION / DEPROVISIONING にはフェイクの Keycloak にレルムを用意する。

    ``updated_at_ago`` を渡すと台帳の最終更新日時をその分だけ過去にする(PROVISIONING の経過時間の確認)。
    """

    def create(status: str = "ACTIVE", *, code: str | None = None, updated_at_ago: dt.timedelta | None = None, **kwargs: Any) -> uuid.UUID:
        code = code or new_e2e_code()
        if status in ("PENDING_DELETION", "DEPROVISIONING"):
            kwargs.setdefault("deletion_requested_at", dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
        tenant_id = cp_db.insert_tenant(status=status, code=code, **kwargs)
        if status in ("ACTIVE", "SUSPENDED", "PENDING_DELETION", "DEPROVISIONING"):
            fake_kc.realms[f"tenant-{code}"] = status == "ACTIVE"
        if updated_at_ago is not None:
            with cp_db.runtime.begin() as connection:
                connection.execute(text("UPDATE t_tenant SET updated_at = :at WHERE id = :id"), {"at": dt.datetime.now(dt.UTC) - updated_at_ago, "id": tenant_id})
        return tenant_id

    return create

