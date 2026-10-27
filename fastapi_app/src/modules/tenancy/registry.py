#!/usr/bin/env python
# coding:utf-8
"""有効テナント一覧（テナントレジストリ）の読み取りインターフェース。

アプリケーションプレーン(AP)はテナントの登録情報を、コントロールプレーン DB のビュー
``v_tenant_registry``（tenant_id, tenant_code, realm_name, status）からのみ読む。
これが AP からコントロールプレーンへの **唯一の依存口** であり、読み取り専用とする。

提供する機能:
    - :class:`TenantRecord` — レジストリの 1 行を表す不変オブジェクト。
    - :class:`TenantStatus` / :func:`is_active` — テナント状態と ACTIVE 判定。
    - :class:`TenantRegistry` — レジストリの読み取りインターフェース（Protocol）。
    - :class:`CachedTenantRegistry` — TTL 付きインメモリキャッシュのラッパー。
    - :class:`SqlTenantRegistry` — ``v_tenant_registry`` を SQL で読む実装。

依存関係:
    ``SqlTenantRegistry`` のみ SQLAlchemy に依存する。それ以外はフレームワーク・
    DB ライブラリに依存しないため、テストではインメモリのフェイク実装に差し替えられる。
"""
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import Engine, text

# レジストリのキャッシュ TTL の既定値（秒）。
# テナントの停止(SUSPENDED)や削除要求は、最大でこの秒数だけ遅れて AP に反映される。
DEFAULT_CACHE_TTL_SECONDS = 30.0

# キャッシュに保持するエントリ数の上限の既定値。
# 未登録キー（存在しない tenant_code 等）の問い合わせでメモリが増え続けないようにする。
DEFAULT_CACHE_MAX_ENTRIES = 1024

# レジストリビュー名の既定値と、許可する識別子の形式（"view" または "schema.view"）。
DEFAULT_REGISTRY_VIEW = "v_tenant_registry"
# fullmatch で使う（"$" は末尾の改行 1 つを許してしまうため、アンカーには頼らない）。
_SQL_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?")


class TenantStatus(StrEnum):
    """テナントのライフサイクル状態（コントロールプレーンの ``tenants.status`` と一致させる）。"""

    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    SUSPENDED = "SUSPENDED"
    PENDING_DELETION = "PENDING_DELETION"
    DEPROVISIONING = "DEPROVISIONING"
    DELETED = "DELETED"


@dataclass(frozen=True, slots=True)
class TenantRecord:
    """テナントレジストリの 1 行。

    ``status`` は未知の値が来ても読み込めるよう ``str`` のまま保持する。
    判定には :func:`is_active` を使い、未知の値は非 ACTIVE として扱う。

    Attributes:
        tenant_id: テナント ID。
        tenant_code: テナントコード（URL・レルム名に使う英小文字の識別子）。
        realm_name: Keycloak のレルム名（``tenant-{tenant_code}``）。
        status: テナントの状態（:class:`TenantStatus` の値）。
    """

    tenant_id: uuid.UUID
    tenant_code: str
    realm_name: str
    status: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> TenantRecord:
        """DB の行（列名 → 値）から生成する。

        psycopg2 はドライバ設定によって uuid 列を ``str`` で返すため、
        ``tenant_id`` は ``uuid.UUID`` に正規化する。

        Args:
            row: ``tenant_id``, ``tenant_code``, ``realm_name``, ``status`` を持つマッピング。

        Returns:
            TenantRecord: 生成したレコード。

        Raises:
            KeyError: 必要な列が欠けている場合。
            ValueError: ``tenant_id`` が UUID として解釈できない場合。
        """
        raw_id = row["tenant_id"]
        tenant_id = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
        return cls(tenant_id=tenant_id, tenant_code=str(row["tenant_code"]), realm_name=str(row["realm_name"]), status=str(row["status"]))


