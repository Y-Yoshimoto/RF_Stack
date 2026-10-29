# -*- coding: utf-8 -*-
"""modules.tenancy.context のユニットテスト(DB 不要)。"""
import asyncio
import contextvars
import dataclasses
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import pytest_check as check

from modules.tenancy.context import (
    TenantContext,
    TenantContextMissingError,
    get_tenant_context,
    require_tenant_context,
    reset_tenant_context,
    set_tenant_context,
    tenant_scope,
)


def _ctx(code: str = "alpha") -> TenantContext:
    """テスト用のコンテキストを作る。"""
    return TenantContext(tenant_id=uuid.uuid4(), tenant_code=code)


class TestTenantContextValidation:
    """TenantContext の生成時検証。"""

    def test_defaults(self):
        """user_id は None、plane は app が既定値になる。"""
        tenant_id = uuid.uuid4()
        ctx = TenantContext(tenant_id=tenant_id, tenant_code="alpha")
        check.equal(ctx.tenant_id, tenant_id)
        check.equal(ctx.tenant_code, "alpha")
        check.is_none(ctx.user_id)
        check.equal(ctx.plane, "app")

    def test_accepts_user_id_and_cp_plane(self):
        """user_id(UUID)と plane=cp を指定できる。"""
        user_id = uuid.uuid4()
        ctx = TenantContext(tenant_id=uuid.uuid4(), tenant_code="alpha", user_id=user_id, plane="cp")
        check.equal(ctx.user_id, user_id)
        check.equal(ctx.plane, "cp")

    @pytest.mark.parametrize("bad_tenant_id", ["8d2f2d54-0000-7000-8000-000000000000", 1, None, b"x"])
    def test_tenant_id_must_be_uuid(self, bad_tenant_id):
        """tenant_id が UUID 以外(文字列を含む)なら TypeError。"""
        with pytest.raises(TypeError, match="tenant_id"):
            TenantContext(tenant_id=bad_tenant_id, tenant_code="alpha")

    @pytest.mark.parametrize("bad_user_id", ["8d2f2d54-0000-7000-8000-000000000000", 1])
    def test_user_id_must_be_uuid_or_none(self, bad_user_id):
        """user_id が UUID でも None でもなければ TypeError。"""
        with pytest.raises(TypeError, match="user_id"):
            TenantContext(tenant_id=uuid.uuid4(), tenant_code="alpha", user_id=bad_user_id)

    def test_tenant_code_must_not_be_empty(self):
        """tenant_code が空なら ValueError。"""
        with pytest.raises(ValueError, match="tenant_code"):
            TenantContext(tenant_id=uuid.uuid4(), tenant_code="")

    @pytest.mark.parametrize("bad_plane", ["", "APP", "admin", None])
    def test_plane_must_be_known(self, bad_plane):
        """plane が app / cp 以外なら ValueError。"""
        with pytest.raises(ValueError, match="plane"):
            TenantContext(tenant_id=uuid.uuid4(), tenant_code="alpha", plane=bad_plane)

    def test_is_immutable_and_hashable(self):
        """不変(代入で FrozenInstanceError)で、等価なものは同値・同ハッシュ。"""
        tenant_id = uuid.uuid4()
        ctx = TenantContext(tenant_id=tenant_id, tenant_code="alpha")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.tenant_code = "beta"  # type: ignore[misc]
        same = TenantContext(tenant_id=tenant_id, tenant_code="alpha")
        check.equal(ctx, same)
        check.equal(hash(ctx), hash(same))


class TestAccessors:
    """get / require / set / reset。"""

    def test_get_returns_none_when_unset(self):
        """未設定なら get は None。"""
        check.is_none(get_tenant_context())

    def test_require_raises_when_unset(self):
        """未設定なら require は TenantContextMissingError(RuntimeError のサブクラス)。"""
        with pytest.raises(TenantContextMissingError):
            require_tenant_context()
        check.is_true(issubclass(TenantContextMissingError, RuntimeError))

    def test_require_returns_context_when_set(self):
        """設定済みなら require は同じオブジェクトを返す。"""
        ctx = _ctx()
        with tenant_scope(ctx):
            check.is_(require_tenant_context(), ctx)
            check.is_(get_tenant_context(), ctx)

    def test_low_level_set_and_reset_restores_previous(self):
        """set が返した Token で reset すると直前の値に戻る。"""
        outer, inner = _ctx("outer"), _ctx("inner")
        outer_token = set_tenant_context(outer)
        try:
            inner_token = set_tenant_context(inner)
            check.is_(get_tenant_context(), inner)
            reset_tenant_context(inner_token)
            check.is_(get_tenant_context(), outer)
        finally:
            reset_tenant_context(outer_token)
        check.is_none(get_tenant_context())

    def test_reset_twice_raises(self):
        """同じ Token で 2 回 reset すると RuntimeError(ContextVar の仕様)。"""
        token = set_tenant_context(_ctx())
        reset_tenant_context(token)
        with pytest.raises(RuntimeError):
            reset_tenant_context(token)

    def test_reset_in_other_context_raises(self):
        """別の Context で作った Token を reset すると ValueError。"""
        other = contextvars.copy_context()
        token = other.run(set_tenant_context, _ctx())
        with pytest.raises(ValueError):
            reset_tenant_context(token)


