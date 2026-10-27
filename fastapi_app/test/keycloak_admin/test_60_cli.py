# -*- coding: utf-8 -*-
"""modules.keycloak_admin.cli のテスト。

``KeycloakAdminClient.from_settings`` を monkeypatch してフェイクのクライアントを注入し、
標準出力・標準エラー・終了コードを検証する。実機の Keycloak には接続しない。
"""
import httpx
import pytest
import pytest_check as check

from modules.keycloak_admin import KeycloakAdminSettings, cli

R = "/keycloak/admin/realms"
REALM = f"{R}/tenant-a"
CLIENTS = f"{REALM}/clients"
USERS = f"{REALM}/users"
SECRET = "cli-client-secret-VALUE"


@pytest.fixture
def cli_kc(kc, monkeypatch):
    """CLI から呼ばれる from_settings をフェイクに差し替えた kc。受け取った settings を ``kc.received`` に残す。"""
    kc.on("GET", REALM, status=404)
    kc.on("POST", R, status=201)
    kc.on("GET", CLIENTS, json=[])
    kc.on("POST", CLIENTS, httpx.Response(201, headers={"Location": f"http://kc{CLIENTS}/cid-1"}))
    kc.on("GET", f"{CLIENTS}/cid-1/client-secret", json={"value": SECRET})
    kc.on("GET", USERS, json=[])
    kc.on("POST", USERS, httpx.Response(201, headers={"Location": f"http://kc{USERS}/uid-1"}))
    kc.on("PUT", f"{USERS}/uid-1/reset-password", status=204)
    kc.received = []

    def fake_from_settings(cls, settings, **kwargs):
        kc.received.append(settings)
        return kc.admin

    monkeypatch.setattr(cli.KeycloakAdminClient, "from_settings", classmethod(fake_from_settings))
    monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "admin-pw")
    return kc


