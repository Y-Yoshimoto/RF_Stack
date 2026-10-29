# -*- coding: utf-8 -*-
"""modules.tenant_metrics.registry(テーマ固有指標の登録箇所の読み込み)と、基盤の指標とのキー重複の検証のテスト。DB には接続しない。"""
import sys
import types

import pytest
import pytest_check as check

from control_plane_app.repositories import app_tenant_metrics
from control_plane_app.repositories.app_tenant_metrics import USER_METRICS, AppTenantMetricsRepository, default_metric_sets
from main_app.repositories.todos.metrics import TODO_METRICS
from modules.tenant_metrics import registry
from modules.tenant_metrics.definition import TenantMetricSet
from modules.tenant_metrics.registry import THEME_METRIC_SOURCES, load_theme_metric_sets, theme_primary_metric_keys


def metric_set(name, *keys, primary=()):
    return TenantMetricSet(name=name, keys=tuple(keys), collect=lambda session, tenant_id: {key: 0 for key in keys}, primary_keys=tuple(primary))


@pytest.fixture
def fake_module(monkeypatch):
    """属性を持つ一時的なモジュールを登録するファクトリ(終了時に取り除く)。"""

    def create(name: str, **attributes) -> str:
        module = types.ModuleType(name)
        for key, value in attributes.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return name

    return create


class TestRegisteredSources:
    """実際に登録されているテーマ(ToDo)。"""

    def test_todo_metrics_are_registered(self):
        """ToDo の指標セットが登録されており、読み込むと TODO_METRICS そのものが返る。"""
        check.is_in("main_app.repositories.todos.metrics:TODO_METRICS", THEME_METRIC_SOURCES)
        check.equal(load_theme_metric_sets(), (TODO_METRICS,))

    def test_todo_metric_keys(self):
        """ToDo の指標は todo_count とステータス別の 3 つで、主要指標は todo_count だけ(docs/spec/ToDoApp.md §7 #5)。"""
        check.equal(TODO_METRICS.keys, ("todo_count", "todo_open_count", "todo_in_progress_count", "todo_done_count"))
        check.equal(theme_primary_metric_keys(), ("todo_count",))

    def test_default_metric_sets_are_foundation_then_theme(self):
        """集計する指標セットは、基盤(ユーザー数)→ テーマの順で、キーの重複が無い。"""
        sets = default_metric_sets()
        check.equal(sets, (USER_METRICS, TODO_METRICS))
        check.equal(USER_METRICS.keys, ("users_total", "users_active"))

    def test_repository_metric_keys(self):
        """集計リポジトリの指標キーは、指標セットの順に並ぶ。エンジンは最初の集計まで作らない。"""
        calls = []
        repository = AppTenantMetricsRepository(engine_factory=lambda: calls.append(1))
        check.equal(repository.metric_keys, ["users_total", "users_active", "todo_count", "todo_open_count", "todo_in_progress_count", "todo_done_count"])
        check.equal(calls, [])


