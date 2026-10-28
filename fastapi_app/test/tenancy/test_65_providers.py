# -*- coding: utf-8 -*-
"""modules.tenancy.providers(ロール毎のエンジン・sessionmaker・レジストリの遅延生成)のテスト。

DB へは接続しない(接続先は存在しないホストに向けた偽の環境変数)。実 DB を使う確認は test_70_app_dependency.py。
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import pytest_check as check

from modules.tenancy import providers
from modules.tenancy.context import TenantContextMissingError, tenant_scope
from modules.tenancy.db import _apply_context_tenant_on_begin
from modules.tenancy.registry import CachedTenantRegistry

# ロール毎の (ユーザー, パスワード, DB 名) の環境変数名と、取得関数
ROLE_ENV = {
    "cp_registry_reader": ("CP_DB_REGISTRY_READER_USER", "CP_DB_REGISTRY_READER_PASSWORD", "CONTROL_PLANE_DB_NAME", providers.get_cp_registry_reader_engine),
    "cp_runtime": ("CP_DB_RUNTIME_USER", "CP_DB_RUNTIME_PASSWORD", "CONTROL_PLANE_DB_NAME", providers.get_cp_runtime_engine),
    "app_runtime": ("APP_DB_RUNTIME_USER", "APP_DB_RUNTIME_PASSWORD", "APP_DB_NAME", providers.get_app_runtime_engine),
    "app_cp_agent": ("APP_DB_CP_AGENT_USER", "APP_DB_CP_AGENT_PASSWORD", "APP_DB_NAME", providers.get_app_cp_agent_engine),
}
ALL_DB_ENV_NAMES = ("DB_HOST", "DB_PORT", "CONTROL_PLANE_DB_NAME", "APP_DB_NAME") + tuple(name for user, password, _db, _fn in ROLE_ENV.values() for name in (user, password))
FAKE_PASSWORD_MARK = "pw-sentinel-must-not-leak"


@pytest.fixture(autouse=True)
def _fresh_providers():
    """各テストの前後でプロバイダのキャッシュを破棄する(他のテストへ偽の接続先を残さない)。"""
    providers.dispose_providers()
    yield
    providers.dispose_providers()


@pytest.fixture
def fake_db_env(monkeypatch):
    """存在しない接続先を向く偽の DB 環境変数を設定する(ロール毎に別のユーザー名)。"""
    monkeypatch.setenv("DB_HOST", "db.invalid")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("CONTROL_PLANE_DB_NAME", "cp_db_x")
    monkeypatch.setenv("APP_DB_NAME", "app_db_x")
    for role, (user_env, password_env, _db_env, _fn) in ROLE_ENV.items():
        monkeypatch.setenv(user_env, f"user_{role}")
        monkeypatch.setenv(password_env, f"{FAKE_PASSWORD_MARK}-{role}")


def _lazy_values() -> list:
    """プロバイダが保持する遅延リソースの現在値を返す(未生成は None)。"""
    lazies = [providers._tenant_registry, providers._app_sessionmaker, providers._cp_sessionmaker, *providers._ENGINES]
    return [lazy._value for lazy in lazies]


class TestImportIsSideEffectFree:
    """import 時に環境変数を読まず、接続もしない。"""

    def test_import_without_any_db_env_creates_nothing(self):
        """DB の環境変数が一つも無いプロセスで import しても、何も生成されず例外にもならない。"""
        src_dir = str(Path(providers.__file__).resolve().parents[2])
        code = (
            "import modules.tenancy.providers as p, modules.tenancy.app_dependency\n"
            "lazies = [p._tenant_registry, p._app_sessionmaker, p._cp_sessionmaker, *p._ENGINES]\n"
            "assert all(lazy._value is None for lazy in lazies)\n"
            "print('ok')\n"
        )
        result = subprocess.run([sys.executable, "-c", code], env={"PYTHONPATH": src_dir, "PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=60, check=False)
        check.equal(result.returncode, 0, result.stderr[-500:])
        check.equal(result.stdout.strip(), "ok")

    def test_nothing_is_created_after_dispose(self, fake_db_env):
        """dispose_providers() の後は、何も保持していない状態に戻る。"""
        providers.get_cp_runtime_engine()
        providers.dispose_providers()
        check.is_true(all(value is None for value in _lazy_values()))


class TestEngines:
    """ロール毎のエンジン。"""

    @pytest.mark.parametrize("role", list(ROLE_ENV))
    def test_engine_uses_the_roles_credentials_and_database(self, fake_db_env, role):
        """各エンジンは、そのロールの環境変数(ユーザー・DB 名)で作られ、生成だけでは接続しない。"""
        _user_env, _password_env, db_env, getter = ROLE_ENV[role]
        engine = getter()
        check.equal(engine.url.username, f"user_{role}")
        check.equal(engine.url.database, {"CONTROL_PLANE_DB_NAME": "cp_db_x", "APP_DB_NAME": "app_db_x"}[db_env])
        check.equal(engine.url.host, "db.invalid")
        check.is_true(engine.pool._pre_ping, "切れた接続を払い出さない(pool_pre_ping)")

    @pytest.mark.parametrize("role", list(ROLE_ENV))
    def test_engine_is_a_process_wide_singleton(self, fake_db_env, role):
        """同じロールのエンジンは何度呼んでも同じインスタンス。"""
        getter = ROLE_ENV[role][3]
        check.is_true(getter() is getter())

    def test_engines_are_distinct_per_role(self, fake_db_env):
        """ロールが違えばエンジンも別(権限の違う接続を共有しない)。"""
        engines = [getter() for *_rest, getter in ROLE_ENV.values()]
        check.equal(len({id(engine) for engine in engines}), len(engines))

    def test_dispose_rebuilds_from_current_environment(self, fake_db_env, monkeypatch):
        """dispose_providers() の後は環境変数を読み直して作り直す。"""
        first = providers.get_cp_runtime_engine()
        providers.dispose_providers()
        monkeypatch.setenv("CP_DB_RUNTIME_USER", "user_changed")
        second = providers.get_cp_runtime_engine()
        check.is_false(first is second)
        check.equal(second.url.username, "user_changed")

    def test_dispose_disposes_created_engines(self, fake_db_env, monkeypatch):
        """生成済みのエンジンは dispose される(プールの接続を閉じる)。"""
        disposed = []
        engine = providers.get_cp_runtime_engine()
        monkeypatch.setattr(engine, "dispose", lambda *a, **k: disposed.append(True))
        providers.dispose_providers()
        check.equal(disposed, [True])

    def test_dispose_is_safe_when_nothing_was_created(self):
        """何も生成していない状態で呼んでも、繰り返し呼んでも例外にならない。"""
        providers.dispose_providers()
        providers.dispose_providers()

    def test_concurrent_first_access_creates_once(self, fake_db_env, monkeypatch):
        """同時に初回アクセスしてもエンジンの生成は 1 回だけ(ロックで保護)。"""
        calls = []
        real_from_env = providers.DBConnector.from_env.__func__

        def slow_from_env(cls, *args, **kwargs):
            calls.append(threading.get_ident())
            time.sleep(0.05)
            return real_from_env(cls, *args, **kwargs)

        monkeypatch.setattr(providers.DBConnector, "from_env", classmethod(slow_from_env))
        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            results.append(providers.get_cp_runtime_engine())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        check.equal(len(calls), 1)
        check.equal(len({id(engine) for engine in results}), 1)


class TestMissingEnvironment:
    """環境変数が足りない場合は、変数名だけを含むエラーになる。"""

    def test_error_names_only_the_missing_variables(self, fake_db_env, monkeypatch):
        """欠けた変数名がメッセージに入り、他の変数の値(パスワード・ホスト名)は入らない。"""
        monkeypatch.delenv("CP_DB_RUNTIME_USER")
        monkeypatch.delenv("DB_PORT")
        with pytest.raises(RuntimeError) as exc_info:
            providers.get_cp_runtime_engine()
        message = str(exc_info.value)
        check.is_in("CP_DB_RUNTIME_USER", message)
        check.is_in("DB_PORT", message)
        check.is_not_in("CP_DB_RUNTIME_PASSWORD", message, "設定済みの変数名は出さない")
        check.is_not_in(FAKE_PASSWORD_MARK, message)
        check.is_not_in("db.invalid", message)

    def test_empty_value_is_treated_as_missing_without_leaking_others(self, fake_db_env, monkeypatch):
        """空文字の変数も未設定として扱う。パスワードの値はメッセージに出ない。"""
        monkeypatch.setenv("APP_DB_RUNTIME_PASSWORD", "")
        with pytest.raises(RuntimeError) as exc_info:
            providers.get_app_runtime_engine()
        check.is_in("APP_DB_RUNTIME_PASSWORD", str(exc_info.value))
        check.is_not_in(FAKE_PASSWORD_MARK, str(exc_info.value))

    def test_failure_is_not_cached(self, fake_db_env, monkeypatch):
        """失敗した生成はキャッシュされず、環境変数を直した後の呼び出しで成功する。"""
        monkeypatch.delenv("APP_DB_CP_AGENT_USER")
        with pytest.raises(RuntimeError):
            providers.get_app_cp_agent_engine()
        monkeypatch.setenv("APP_DB_CP_AGENT_USER", "user_fixed")
        check.equal(providers.get_app_cp_agent_engine().url.username, "user_fixed")

    def test_other_roles_are_unaffected(self, fake_db_env, monkeypatch):
        """あるロールの変数が欠けていても、別ロールのエンジンは生成できる(必要になった時点で個別に読む)。"""
        monkeypatch.delenv("CP_DB_REGISTRY_READER_PASSWORD")
        check.equal(providers.get_cp_runtime_engine().url.username, "user_cp_runtime")
        with pytest.raises(RuntimeError):
            providers.get_cp_registry_reader_engine()

    def test_registry_creation_reports_missing_variables(self, fake_db_env, monkeypatch):
        """レジストリの生成は cp_registry_reader の変数を読み、欠けていれば変数名のエラーになる。"""
        monkeypatch.delenv("CP_DB_REGISTRY_READER_USER")
        with pytest.raises(RuntimeError, match="CP_DB_REGISTRY_READER_USER"):
            providers.get_tenant_registry()


class TestSessionmakers:
    """sessionmaker とテナント GUC のリスナー。"""

    def test_guc_listener_is_installed_only_on_the_app_runtime_sessionmaker(self, fake_db_env):
        """GUC リスナーは app_runtime の sessionmaker にだけ登録され、cp_runtime の sessionmaker には登録されない。

        登録の有無は event.contains ではなく、実際に作られるセッションの dispatch で確認する(id の再利用による誤判定を避ける)。
        """
        app_factory = providers.get_app_sessionmaker()
        cp_factory = providers.get_cp_sessionmaker()
        check.is_true(_apply_context_tenant_on_begin in app_factory().dispatch.after_begin)
        check.is_false(_apply_context_tenant_on_begin in cp_factory().dispatch.after_begin)

    def test_listener_is_installed_on_every_rebuilt_sessionmaker(self, fake_db_env):
        """dispose_providers() で破棄して作り直した app_runtime の sessionmaker にも、毎回 GUC リスナーが効くこと(200 回)。"""
        import gc

        missing = 0
        for index in range(200):
            providers.dispose_providers()
            factory = providers.get_app_sessionmaker()
            if _apply_context_tenant_on_begin not in factory().dispatch.after_begin:
                missing += 1
            if index % 7 == 0:
                gc.collect()
        check.equal(missing, 0, f"リスナーが効いていない sessionmaker が {missing}/200 回あった")

    def test_session_class_itself_has_no_listener(self, fake_db_env):
        """Session クラス全体にはリスナーを登録しない(CP DB のセッションに効いてしまうため)。"""
        from sqlmodel import Session

        providers.get_app_sessionmaker()
        check.is_false(_apply_context_tenant_on_begin in Session().dispatch.after_begin)

    def test_sessionmakers_are_bound_to_their_roles(self, fake_db_env):
        """sessionmaker はそれぞれ app_runtime / cp_runtime のエンジンに結び付く。"""
        check.is_true(providers.get_app_sessionmaker().kw["bind"] is providers.get_app_runtime_engine())
        check.is_true(providers.get_cp_sessionmaker().kw["bind"] is providers.get_cp_runtime_engine())

    def test_sessionmakers_are_singletons(self, fake_db_env):
        """sessionmaker もプロセス内で共有される。"""
        check.is_true(providers.get_app_sessionmaker() is providers.get_app_sessionmaker())
        check.is_true(providers.get_cp_sessionmaker() is providers.get_cp_sessionmaker())

    def test_registry_is_cached_sql_registry_on_registry_reader(self, fake_db_env):
        """レジストリは cp_registry_reader のエンジンを使うキャッシュ付きの実装で、同じインスタンスが共有される。"""
        registry = providers.get_tenant_registry()
        check.is_instance(registry, CachedTenantRegistry)
        check.is_true(registry is providers.get_tenant_registry())
        check.is_true(registry._inner._engine is providers.get_cp_registry_reader_engine())


class TestOpenAppSession:
    """open_app_session はテナントコンテキストを必須とする。"""

    def test_rejects_when_no_tenant_context(self, fake_db_env):
        """コンテキスト無しではセッションを開始せず TenantContextMissingError にする。"""
        with pytest.raises(TenantContextMissingError):
            with providers.open_app_session():
                pytest.fail("セッションを開始してはならない")
        check.is_none(providers._app_sessionmaker._value, "sessionmaker(エンジン)も生成しない")

    def test_rejects_before_reading_environment(self, monkeypatch):
        """コンテキスト無しの拒否は、環境変数の検査より先に行われる(設定不備で別の例外に化けない)。"""
        for name in ALL_DB_ENV_NAMES:
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(TenantContextMissingError):
            with providers.open_app_session():
                pytest.fail("セッションを開始してはならない")

    def test_with_context_opens_a_session_without_connecting(self, fake_db_env, tenant_a):
        """コンテキストがあればセッションを返す(最初のクエリまで接続しない)。"""
        with tenant_scope(tenant_a), providers.open_app_session() as session:
            check.is_true(session.get_bind() is providers.get_app_runtime_engine())
            check.is_false(session.in_transaction())

    def test_context_must_be_active_not_just_created(self, fake_db_env, tenant_a):
        """tenant_scope を抜けた後は、再び拒否される。"""
        with tenant_scope(tenant_a), providers.open_app_session():
            pass
        with pytest.raises(TenantContextMissingError):
            with providers.open_app_session():
                pass

    def test_none_scope_is_not_a_context(self, fake_db_env):
        """tenant_scope(None) は『コンテキスト無し』のままで、拒否される。"""
        with tenant_scope(None), pytest.raises(TenantContextMissingError):
            with providers.open_app_session():
                pass