class TestSuccess:
    """正常終了。"""

    def test_exit_code_and_stdout(self, cli_kc, capsys):
        """終了コード 0。進捗が順に出て、最後の行が KEYCLOAK_CLIENT_SECRET=...。"""
        code = cli.main(["tenant-a", "fastapi-app", "alice", "My-Pass1!"])
        out, err = capsys.readouterr()
        lines = out.splitlines()
        check.equal(code, 0)
        check.equal(lines[0], "[1/6] Get admin access token")
        check.is_in("[2/6] Ensure realm exists: tenant-a", lines)
        check.is_in("[6/6] Set user password", lines)
        check.equal(lines[-1], f"KEYCLOAK_CLIENT_SECRET={SECRET}")
        check.equal(lines[-2], "KEYCLOAK_CLIENT_ID=fastapi-app")
        check.is_in("Done.", lines)
        check.is_in("Realm:        tenant-a", lines)
        check.is_in("Username:     alice", lines)
        check.equal(err, "")

    def test_password_is_never_printed(self, cli_kc, capsys):
        """ユーザーのパスワードは標準出力・標準エラーのどちらにも出さない。"""
        cli.main(["tenant-a", "fastapi-app", "alice", "My-Pass1!"])
        out, err = capsys.readouterr()
        check.is_not_in("My-Pass1!", out + err)
        check.is_not_in("admin-pw", out + err)

    def test_explicit_password_is_used(self, cli_kc):
        """引数のパスワードを Keycloak に設定する。"""
        cli.main(["tenant-a", "fastapi-app", "alice", "My-Pass1!"])
        check.equal(cli_kc.requests_to("PUT")[0].json["value"], "My-Pass1!")

    def test_default_password_when_omitted(self, cli_kc):
        """パスワードを省略し環境変数も無ければ ChangeMe123! を使う。"""
        cli.main(["tenant-a", "fastapi-app", "alice"])
        check.equal(cli_kc.requests_to("PUT")[0].json["value"], "ChangeMe123!")

    def test_default_password_from_env(self, cli_kc, monkeypatch):
        """パスワードを省略すると KEYCLOAK_INIT_USER_PASSWORD を使う。"""
        monkeypatch.setenv("KEYCLOAK_INIT_USER_PASSWORD", "Env-Pass9!")
        cli.main(["tenant-a", "fastapi-app", "alice"])
        check.equal(cli_kc.requests_to("PUT")[0].json["value"], "Env-Pass9!")

    def test_empty_password_argument_uses_default(self, cli_kc):
        """パスワード引数が空文字なら省略時と同じ既定値を使う。"""
        cli.main(["tenant-a", "fastapi-app", "alice", ""])
        check.equal(cli_kc.requests_to("PUT")[0].json["value"], "ChangeMe123!")

    def test_settings_come_from_environment(self, cli_kc, monkeypatch):
        """from_settings には環境変数から作った設定を渡す。"""
        monkeypatch.setenv("KEYCLOAK_URL", "http://kc.example:1234")
        cli.main(["tenant-a", "fastapi-app", "alice"])
        check.is_instance(cli_kc.received[0], KeycloakAdminSettings)
        check.equal(cli_kc.received[0].server_url, "http://kc.example:1234")
        check.equal(cli_kc.received[0].admin_password, "admin-pw")

    def test_client_urls_come_from_environment(self, cli_kc, monkeypatch):
        """クライアントのリダイレクト URL 等は環境変数(FRONTEND_URL など)から作る。"""
        monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
        monkeypatch.setenv("APP_CALLBACK_URL", "https://app.example.com/cb")
        cli.main(["tenant-a", "fastapi-app", "alice"])
        body = cli_kc.requests_to("POST", CLIENTS)[0].json
        check.equal(body["redirectUris"], ["https://app.example.com/cb"])
        check.equal(body["webOrigins"], ["https://app.example.com"])
        check.equal(body["attributes"]["post.logout.redirect.uris"], "https://app.example.com/*")

    def test_rerun_prints_existing_messages(self, cli_kc, capsys):
        """作成済みの再実行は exit 0 で、already exists を表示し、同じシークレットを最後に出す。"""
        cli_kc.on("GET", REALM, json={"realm": "tenant-a"})
        cli_kc.on("GET", CLIENTS, json=[{"id": "cid-1", "clientId": "fastapi-app"}])
        cli_kc.on("PUT", f"{CLIENTS}/cid-1", status=204)
        cli_kc.on("GET", USERS, json=[{"id": "uid-1", "username": "alice"}])
        code = cli.main(["tenant-a", "fastapi-app", "alice"])
        out = capsys.readouterr().out
        check.equal(code, 0)
        check.is_in("  - Realm already exists", out)
        check.is_in("  - User already exists", out)
        check.equal(out.splitlines()[-1], f"KEYCLOAK_CLIENT_SECRET={SECRET}")