def is_active(record: TenantRecord | None) -> bool:
    """テナントが利用可能（ACTIVE）かどうかを判定する。

    Args:
        record: 判定対象。未登録を表す ``None`` も受け付ける。

    Returns:
        bool: ``status`` が ``ACTIVE`` の場合のみ ``True``。``None`` や未知の状態は ``False``。
    """
    return record is not None and record.status == TenantStatus.ACTIVE


class TenantRegistry(Protocol):
    """テナントレジストリの読み取りインターフェース。

    いずれのメソッドも、該当テナントが存在しない場合は ``None`` を返す
    （状態による絞り込みは行わず、ACTIVE 判定は呼び出し側で :func:`is_active` を使う）。
    """

    def get_by_code(self, tenant_code: str) -> TenantRecord | None:
        """テナントコードで検索する。"""
        ...

    def get_by_realm(self, realm_name: str) -> TenantRecord | None:
        """Keycloak のレルム名で検索する。"""
        ...

    def get_by_id(self, tenant_id: uuid.UUID) -> TenantRecord | None:
        """テナント ID で検索する。"""
        ...


class CachedTenantRegistry:
    """:class:`TenantRegistry` に TTL 付きインメモリキャッシュを被せるラッパー。

    リクエスト毎にコントロールプレーン DB へ問い合わせないためのもの。

    整合性:
        キャッシュは TTL（既定 30 秒）の間保持されるため、テナントの **停止・再開・削除要求は
        最大 TTL 秒だけ遅れて反映される**。未登録（``None``）の結果も同じ TTL でキャッシュする
        ため、新規払い出し直後のテナントも最大 TTL 秒は未登録として扱われうる。
        即時反映が必要な場合は :meth:`invalidate` を呼ぶ（ただしプロセス内のみ）。

    スレッド安全性:
        同期の依存関数はスレッドプールで実行されるため、内部状態はロックで保護する。
        問い合わせ自体はロック外で行うため、同一キーへの同時ミスでは複数回問い合わせが
        発生しうる（結果は同じなので許容する）。

    Args:
        inner: 実際に問い合わせるレジストリ。
        ttl_seconds: キャッシュの有効期間（秒）。0 以下は不可。
        max_entries: 保持するエントリ数の上限。超えた場合は期限切れを掃除し、
            それでも超える場合は古いものから破棄する。
        clock: 現在時刻（秒）を返す関数。既定は ``time.monotonic``。テストで差し替える。

    Raises:
        ValueError: ``ttl_seconds`` または ``max_entries`` が正でない場合。
    """

    def __init__(self, inner: TenantRegistry, ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS, max_entries: int = DEFAULT_CACHE_MAX_ENTRIES, clock: Callable[[], float] = time.monotonic) -> None:
        """キャッシュを初期化する。"""
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._inner = inner
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        # (検索種別, キー) -> (有効期限, 結果)
        self._entries: dict[tuple[str, str], tuple[float, TenantRecord | None]] = {}

    @property
    def ttl_seconds(self) -> float:
        """キャッシュの有効期間（秒）。"""
        return self._ttl_seconds

    def get_by_code(self, tenant_code: str) -> TenantRecord | None:
        """テナントコードで検索する（キャッシュ経由）。"""
        return self._get(("code", tenant_code), lambda: self._inner.get_by_code(tenant_code))

    def get_by_realm(self, realm_name: str) -> TenantRecord | None:
        """レルム名で検索する（キャッシュ経由）。"""
        return self._get(("realm", realm_name), lambda: self._inner.get_by_realm(realm_name))

    def get_by_id(self, tenant_id: uuid.UUID) -> TenantRecord | None:
        """テナント ID で検索する（キャッシュ経由）。"""
        return self._get(("id", str(tenant_id)), lambda: self._inner.get_by_id(tenant_id))

    def invalidate(self) -> None:
        """キャッシュをすべて破棄する。"""
        with self._lock:
            self._entries.clear()

    def _get(self, key: tuple[str, str], loader: Callable[[], TenantRecord | None]) -> TenantRecord | None:
        """キャッシュを引き、無効なら ``loader`` で取得して保存する。

        Args:
            key: ``(検索種別, キー)`` の組。
            loader: キャッシュミス時に呼ぶ問い合わせ関数。

        Returns:
            TenantRecord | None: 検索結果。
        """
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] > now:
                return entry[1]

        record = loader()

        with self._lock:
            self._entries.pop(key, None)
            if len(self._entries) >= self._max_entries:
                self._evict(now)
            self._entries[key] = (now + self._ttl_seconds, record)
        return record

    def _evict(self, now: float) -> None:
        """期限切れを削除し、なお上限以上なら挿入順の古いものから削除する（ロック保持中に呼ぶ）。

        Args:
            now: 現在時刻（秒）。
        """
        expired = [key for key, (expires_at, _) in self._entries.items() if expires_at <= now]
        for key in expired:
            del self._entries[key]
        while len(self._entries) >= self._max_entries:
            del self._entries[next(iter(self._entries))]


