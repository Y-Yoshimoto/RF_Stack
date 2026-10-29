#!/usr/bin/env python
# coding:utf-8
"""テナント毎の指標セットの定義と検証（01 §6.4、§13 #5）。

指標は「指標キー（``t_tenant_daily_metric.metric_key``）」と「集計関数」の組で定義する。
1 回のクエリで複数の指標を求められるよう、集計関数は複数のキーの値をまとめて返す（:class:`TenantMetricSet`）。

集計関数の約束:
    - ``(session, tenant_id) -> {metric_key: 値}`` の形で、``keys`` のすべてのキーを返す（0 件でも 0 を返す）
    - ``session`` は ``app_db`` に ``app_cp_agent``（SELECT / DELETE のみ、RLS 適用）で接続し、
      GUC ``app.current_tenant`` を ``tenant_id`` に設定済みの読み取り用トランザクション。書き込まないこと
    - RLS によりそのテナントの行しか見えないが、多重防御として ``tenant_id`` の条件も付ける
    - 値は整数または ``Decimal``（``t_tenant_daily_metric.value`` は ``numeric``。浮動小数点は使わない）
    - 現在の状態だけから求める（同じ状態なら何度呼んでも同じ値。日次スナップショットの冪等性の前提）
"""
import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

# 集計関数が返す値の型
type MetricValue = int | Decimal

# 指標キーの形式（snake_case。``metric_key`` 列と API のキーにそのまま使う）
METRIC_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,62}")


@dataclass(frozen=True, kw_only=True)
class TenantMetricSet:
    """1 つの集計関数で求める指標の組。

    Attributes:
        name: 指標セットの名前（ログ・エラーの表示用。例: ``users``、``todo``）。
        keys: 集計関数が返す指標キー。
        collect: ``(session, tenant_id) -> {metric_key: 値}``。約束はモジュールの説明を参照。
        primary_keys: ``keys`` のうち、CP のテナント一覧に出す主要指標（01 §13 #5）。
    """

    name: str
    keys: tuple[str, ...]
    collect: Callable[[Session, uuid.UUID], Mapping[str, MetricValue]]
    primary_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """キーの形式と重複、主要指標が ``keys`` に含まれることを検証する。"""
        if not self.keys:
            raise ValueError(f"metric set {self.name!r} has no keys")
        invalid = [key for key in self.keys if not METRIC_KEY_PATTERN.fullmatch(key)]
        if invalid:
            raise ValueError(f"metric set {self.name!r} has invalid metric keys: {invalid}")
        if len(set(self.keys)) != len(self.keys):
            raise ValueError(f"metric set {self.name!r} has duplicate metric keys")
        unknown = [key for key in self.primary_keys if key not in self.keys]
        if unknown:
            raise ValueError(f"metric set {self.name!r} has primary keys not in keys: {unknown}")

    def collect_values(self, session: Session, tenant_id: uuid.UUID) -> dict[str, Decimal]:
        """集計関数を呼び、戻り値を検証して ``Decimal`` に揃える。

        Args:
            session: GUC を ``tenant_id`` に設定済みの ``app_db`` のセッション。
            tenant_id: テナント ID。

        Returns:
            dict[str, Decimal]: 指標キーごとの値（``keys`` の順）。

        Raises:
            ValueError: 返したキーが ``keys`` と一致しない、または値の型が不正な場合。
        """
        values = self.collect(session, tenant_id)
        if set(values) != set(self.keys):
            raise ValueError(f"metric set {self.name!r} returned keys {sorted(values)}, expected {sorted(self.keys)}")
        result: dict[str, Decimal] = {}
        for key in self.keys:
            value = values[key]
            # bool は int のサブクラスだが指標の値としては誤りのため拒否する。float は誤差を持ち込むため拒否する
            if isinstance(value, bool) or not isinstance(value, int | Decimal):
                raise ValueError(f"metric {key!r} of set {self.name!r} must be int or Decimal, got {type(value).__name__}")
            result[key] = Decimal(value)
        return result


def validate_metric_sets(metric_sets: Iterable[TenantMetricSet]) -> tuple[TenantMetricSet, ...]:
    """指標セットの組を検証する（指標キーとセット名がセット間で重複しないこと）。

    Args:
        metric_sets: 指標セット。

    Returns:
        tuple[TenantMetricSet, ...]: 検証済みの指標セット（入力の順）。

    Raises:
        ValueError: 指標キーまたはセット名が重複する場合。
    """
    sets = tuple(metric_sets)
    owners: dict[str, str] = {}
    names: set[str] = set()
    for metric_set in sets:
        if metric_set.name in names:
            raise ValueError(f"duplicate metric set name: {metric_set.name!r}")
        names.add(metric_set.name)
        for key in metric_set.keys:
            if key in owners:
                raise ValueError(f"metric key {key!r} is defined by both {owners[key]!r} and {metric_set.name!r}")
            owners[key] = metric_set.name
    return sets
