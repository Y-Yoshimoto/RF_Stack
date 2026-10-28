# -*- coding: utf-8 -*-
"""modules.tenant_metrics.definition(指標セットの定義と検証。01 §13 #5)のテスト。DB には接続しない。"""
from decimal import Decimal

import pytest
import pytest_check as check

from modules.tenant_metrics.definition import METRIC_KEY_PATTERN, TenantMetricSet, validate_metric_sets


def make_set(name="s", keys=("a_count", "b_count"), result=None, **kwargs):
    """集計関数が ``result``(省略時は全キーが 1)を返す指標セット。"""
    return TenantMetricSet(name=name, keys=tuple(keys), collect=lambda session, tenant_id: dict(result) if result is not None else {key: 1 for key in keys}, **kwargs)


class TestConstruction:
    """指標セットの生成時の検証。"""

    def test_valid_set(self):
        """キーが snake_case で重複せず、主要指標がキーに含まれていれば作れる(主要指標は省略できる)。"""
        metric_set = make_set(primary_keys=("a_count",))
        check.equal((metric_set.keys, metric_set.primary_keys), (("a_count", "b_count"), ("a_count",)))
        check.equal(make_set().primary_keys, ())

    def test_no_keys(self):
        """キーが空なら ValueError。"""
        with pytest.raises(ValueError, match="no keys"):
            make_set(keys=())

    @pytest.mark.parametrize("key", ["", "A", "Count", "1count", "_count", "todo-count", "todo count", "todo.count", "件数", "a" * 64])
    def test_invalid_key_format(self, key):
        """大文字・数字や記号の先頭・ハイフン・空白・日本語・64 文字以上のキーは ValueError。"""
        with pytest.raises(ValueError, match="invalid metric keys"):
            make_set(keys=(key,))

    @pytest.mark.parametrize("key", ["a", "todo_count", "x1_2_3", "a" * 63])
    def test_valid_key_format(self, key):
        """英小文字で始まる、英小文字・数字・アンダースコアの 63 文字以内のキーは作れる。"""
        check.is_not_none(METRIC_KEY_PATTERN.fullmatch(key))
        make_set(keys=(key,))

    def test_duplicate_keys(self):
        """同じキーを 2 回含むと ValueError。"""
        with pytest.raises(ValueError, match="duplicate metric keys"):
            make_set(keys=("a_count", "a_count"))

    def test_primary_key_must_be_in_keys(self):
        """主要指標が keys に無ければ ValueError。"""
        with pytest.raises(ValueError, match="primary keys not in keys"):
            make_set(primary_keys=("other_count",))

    def test_is_frozen(self):
        """指標セットは不変。"""
        metric_set = make_set()
        with pytest.raises(AttributeError):
            metric_set.name = "changed"


class TestCollectValues:
    """集計関数の戻り値の検証と Decimal への変換。"""

    def test_returns_decimals_in_key_order(self):
        """int / Decimal を Decimal に揃え、キーの順で返す。"""
        metric_set = make_set(keys=("b_count", "a_count"), result={"a_count": 2, "b_count": Decimal("3.50")})
        values = metric_set.collect_values(None, None)
        check.equal(list(values), ["b_count", "a_count"])
        check.equal(values, {"b_count": Decimal("3.50"), "a_count": Decimal(2)})
        check.is_true(all(isinstance(v, Decimal) for v in values.values()))

    def test_session_and_tenant_are_passed_through(self):
        """集計関数にセッションとテナント ID をそのまま渡す。"""
        seen = []
        metric_set = TenantMetricSet(name="s", keys=("a_count",), collect=lambda session, tenant_id: seen.append((session, tenant_id)) or {"a_count": 0})
        metric_set.collect_values("SESSION", "TENANT")
        check.equal(seen, [("SESSION", "TENANT")])

    @pytest.mark.parametrize("value", [1.5, 1.0, "3", None, True, False, [1], {"a": 1}])
    def test_rejects_non_integer_non_decimal(self, value):
        """float(誤差を持ち込む)・文字列・None・bool など、int / Decimal 以外は ValueError。"""
        metric_set = make_set(keys=("a_count",), result={"a_count": value})
        with pytest.raises(ValueError, match="must be int or Decimal"):
            metric_set.collect_values(None, None)

    def test_rejects_missing_key(self):
        """宣言したキーが足りなければ ValueError。"""
        metric_set = make_set(result={"a_count": 1})
        with pytest.raises(ValueError, match="returned keys"):
            metric_set.collect_values(None, None)

    def test_rejects_extra_key(self):
        """宣言していないキーを返したら ValueError。"""
        metric_set = make_set(result={"a_count": 1, "b_count": 2, "c_count": 3})
        with pytest.raises(ValueError, match="returned keys"):
            metric_set.collect_values(None, None)

    def test_zero_is_valid(self):
        """0 は有効な値。"""
        check.equal(make_set(result={"a_count": 0, "b_count": 0}).collect_values(None, None), {"a_count": Decimal(0), "b_count": Decimal(0)})


class TestValidateMetricSets:
    """指標セット間の重複の検証。"""

    def test_returns_tuple_in_input_order(self):
        """検証済みのタプルを入力の順で返す。ジェネレーターも受け取れる。"""
        first, second = make_set(name="one", keys=("a_count",)), make_set(name="two", keys=("b_count",))
        check.equal(validate_metric_sets(s for s in (second, first)), (second, first))
        check.equal(validate_metric_sets([]), ())

    def test_duplicate_key_across_sets(self):
        """セットをまたいで同じキーがあれば ValueError(どのセットが定義しているかをメッセージに含める)。"""
        with pytest.raises(ValueError, match=r"'x_count' is defined by both 'one' and 'two'"):
            validate_metric_sets([make_set(name="one", keys=("x_count",)), make_set(name="two", keys=("x_count",))])

    def test_duplicate_set_name(self):
        """同じ名前のセットが 2 つあれば ValueError。"""
        with pytest.raises(ValueError, match="duplicate metric set name"):
            validate_metric_sets([make_set(name="same", keys=("a_count",)), make_set(name="same", keys=("b_count",))])