class SqlTenantRegistry:
    """コントロールプレーン DB のビュー ``v_tenant_registry`` を読むレジストリ実装。

    ビューは読み取り専用ロールで参照する想定。エンジンは
    :class:`~modules.db_connector.engine.DBConnector` の ``engine`` を渡し、
    本クラスで ``create_engine`` は呼ばない。

    TODO: ``v_tenant_registry`` はまだ作成されていない（postgres-schema 担当）。
        ビュー作成後に列名・スキーマ名（``control_plane.v_tenant_registry`` 等）を確認し、
        結合テストで動作を確認すること。

    Args:
        engine: コントロールプレーン DB のエンジン。
        view_name: 参照するビュー名。``view`` または ``schema.view`` 形式の識別子のみ許可する。

    Raises:
        ValueError: ``view_name`` が識別子として不正な場合（SQL インジェクション防止）。
    """

    def __init__(self, engine: Engine, view_name: str = DEFAULT_REGISTRY_VIEW) -> None:
        """ビュー名を検証し、検索用 SQL を組み立てる。"""
        if not _SQL_IDENTIFIER_PATTERN.fullmatch(view_name):
            raise ValueError("view_name must be an SQL identifier like 'view' or 'schema.view'")
        self._engine = engine
        base = f"SELECT tenant_id, tenant_code, realm_name, status FROM {view_name}"
        self._by_code_sql = text(f"{base} WHERE tenant_code = :value")
        self._by_realm_sql = text(f"{base} WHERE realm_name = :value")
        # psycopg2 は uuid.UUID をそのまま渡せない設定があるため、文字列で渡して SQL 側で変換する
        self._by_id_sql = text(f"{base} WHERE tenant_id = CAST(:value AS uuid)")

    def get_by_code(self, tenant_code: str) -> TenantRecord | None:
        """テナントコードで検索する。"""
        return self._fetch_one(self._by_code_sql, tenant_code)

    def get_by_realm(self, realm_name: str) -> TenantRecord | None:
        """レルム名で検索する。"""
        return self._fetch_one(self._by_realm_sql, realm_name)

    def get_by_id(self, tenant_id: uuid.UUID) -> TenantRecord | None:
        """テナント ID で検索する。"""
        return self._fetch_one(self._by_id_sql, str(tenant_id))

    def _fetch_one(self, statement: Any, value: str) -> TenantRecord | None:
        """1 行を取得して :class:`TenantRecord` に変換する。

        Args:
            statement: 実行する ``text()`` 文。
            value: バインドパラメータ ``:value`` の値。

        Returns:
            TenantRecord | None: 該当行。無ければ ``None``。
        """
        with self._engine.connect() as connection:
            row = connection.execute(statement, {"value": value}).mappings().first()
        if row is None:
            return None
        return TenantRecord.from_mapping(row)
