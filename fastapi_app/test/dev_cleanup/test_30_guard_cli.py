# -*- coding: utf-8 -*-
"""dev_tools.e2e_cleanup の実行できる環境の判定と CLI(終了コード)のテスト。

DB・Keycloak には接続しない(後片付けの本体は差し替える)。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_check as check

from dev_tools import e2e_cleanup
from dev_tools.e2e_cleanup import (
    E2ECleanupInProgressError,
    E2ECleanupNotAllowedError,
    E2ECleanupResult,
    TenantCleanupCounts,
    cleanup_e2e_data,
    is_e2e_cleanup_allowed,
    main,
    require_e2e_cleanup_allowed,
)
from modules.tenancy import providers

DEV = ("development", "true")


class TestAllowed:
    """APP_ENV=development かつ AUTH_DEV_LOGIN_ENABLED が真の場合だけ許可する(dev-login と同じ条件)。"""

    @pytest.mark.parametrize("flag", ["true", "TRUE", "True", "1", "yes", "on", " true "])
    def test_allowed_in_development_with_dev_login(self, monkeypatch, flag):
        """開発環境で開発用ログインが有効(true / 1 / yes / on。大文字小文字・前後の空白は無視)なら許可する。"""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", flag)
        check.is_true(is_e2e_cleanup_allowed())
        require_e2e_cleanup_allowed()

    @pytest.mark.parametrize(
        ("app_env", "flag"),
        [
            ("production", "true"), ("staging", "true"), ("test", "true"), ("Production", "true"), ("", "true"), ("developmentx", "true"), ("dev", "true"),
            ("development", "false"), ("development", ""), ("development", "0"), ("development", "no"), ("development", "off"), ("development", "enabled"), ("production", "false"),
        ],
    )
    def test_refused_otherwise(self, monkeypatch, app_env, flag):
        """開発環境でない(未知の値・空を含む)、または開発用ログインが無効なら拒否する。require_* は E2ECleanupNotAllowedError。"""
        monkeypatch.setenv("APP_ENV", app_env)
        monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", flag)
        check.is_false(is_e2e_cleanup_allowed())
        with pytest.raises(E2ECleanupNotAllowedError) as caught:
            require_e2e_cleanup_allowed()
        check.is_in("APP_ENV=development", str(caught.value))

    def test_unset_dev_login_flag_is_refused(self, monkeypatch):
        """AUTH_DEV_LOGIN_ENABLED が未設定なら拒否する(明示的に有効化したときだけ動く)。"""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.delenv("AUTH_DEV_LOGIN_ENABLED", raising=False)
        check.is_false(is_e2e_cleanup_allowed())

    def test_error_hierarchy(self):
        """全ての例外は E2ECleanupError の派生(CLI・API が一括で扱える)。"""
        check.is_true(issubclass(E2ECleanupNotAllowedError, e2e_cleanup.E2ECleanupError))
        check.is_true(issubclass(E2ECleanupInProgressError, e2e_cleanup.E2ECleanupError))

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_entry_point_refuses_before_connecting(self, monkeypatch, dry_run):
        """cleanup_e2e_data は開発環境以外では、DB(CP のセッションを作るプロバイダ)に触れる前に拒否する。"""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", "true")

        def forbidden(*args, **kwargs):
            raise AssertionError("開発環境以外で DB に接続しようとした")

        monkeypatch.setattr(providers, "get_cp_sessionmaker", forbidden)
        monkeypatch.setattr(providers, "get_app_cp_agent_engine", forbidden)
        with pytest.raises(E2ECleanupNotAllowedError):
            cleanup_e2e_data(dry_run=dry_run)


@pytest.fixture
def cli(monkeypatch):
    """CLI の本体(cleanup_e2e_data)を差し替え、呼び出しを記録する。標準出力・標準エラーも取り出す。"""

    class Cli:
        calls: list[bool] = []
        outcome: object = E2ECleanupResult(dry_run=False)

    state = Cli()
    state.calls = []

    def fake(*, dry_run: bool = False):
        state.calls.append(dry_run)
        if isinstance(state.outcome, BaseException):
            raise state.outcome
        return state.outcome

    disposed = []
    monkeypatch.setattr(e2e_cleanup, "cleanup_e2e_data", fake)
    monkeypatch.setattr(providers, "dispose_providers", lambda: disposed.append(True))
    state.disposed = disposed
    return state


class TestCli:
    """main(): 0 = 成功、1 = 失敗したテナントがある、2 = 実行できない環境・実行中。"""

    def test_success_prints_json_and_exits_0(self, cli, capsys):
        """成功なら終了コード 0 で、結果を JSON で標準出力に表示する。"""
        cli.outcome = E2ECleanupResult(dry_run=False, tenants=TenantCleanupCounts(deprovisioned=2, reaped=1))
        check.equal(main([]), 0)
        out = capsys.readouterr().out
        payload = json.loads(out)
        check.equal((payload["ok"], payload["dry_run"], payload["tenants"]["deprovisioned"]), (True, False, 2))
        check.equal(cli.calls, [False])

    def test_dry_run_flag(self, cli, capsys):
        """--dry-run は dry_run=True で後片付けを呼ぶ。"""
        cli.outcome = E2ECleanupResult(dry_run=True)
        check.equal(main(["--dry-run"]), 0)
        check.equal(cli.calls, [True])
        check.equal(json.loads(capsys.readouterr().out)["dry_run"], True)

    def test_failures_exit_1(self, cli, capsys):
        """失敗したテナントがあれば終了コード 1(結果は表示する)。"""
        result = E2ECleanupResult(dry_run=False)
        result.failures.append(e2e_cleanup.CleanupFailure(scope="cp", tenant_code="e2e-abcd1234", error="deprovisioning_failed"))
        cli.outcome = result
        check.equal(main([]), 1)
        payload = json.loads(capsys.readouterr().out)
        check.equal((payload["ok"], payload["failures"][0]["tenant_code"]), (False, "e2e-abcd1234"))

    def test_not_allowed_exits_2(self, cli, capsys):
        """開発環境でない(E2ECleanupNotAllowedError)なら終了コード 2。メッセージは標準エラーで、標準出力には何も出さない。"""
        cli.outcome = E2ECleanupNotAllowedError("not allowed")
        check.equal(main([]), 2)
        captured = capsys.readouterr()
        check.equal((captured.out, "not allowed" in captured.err), ("", True))

    def test_in_progress_exits_2(self, cli, capsys):
        """別の後片付けが実行中(E2ECleanupInProgressError)でも終了コード 2。"""
        cli.outcome = E2ECleanupInProgressError("busy")
        check.equal(main(["--dry-run"]), 2)
        check.is_in("busy", capsys.readouterr().err)

    @pytest.mark.parametrize("outcome", [E2ECleanupNotAllowedError("x"), E2ECleanupInProgressError("x"), E2ECleanupResult(dry_run=False)])
    def test_providers_are_always_disposed(self, cli, outcome):
        """成功・拒否・実行中のいずれでも、終了時に DB エンジン(プロバイダ)を破棄する。"""
        cli.outcome = outcome
        main([])
        check.equal(cli.disposed, [True])

    def test_unknown_argument_is_a_usage_error(self, cli, capsys):
        """未知の引数は argparse の使い方エラー(SystemExit 2)で、後片付けは呼ばない。"""
        with pytest.raises(SystemExit) as caught:
            main(["--delete-everything"])
        check.equal(caught.value.code, 2)
        check.equal(cli.calls, [])

    def test_no_arguments_to_choose_targets(self, capsys):
        """対象を引数で指定する手段は無い(--dry-run と -v / --verbose だけ)。任意のデータを消せる CLI にしない。"""
        with pytest.raises(SystemExit) as caught:
            main(["--help"])
        check.equal(caught.value.code, 0)
        help_text = capsys.readouterr().out
        check.is_in("--dry-run", help_text)
        check.is_not_in("--tenant", help_text)
        check.is_not_in("--email", help_text)


class TestModuleEntryPoint:
    """``python -m dev_tools.e2e_cleanup`` の実際の終了コード(開発環境以外では DB に接続せず 2)。"""

    @pytest.mark.parametrize("app_env", ["production", "staging"])
    def test_exit_code_2_outside_development(self, app_env):
        """開発環境以外で実行すると終了コード 2、標準出力は空、標準エラーに理由が出る。"""
        src = Path(e2e_cleanup.__file__).resolve().parents[1]
        env = {**os.environ, "APP_ENV": app_env, "AUTH_DEV_LOGIN_ENABLED": "true", "PYTHONPATH": str(src)}
        done = subprocess.run([sys.executable, "-m", "dev_tools.e2e_cleanup", "--dry-run"], env=env, capture_output=True, text=True, timeout=120, cwd=str(src), check=False)
        check.equal(done.returncode, 2, done.stderr[-500:])
        check.equal(done.stdout, "")
        check.is_in("APP_ENV=development", done.stderr)
