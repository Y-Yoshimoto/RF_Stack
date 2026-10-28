# -*- coding: utf-8 -*-
"""scheduler.runner.is_scheduler_enabled(スケジューラの有効/無効の判定。02 §5.5)のテスト。DB・外部には接続しない。"""
import pytest
import pytest_check as check

from scheduler.runner import SCHEDULER_ENABLED_ENV, is_scheduler_enabled


@pytest.mark.parametrize("value", ["true", "TRUE", "True", "1", "yes", "YES", "on", "On", "  true  ", "\ton\n"])
def test_truthy_values_enable(value):
    """true / 1 / yes / on(大文字小文字を区別せず、前後の空白を無視)は有効。APP_ENV に関係なく有効にできる。"""
    for app_env in ("development", "production", ""):
        check.is_true(is_scheduler_enabled({SCHEDULER_ENABLED_ENV: value, "APP_ENV": app_env}), f"{value!r} / {app_env!r}")


@pytest.mark.parametrize("value", ["false", "FALSE", "False", "0", "no", "NO", "off", "Off", "  false  "])
def test_falsy_values_disable(value):
    """false / 0 / no / off は無効。本番(APP_ENV=production)でも明示すれば無効にできる(別プロセスに分離する場合)。"""
    for app_env in ("development", "production", ""):
        check.is_false(is_scheduler_enabled({SCHEDULER_ENABLED_ENV: value, "APP_ENV": app_env}), f"{value!r} / {app_env!r}")


@pytest.mark.parametrize("value", ["", " ", "\t"])
@pytest.mark.parametrize(
    ("app_env", "expected"),
    [("development", False), ("Development", False), (" DEVELOPMENT ", False), ("production", True), ("staging", True), ("test", True), ("", True), ("dev", True)],
)
def test_unset_or_blank_is_decided_by_app_env(value, app_env, expected):
    """未設定・空は APP_ENV で決まる。development(大文字小文字・空白を無視)のときだけ無効で、それ以外(未設定・別名を含む)は有効(本番での設定漏れでジョブが止まらない)。"""
    check.equal(is_scheduler_enabled({SCHEDULER_ENABLED_ENV: value, "APP_ENV": app_env}), expected)
    if value == "":
        check.equal(is_scheduler_enabled({"APP_ENV": app_env}), expected)


def test_nothing_set_is_enabled():
    """どちらも未設定なら有効(development と明示された場合だけ無効)。"""
    check.is_true(is_scheduler_enabled({}))


@pytest.mark.parametrize("value", ["maybe", "2", "enable", "disabled", "ture", "y", "n", "t", "f", "tru e", "-1", "none", "null"])
def test_invalid_value_raises(value):
    """真偽値として解釈できない値は ValueError(起動時に気づけるよう、黙って無効/有効にしない)。メッセージに変数名を含む。"""
    with pytest.raises(ValueError, match=SCHEDULER_ENABLED_ENV):
        is_scheduler_enabled({SCHEDULER_ENABLED_ENV: value, "APP_ENV": "production"})


def test_invalid_value_raises_even_in_development():
    """APP_ENV=development でも、不正な値は ValueError(設定の誤りを隠さない)。"""
    with pytest.raises(ValueError):
        is_scheduler_enabled({SCHEDULER_ENABLED_ENV: "maybe", "APP_ENV": "development"})


def test_reads_process_environment_by_default(monkeypatch):
    """引数を省略すると os.environ を読む。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv(SCHEDULER_ENABLED_ENV, raising=False)
    check.is_false(is_scheduler_enabled())
    monkeypatch.setenv(SCHEDULER_ENABLED_ENV, "true")
    check.is_true(is_scheduler_enabled())
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv(SCHEDULER_ENABLED_ENV)
    check.is_true(is_scheduler_enabled())
    monkeypatch.setenv(SCHEDULER_ENABLED_ENV, "off")
    check.is_false(is_scheduler_enabled())


def test_environment_variable_name():
    """環境変数名は SCHEDULER_ENABLED(ドキュメント・.env.default と一致)。"""
    check.equal(SCHEDULER_ENABLED_ENV, "SCHEDULER_ENABLED")
