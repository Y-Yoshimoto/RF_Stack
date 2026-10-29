# -*- coding: utf-8 -*-
"""API テスト用の Redis 代替(セッション・レート制限・ヘルスチェックが使うコマンドだけ)。有効期限は進められる時計で扱う。"""
import math
import time
from collections.abc import Callable
from typing import Any

import redis.exceptions


class FakePipeline:
    """``pipeline(transaction=True)`` の代替。コマンドを溜めて ``execute`` でまとめて実行する。"""

    def __init__(self, redis: "FakeRedis") -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Callable[..., "FakePipeline"]:
        def add(*args: Any, **kwargs: Any) -> "FakePipeline":
            self._ops.append((name, args, kwargs))
            return self

        return add

    def execute(self) -> list[Any]:
        return [getattr(self._redis, name)(*args, **kwargs) for name, args, kwargs in self._ops]


class FakeRedis:
    """インメモリの Redis 代替。``clock`` を進めると有効期限が切れる。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.data: dict[str, str] = {}
        self.expires: dict[str, float] = {}

    def _alive(self, key: str) -> bool:
        deadline = self.expires.get(key)
        if deadline is not None and deadline <= self.clock():
            self.data.pop(key, None)
            self.expires.pop(key, None)
        return key in self.data

    def set(self, name: str, value: Any, ex: int | None = None, nx: bool = False) -> bool | None:
        if nx and self._alive(name):
            return None
        self.data[name] = str(value)
        if ex is not None:
            self.expires[name] = self.clock() + ex
        else:
            self.expires.pop(name, None)
        return True

    def setex(self, key: str, ttl: int, value: str) -> bool:
        return bool(self.set(key, value, ex=ttl))

    def get(self, key: str) -> str | None:
        return self.data[key] if self._alive(key) else None

    def getdel(self, key: str) -> str | None:
        value = self.get(key)
        self.delete(key)
        return value

    def delete(self, key: str) -> int:
        existed = self._alive(key)
        self.data.pop(key, None)
        self.expires.pop(key, None)
        return int(existed)

    def incr(self, key: str) -> int:
        value = int(self.data[key] if self._alive(key) else 0) + 1
        self.data[key] = str(value)
        return value

    def ttl(self, key: str) -> int:
        if not self._alive(key):
            return -2
        deadline = self.expires.get(key)
        return -1 if deadline is None else max(math.ceil(deadline - self.clock()), 0)

    def ping(self) -> bool:
        return True

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        return FakePipeline(self)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(key for key in list(self.data) if key.startswith(prefix) and self._alive(key))


class DownRedis:
    """接続できない Redis(あらゆる操作が ``ConnectionError``)。"""

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def fail(*args: Any, **kwargs: Any) -> Any:
            raise redis.exceptions.ConnectionError("redis is down (test)")

        return fail
