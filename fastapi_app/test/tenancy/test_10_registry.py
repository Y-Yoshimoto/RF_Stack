# -*- coding: utf-8 -*-
"""modules.tenancy.registry のユニットテスト(CachedTenantRegistry / TenantRecord / is_active / SqlTenantRegistry の検証部分)。"""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import pytest_check as check

from modules.tenancy.registry import (
    DEFAULT_CACHE_MAX_ENTRIES,
    DEFAULT_CACHE_TTL_SECONDS,
    CachedTenantRegistry,
    SqlTenantRegistry,
    TenantRecord,
    TenantStatus,
    is_active,
)


def _record(code: str = "alpha", status: str = "ACTIVE") -> TenantRecord:
    """テスト用のレコードを作る。"""
    return TenantRecord(tenant_id=uuid.uuid4(), tenant_code=code, realm_name=f"tenant-{code}", status=status)


class FakeClock:
    """進められる時計。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CountingRegistry:
    """問い合わせ回数を数えるインメモリのレジストリ。"""

    def __init__(self, records: list[TenantRecord] | None = None) -> None:
        self.records = list(records or [])
        self.calls: list[tuple[str, object]] = []
        self.error: Exception | None = None

    def _find(self, kind: str, key: object, predicate) -> TenantRecord | None:
        self.calls.append((kind, key))
        if self.error is not None:
            raise self.error
        return next((r for r in self.records if predicate(r)), None)

    def get_by_code(self, tenant_code: str) -> TenantRecord | None:
        return self._find("code", tenant_code, lambda r: r.tenant_code == tenant_code)

    def get_by_realm(self, realm_name: str) -> TenantRecord | None:
        return self._find("realm", realm_name, lambda r: r.realm_name == realm_name)

    def get_by_id(self, tenant_id: uuid.UUID) -> TenantRecord | None:
        return self._find("id", tenant_id, lambda r: r.tenant_id == tenant_id)


class TestTenantRecord:
    """TenantRecord.from_mapping。"""

    def test_from_mapping_converts_str_uuid(self):
        """文字列の tenant_id を UUID に正規化する。"""
        tenant_id = uuid.uuid4()
        record = TenantRecord.from_mapping({"tenant_id": str(tenant_id), "tenant_code": "alpha", "realm_name": "tenant-alpha", "status": "ACTIVE"})
        check.equal(record, TenantRecord(tenant_id=tenant_id, tenant_code="alpha", realm_name="tenant-alpha", status="ACTIVE"))
        check.is_instance(record.tenant_id, uuid.UUID)

    def test_from_mapping_keeps_uuid_object_and_ignores_extra_columns(self):
        """UUID はそのまま、余分な列は無視する。"""
        tenant_id = uuid.uuid4()
        record = TenantRecord.from_mapping({"tenant_id": tenant_id, "tenant_code": "a", "realm_name": "r", "status": "SUSPENDED", "extra": 1})
        check.is_(record.tenant_id, tenant_id)
        check.equal(record.status, "SUSPENDED")

    def test_from_mapping_stringifies_other_columns(self):
        """文字列以外の値(Enum など)は str に変換する。"""
        record = TenantRecord.from_mapping({"tenant_id": uuid.uuid4(), "tenant_code": "a", "realm_name": "r", "status": TenantStatus.ACTIVE})
        check.equal(record.status, "ACTIVE")
        check.is_instance(record.status, str)

    @pytest.mark.parametrize("missing", ["tenant_id", "tenant_code", "realm_name", "status"])
    def test_from_mapping_missing_column_raises_key_error(self, missing):
        """必要な列が欠けていれば KeyError。"""
        row = {"tenant_id": uuid.uuid4(), "tenant_code": "a", "realm_name": "r", "status": "ACTIVE"}
        del row[missing]
        with pytest.raises(KeyError):
            TenantRecord.from_mapping(row)

    def test_from_mapping_invalid_uuid_raises_value_error(self):
        """tenant_id が UUID として解釈できなければ ValueError。"""
        with pytest.raises(ValueError):
            TenantRecord.from_mapping({"tenant_id": "not-a-uuid", "tenant_code": "a", "realm_name": "r", "status": "ACTIVE"})


class TestIsActive:
    """is_active の判定。"""

    def test_active_is_true(self):
        """ACTIVE のみ True(str でも StrEnum でも)。"""
        check.is_true(is_active(_record(status="ACTIVE")))
        check.is_true(is_active(_record(status=TenantStatus.ACTIVE)))

    def test_none_is_false(self):
        """未登録(None)は False。"""
        check.is_false(is_active(None))

    @pytest.mark.parametrize("status", [s.value for s in TenantStatus if s is not TenantStatus.ACTIVE] + ["UNKNOWN", "active", ""])
    def test_non_active_and_unknown_are_false(self, status):
        """ACTIVE 以外・未知・小文字の状態はすべて False。"""
        check.is_false(is_active(_record(status=status)))


class TestCachedTenantRegistry:
    """TTL キャッシュの振る舞い(時計を注入して時間依存を排除)。"""

    def _make(self, records=None, **kwargs):
        clock = FakeClock()
        inner = CountingRegistry(records)
        return CachedTenantRegistry(inner, clock=clock, **kwargs), inner, clock

    def test_defaults(self):
        """既定の TTL は 30 秒。"""
        check.equal(DEFAULT_CACHE_TTL_SECONDS, 30.0)
        check.equal(DEFAULT_CACHE_MAX_ENTRIES, 1024)
        check.equal(CachedTenantRegistry(CountingRegistry()).ttl_seconds, 30.0)

    def test_hit_within_ttl_queries_once(self):
        """TTL 内の 2 回目はキャッシュから返し、内側へは 1 回だけ問い合わせる。"""
        record = _record()
        registry, inner, clock = self._make([record], ttl_seconds=10)
        check.equal(registry.get_by_code("alpha"), record)
        clock.advance(9.9)
        check.equal(registry.get_by_code("alpha"), record)
        check.equal(len(inner.calls), 1)

    def test_expires_exactly_at_ttl(self):
        """有効期限ちょうどで失効し、再問い合わせする(境界は失効側)。"""
        record = _record()
        registry, inner, clock = self._make([record], ttl_seconds=10)
        registry.get_by_code("alpha")
        clock.advance(10)
        registry.get_by_code("alpha")
        check.equal(len(inner.calls), 2)

    def test_reflects_status_change_after_ttl(self):
        """TTL が過ぎると停止(状態変更)が反映される。"""
        record = _record(status="ACTIVE")
        registry, inner, clock = self._make([record], ttl_seconds=30)
        check.is_true(is_active(registry.get_by_realm(record.realm_name)))
        inner.records = [TenantRecord(record.tenant_id, record.tenant_code, record.realm_name, "SUSPENDED")]
        check.is_true(is_active(registry.get_by_realm(record.realm_name)), "TTL 内は古い値")
        clock.advance(30)
        check.is_false(is_active(registry.get_by_realm(record.realm_name)), "TTL 後は新しい値")

    def test_none_result_is_cached(self):
        """未登録(None)の結果もキャッシュする。TTL 後に登録されていれば見つかる。"""
        registry, inner, clock = self._make([], ttl_seconds=10)
        check.is_none(registry.get_by_code("late"))
        late = _record("late")
        inner.records.append(late)
        check.is_none(registry.get_by_code("late"), "TTL 内は None のまま")
        check.equal(len(inner.calls), 1)
        clock.advance(10)
        check.equal(registry.get_by_code("late"), late)

    def test_invalidate_clears_all(self):
        """invalidate で全エントリを破棄し、次回は再問い合わせする。"""
        record = _record()
        registry, inner, _ = self._make([record], ttl_seconds=10)
        registry.get_by_code("alpha")
        registry.get_by_id(record.tenant_id)
        registry.invalidate()
        registry.get_by_code("alpha")
        registry.get_by_id(record.tenant_id)
        check.equal(len(inner.calls), 4)

    def test_lookup_kinds_are_cached_separately(self):
        """code / realm / id は同じ文字列でも別キーとして扱う。"""
        record = _record("alpha")
        registry, inner, _ = self._make([record], ttl_seconds=10)
        registry.get_by_code("alpha")
        registry.get_by_realm("tenant-alpha")
        registry.get_by_id(record.tenant_id)
        registry.get_by_code("tenant-alpha")  # 同じ文字列でも code 検索は別キー
        check.equal([kind for kind, _ in inner.calls], ["code", "realm", "id", "code"])

    def test_different_keys_do_not_share_results(self):
        """キーごとに結果を分ける(alpha の結果を beta に返さない)。"""
        alpha, beta = _record("alpha"), _record("beta")
        registry, _, _ = self._make([alpha, beta], ttl_seconds=10)
        check.equal(registry.get_by_code("alpha"), alpha)
        check.equal(registry.get_by_code("beta"), beta)
        check.is_none(registry.get_by_code("gamma"))

    def test_loader_exception_propagates_and_is_not_cached(self):
        """内側が例外を出したらそのまま伝播し、失敗をキャッシュしない。"""
        record = _record()
        registry, inner, _ = self._make([record], ttl_seconds=10)
        inner.error = ConnectionError("db down")
        with pytest.raises(ConnectionError):
            registry.get_by_code("alpha")
        inner.error = None
        check.equal(registry.get_by_code("alpha"), record)

    def test_max_entries_evicts_oldest(self):
        """上限を超えると挿入順で古いものから破棄する(参照しても順序は更新されない)。"""
        records = [_record(c) for c in ("a", "b", "c")]
        registry, inner, _ = self._make(records, ttl_seconds=100, max_entries=2)
        registry.get_by_code("a")
        registry.get_by_code("b")
        registry.get_by_code("a")  # ヒット(順序は更新されない)
        registry.get_by_code("c")  # a を破棄
        inner.calls.clear()
        registry.get_by_code("b")
        check.equal(inner.calls, [], "b は残っている")
        registry.get_by_code("a")
        check.equal(inner.calls, [("code", "a")], "a は破棄されて再問い合わせ")

    def test_max_entries_one(self):
        """上限 1 でも動作し、常に最後の 1 件だけを保持する。"""
        registry, inner, _ = self._make([_record("a"), _record("b")], ttl_seconds=100, max_entries=1)
        registry.get_by_code("a")
        registry.get_by_code("b")
        inner.calls.clear()
        registry.get_by_code("b")
        check.equal(inner.calls, [])
        registry.get_by_code("a")
        check.equal(len(inner.calls), 1)

    def test_expired_entries_are_swept_before_eviction(self):
        """上限到達時はまず期限切れを掃除するため、有効なエントリは破棄されない。"""
        registry, inner, clock = self._make([_record("a"), _record("b"), _record("c")], ttl_seconds=10, max_entries=2)
        registry.get_by_code("a")
        clock.advance(6)
        registry.get_by_code("b")
        clock.advance(5)  # a は失効、b は有効
        registry.get_by_code("c")
        inner.calls.clear()
        registry.get_by_code("b")
        registry.get_by_code("c")
        check.equal(inner.calls, [], "有効な b と c は残る")

    def test_unknown_keys_do_not_grow_beyond_limit(self):
        """未登録キーを大量に問い合わせてもエントリ数が上限を超えない(メモリ増加防止)。"""
        registry, inner, _ = self._make([], ttl_seconds=100, max_entries=5)
        for index in range(50):
            registry.get_by_code(f"unknown-{index}")
        inner.calls.clear()
        registry.get_by_code("unknown-49")
        check.equal(inner.calls, [], "直近のキーは残る")
        registry.get_by_code("unknown-0")
        check.equal(len(inner.calls), 1, "古いキーは破棄済み")

    @pytest.mark.parametrize("ttl", [0, -1, -0.5])
    def test_invalid_ttl_raises(self, ttl):
        """ttl_seconds が 0 以下なら ValueError。"""
        with pytest.raises(ValueError, match="ttl_seconds"):
            CachedTenantRegistry(CountingRegistry(), ttl_seconds=ttl)

    @pytest.mark.parametrize("max_entries", [0, -1])
    def test_invalid_max_entries_raises(self, max_entries):
        """max_entries が 0 以下なら ValueError。"""
        with pytest.raises(ValueError, match="max_entries"):
            CachedTenantRegistry(CountingRegistry(), max_entries=max_entries)

    def test_thread_safety_smoke(self):
        """多数のスレッドから同時に使っても例外が出ず、結果が正しい。"""
        records = [_record(f"t{i}") for i in range(20)]
        registry = CachedTenantRegistry(CountingRegistry(records), ttl_seconds=100, max_entries=8)
        barrier = threading.Barrier(8)

        def work(worker: int) -> list[bool]:
            barrier.wait(timeout=10)
            return [registry.get_by_code(f"t{(worker + n) % 20}") == records[(worker + n) % 20] for n in range(200)]

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(work, range(8)))
        check.is_true(all(all(r) for r in results))


class TestSqlTenantRegistryViewName:
    """SqlTenantRegistry の view_name 検証(SQL インジェクション防止)。DB には接続しない。"""

    @pytest.mark.parametrize("view_name", ["v_tenant_registry", "_v", "control_plane.v_tenant_registry", "S1.V2"])
    def test_valid_view_names(self, view_name):
        """view / schema.view 形式の識別子は受け付ける。"""
        SqlTenantRegistry(engine=object(), view_name=view_name)  # type: ignore[arg-type]

    def test_default_view_name(self):
        """既定のビュー名は v_tenant_registry。"""
        registry = SqlTenantRegistry(engine=object())  # type: ignore[arg-type]
        check.is_in("v_tenant_registry", str(registry._by_code_sql))

    @pytest.mark.parametrize(
        "view_name",
        ["", "1view", "a.b.c", "a-b", "a b", "v; DROP TABLE x", "v--", 'v"x"', ".v", "v.", "public.", "v) UNION SELECT 1 --", "あ",
         "v\n",
         ],
    )
    def test_invalid_view_names_raise(self, view_name):
        """不正な識別子は ValueError。"""
        with pytest.raises(ValueError, match="view_name"):
            SqlTenantRegistry(engine=object(), view_name=view_name)  # type: ignore[arg-type]