class TestTenantScope:
    """tenant_scope の設定と復元。"""

    def test_sets_inside_and_restores_after(self):
        """ブロック内だけ設定され、抜けると None に戻る。yield 値は渡したコンテキスト。"""
        ctx = _ctx()
        with tenant_scope(ctx) as yielded:
            check.is_(yielded, ctx)
            check.is_(get_tenant_context(), ctx)
        check.is_none(get_tenant_context())

    def test_restores_on_exception(self):
        """例外が発生しても元に戻り、例外はそのまま伝播する。"""
        with pytest.raises(RuntimeError, match="boom"):
            with tenant_scope(_ctx()):
                raise RuntimeError("boom")
        check.is_none(get_tenant_context())

    def test_nested_restores_outer(self):
        """入れ子の内側を抜けると外側のコンテキストに戻る。"""
        outer, inner = _ctx("outer"), _ctx("inner")
        with tenant_scope(outer):
            with tenant_scope(inner):
                check.is_(get_tenant_context(), inner)
            check.is_(get_tenant_context(), outer)
        check.is_none(get_tenant_context())

    def test_nested_restores_outer_on_inner_exception(self):
        """内側で例外が出ても外側のコンテキストに戻る。"""
        outer = _ctx("outer")
        with tenant_scope(outer):
            with pytest.raises(ValueError):
                with tenant_scope(_ctx("inner")):
                    raise ValueError("inner")
            check.is_(get_tenant_context(), outer)

    def test_none_scope_clears_inside(self):
        """None を渡すとブロック内だけテナントなしになり、抜けると外側に戻る。"""
        outer = _ctx("outer")
        with tenant_scope(outer):
            with tenant_scope(None) as yielded:
                check.is_none(yielded)
                check.is_none(get_tenant_context())
                with pytest.raises(TenantContextMissingError):
                    require_tenant_context()
            check.is_(get_tenant_context(), outer)


class TestIsolationBetweenExecutionContexts:
    """スレッド・asyncio タスク間でテナントが漏れない。"""

    def test_new_thread_does_not_inherit(self):
        """新しいスレッドは親スレッドのコンテキストを引き継がない。"""
        seen: list = []
        with tenant_scope(_ctx()):
            thread = threading.Thread(target=lambda: seen.append(get_tenant_context()))
            thread.start()
            thread.join()
        check.equal(seen, [None])

    def test_threads_keep_their_own_tenant(self):
        """並行スレッドが互いに別のテナントを保持し続ける(バリアで必ず同時に設定済みにする)。"""
        workers = 8
        barrier = threading.Barrier(workers)

        def work(index: int) -> tuple[str, str | None]:
            ctx = _ctx(f"tenant-{index}")
            with tenant_scope(ctx):
                barrier.wait(timeout=10)  # 全スレッドが設定済みの状態を作る
                current = get_tenant_context()
                barrier.wait(timeout=10)
                return ctx.tenant_code, current.tenant_code if current else None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(work, range(workers)))
        for expected, actual in results:
            check.equal(actual, expected)
        check.is_none(get_tenant_context())

    @pytest.mark.asyncio
    async def test_asyncio_tasks_keep_their_own_tenant(self):
        """並行 asyncio タスクが await を挟んでも互いに別のテナントを保持する。"""
        tasks = 6
        gate = asyncio.Event()
        ready = 0

        async def work(index: int) -> tuple[str, str | None]:
            nonlocal ready
            ctx = _ctx(f"tenant-{index}")
            with tenant_scope(ctx):
                ready += 1
                if ready == tasks:
                    gate.set()
                await gate.wait()  # 全タスクが設定済みの状態で切り替わる
                await asyncio.sleep(0)
                current = get_tenant_context()
                return ctx.tenant_code, current.tenant_code if current else None

        results = await asyncio.gather(*(work(i) for i in range(tasks)))
        for expected, actual in results:
            check.equal(actual, expected)
        check.is_none(get_tenant_context())

    @pytest.mark.asyncio
    async def test_task_scope_does_not_leak_to_parent(self):
        """子タスクの tenant_scope は親(呼び出し元)のコンテキストに影響しない。"""

        async def child() -> None:
            with tenant_scope(_ctx()):
                await asyncio.sleep(0)

        await asyncio.create_task(child())
        check.is_none(get_tenant_context())

    @pytest.mark.asyncio
    async def test_child_task_inherits_snapshot_at_creation(self):
        """子タスクは生成時点のコンテキストを引き継ぎ、親の以降の変更は見えない。"""
        parent = _ctx("parent")
        seen: list = []
        proceed = asyncio.Event()

        async def child() -> None:
            await proceed.wait()
            seen.append(get_tenant_context())

        with tenant_scope(parent):
            task = asyncio.create_task(child())
        proceed.set()  # 親のスコープを抜けた後で子を進める
        await task
        check.equal(seen, [parent])