class TestFailure:
    """異常終了は exit 1 + 標準エラーに ERROR: ...。秘匿値と KEYCLOAK_CLIENT_SECRET は出さない。"""

    def _assert_failed(self, code, capsys, *, message_fragment):
        out, err = capsys.readouterr()
        check.equal(code, 1)
        check.is_true(err.startswith("ERROR: "), err)
        check.is_in(message_fragment, err)
        check.is_not_in("KEYCLOAK_CLIENT_SECRET", out + err)
        check.is_not_in(SECRET, out + err)
        check.is_not_in("My-Pass1!", out + err)

    def test_authentication_failure(self, cli_kc, capsys):
        """管理者認証の失敗は exit 1。ステータスと error が stderr に出る。"""
        cli_kc.token_response = httpx.Response(401, json={"error": "invalid_grant", "error_description": "Invalid user credentials"})
        code = cli.main(["tenant-a", "fastapi-app", "alice", "My-Pass1!"])
        self._assert_failed(code, capsys, message_fragment="Failed to obtain admin token. HTTP 401 error=invalid_grant")

    def test_keycloak_error_midway(self, cli_kc, capsys):
        """途中の Admin API エラー(403)でも exit 1。進捗は途中まで出ている。"""
        cli_kc.on("POST", R, httpx.Response(403, json={"error": "HTTP 403 Forbidden"}))
        code = cli.main(["tenant-a", "fastapi-app", "alice", "My-Pass1!"])
        out = capsys.readouterr()
        check.equal(code, 1)
        check.is_in("[2/6] Ensure realm exists: tenant-a", out.out)
        check.is_in("Failed to create realm tenant-a. HTTP 403", out.err)
        check.is_not_in("KEYCLOAK_CLIENT_SECRET", out.out)

    def test_connection_failure(self, cli_kc, capsys):
        """接続失敗は exit 1。"""
        cli_kc.token_response = httpx.ConnectError("refused")
        code = cli.main(["tenant-a", "fastapi-app", "alice", "My-Pass1!"])
        self._assert_failed(code, capsys, message_fragment="ConnectError")

    def test_timeout(self, cli_kc, capsys):
        """タイムアウトは exit 1。"""
        cli_kc.token_response = httpx.ReadTimeout("slow")
        code = cli.main(["tenant-a", "fastapi-app", "alice", "My-Pass1!"])
        self._assert_failed(code, capsys, message_fragment="ReadTimeout")

    def test_invalid_realm_name(self, cli_kc, capsys):
        """不正なレルム名(ValueError)は exit 1 で、Keycloak へ書き込まない。"""
        code = cli.main(["bad realm", "fastapi-app", "alice", "My-Pass1!"])
        self._assert_failed(code, capsys, message_fragment="realm must match")
        check.equal(cli_kc.writes, [])

    def test_settings_error_in_production(self, monkeypatch, capsys):
        """本番相当で管理パスワード未設定(RuntimeError)なら exit 1。Keycloak へは接続しない。"""
        monkeypatch.delenv("KEYCLOAK_ADMIN_PASSWORD", raising=False)
        monkeypatch.setenv("APP_ENV", "production")
        called = []
        monkeypatch.setattr(cli.KeycloakAdminClient, "from_settings", classmethod(lambda cls, settings, **kw: called.append(settings)))
        code = cli.main(["tenant-a", "fastapi-app", "alice"])
        self._assert_failed(code, capsys, message_fragment="KEYCLOAK_ADMIN_PASSWORD")
        check.equal(called, [])

    def test_invalid_timeout_setting(self, monkeypatch, capsys):
        """タイムアウト設定が不正(ValueError)なら exit 1。"""
        monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "pw")
        monkeypatch.setenv("KEYCLOAK_ADMIN_TIMEOUT_SECONDS", "abc")
        code = cli.main(["tenant-a", "fastapi-app", "alice"])
        out, err = capsys.readouterr()
        check.equal(code, 1)
        check.is_true(err.startswith("ERROR: "))


class TestArguments:
    """引数。"""

    @pytest.mark.parametrize("argv", [[], ["r"], ["r", "c"]])
    def test_missing_required_arguments_exit_2(self, argv, capsys):
        """必須引数(realm_name client_id username)が足りないと argparse が exit 2。"""
        with pytest.raises(SystemExit) as exc_info:
            cli.main(argv)
        check.equal(exc_info.value.code, 2)
        check.is_in("usage:", capsys.readouterr().err)

    def test_too_many_arguments_exit_2(self):
        """余分な引数は exit 2。"""
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["r", "c", "u", "p", "extra"])
        check.equal(exc_info.value.code, 2)

    def test_help_lists_environment_variables(self, capsys):
        """--help は 0 で終了し、環境変数の一覧を表示する。"""
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["--help"])
        check.equal(exc_info.value.code, 0)
        out = capsys.readouterr().out
        for name in ("KEYCLOAK_URL", "KEYCLOAK_ADMIN_PASSWORD", "KEYCLOAK_INIT_USER_PASSWORD", "FRONTEND_URL"):
            check.is_in(name, out)

    def test_verbose_flag_is_accepted(self, cli_kc, capsys):
        """-v を付けても成功する(詳細ログは標準エラー)。"""
        check.equal(cli.main(["-v", "tenant-a", "fastapi-app", "alice"]), 0)
        check.equal(capsys.readouterr().out.splitlines()[-1], f"KEYCLOAK_CLIENT_SECRET={SECRET}")

    def test_parser_defaults(self):
        """user_password の既定は None(実行時に環境変数 / 既定値で解決する)。"""
        args = cli.build_parser().parse_args(["r", "c", "u"])
        check.equal((args.realm_name, args.client_id, args.username, args.user_password, args.verbose), ("r", "c", "u", None, False))