class TestLoading:
    """"<モジュール>:<属性>" の読み込み。"""

    def test_single_and_sequences(self, fake_module):
        """属性は指標セット 1 つ、または tuple / list。登録順に並ぶ。"""
        one, two, three = metric_set("one", "one_a"), metric_set("two", "two_a"), metric_set("three", "three_a")
        name = fake_module("zt_theme_ok", ONE=one, TUPLE=(two,), LIST=[three])
        check.equal(load_theme_metric_sets([f"{name}:ONE", f"{name}:TUPLE", f"{name}:LIST"]), (one, two, three))

    def test_empty_sources(self):
        """提供元が無ければ空(テーマが指標を持たない)。"""
        check.equal(load_theme_metric_sets([]), ())
        check.equal(theme_primary_metric_keys([]), ())

    def test_primary_keys_in_registration_order(self, fake_module):
        """主要指標のキーは、登録順・セット内の宣言順に並ぶ。主要指標を持たないセットは寄与しない。"""
        name = fake_module("zt_theme_primary", A=metric_set("a", "a_1", "a_2", primary=("a_2", "a_1")), B=metric_set("b", "b_1"), C=metric_set("c", "c_1", primary=("c_1",)))
        check.equal(theme_primary_metric_keys([f"{name}:A", f"{name}:B", f"{name}:C"]), ("a_2", "a_1", "c_1"))

    @pytest.mark.parametrize("source", ["", "no_colon", ":attr", "module:", "a.b.c"])
    def test_invalid_format(self, source):
        """"<モジュール>:<属性>" の形式でなければ ValueError。"""
        with pytest.raises(ValueError, match="invalid theme metric source"):
            load_theme_metric_sets([source])

    def test_attribute_must_be_metric_set(self, fake_module):
        """属性が指標セットでない(文字列・辞書、または指標セット以外を含む列)なら ValueError。"""
        name = fake_module("zt_theme_bad", TEXT="x", MIXED=(metric_set("m", "m_1"), "x"), MAPPING={"m": 1})
        for attr in ("TEXT", "MIXED", "MAPPING"):
            with pytest.raises(ValueError, match="must be TenantMetricSet"):
                load_theme_metric_sets([f"{name}:{attr}"])

    def test_missing_module_and_attribute(self):
        """モジュールが無ければ ImportError、属性が無ければ AttributeError(登録の誤りは起動時に気づける)。"""
        with pytest.raises(ImportError):
            load_theme_metric_sets(["zt_no_such_module_xyz:ATTR"])
        with pytest.raises(AttributeError):
            load_theme_metric_sets(["main_app.repositories.todos.metrics:NO_SUCH_ATTRIBUTE"])


class TestKeyCollisions:
    """指標キー・セット名の重複は、読み込み・集計の準備の時点でエラーにする。"""

    def test_duplicate_key_between_theme_sets(self, fake_module):
        """テーマ内の 2 つのセットが同じキーを定義すると ValueError。"""
        name = fake_module("zt_theme_dup", A=metric_set("a", "shared_count"), B=metric_set("b", "shared_count"))
        with pytest.raises(ValueError, match="shared_count"):
            load_theme_metric_sets([f"{name}:A", f"{name}:B"])

    def test_same_source_twice_is_a_collision(self):
        """同じ提供元を 2 回登録するとキーが重複して ValueError。"""
        source = "main_app.repositories.todos.metrics:TODO_METRICS"
        with pytest.raises(ValueError):
            load_theme_metric_sets([source, source])

    def test_theme_key_colliding_with_foundation_metric(self, fake_module, monkeypatch):
        """テーマが基盤の指標(users_total)と同じキーを定義すると、集計の準備(default_metric_sets・リポジトリの生成)で ValueError。"""
        name = fake_module("zt_theme_users", CLASH=metric_set("clash", "users_total"))
        monkeypatch.setattr(app_tenant_metrics, "load_theme_metric_sets", lambda: load_theme_metric_sets([f"{name}:CLASH"]))
        with pytest.raises(ValueError, match="users_total"):
            default_metric_sets()
        with pytest.raises(ValueError, match="users_total"):
            AppTenantMetricsRepository(engine_factory=lambda: None)

    def test_repository_validates_explicit_metric_sets(self):
        """指標セットを明示しても、キーの重複は ValueError。"""
        with pytest.raises(ValueError):
            AppTenantMetricsRepository(engine_factory=lambda: None, metric_sets=[metric_set("a", "x_count"), metric_set("b", "x_count")])

    def test_default_sources_constant_is_the_registration_point(self):
        """登録箇所は registry.THEME_METRIC_SOURCES だけ(load_theme_metric_sets の既定引数と同じ値)。"""
        check.is_(registry.load_theme_metric_sets.__defaults__[0], THEME_METRIC_SOURCES)
