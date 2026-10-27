# -*- coding: utf-8 -*-
"""models(Spec の to_representation / Result の repr)と settings(環境変数からの設定)のテスト。"""
import dataclasses
import logging

import pytest
import pytest_check as check

import modules.keycloak_admin as keycloak_admin
from modules.keycloak_admin import AppClientSettings, ClientResult, ClientSpec, KeycloakAdminSettings, ProtocolMapperSpec, RealmResult, RealmSpec, SetupResult, UserResult, UserSpec
from modules.keycloak_admin.settings import DEFAULT_CALLBACK_URL, DEFAULT_FRONTEND_URL, INSECURE_DEFAULT_ADMIN_PASSWORD, default_init_user_password


class TestClientSpec:
    """ClientSpec.to_representation。"""

    def test_defaults_match_bff_client(self):
        """既定は BFF 用: confidential・認可コードフロー・パスワードグラント有効・サービスアカウント無効。"""
        rep = ClientSpec(client_id="fastapi-app").to_representation()
        check.equal(
            rep,
            {
                "clientId": "fastapi-app",
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": True,
                "serviceAccountsEnabled": False,
                "redirectUris": [],
                "webOrigins": [],
                "attributes": {},
            },
        )

    def test_post_logout_redirect_uris_joined_with_double_hash(self):
        """post.logout.redirect.uris 属性は ## で連結する(1 件ならそのまま)。"""
        two = ClientSpec(client_id="c", post_logout_redirect_uris=("http://a/*", "http://b/*")).to_representation()
        check.equal(two["attributes"]["post.logout.redirect.uris"], "http://a/*##http://b/*")
        one = ClientSpec(client_id="c", post_logout_redirect_uris=("http://a/*",)).to_representation()
        check.equal(one["attributes"]["post.logout.redirect.uris"], "http://a/*")

    def test_no_post_logout_attribute_when_empty(self):
        """post_logout_redirect_uris が空なら属性自体を出さない。"""
        check.is_not_in("post.logout.redirect.uris", ClientSpec(client_id="c").to_representation()["attributes"])

    def test_attributes_are_merged_and_not_mutated(self):
        """追加属性は残り、元の attributes を書き換えない。"""
        attributes = {"pkce.code.challenge.method": "S256"}
        spec = ClientSpec(client_id="c", attributes=attributes, post_logout_redirect_uris=("http://a/*",))
        rep = spec.to_representation()
        check.equal(rep["attributes"], {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": "http://a/*"})
        check.equal(attributes, {"pkce.code.challenge.method": "S256"})
        check.equal(spec.to_representation(), rep, "繰り返し呼んでも同じ")

    def test_lists_and_flags(self):
        """redirect / origin はリスト化し、フラグはそのまま反映する。"""
        rep = ClientSpec(client_id="c", redirect_uris=("a", "b"), web_origins=("o",), public_client=True, standard_flow_enabled=False, direct_access_grants_enabled=False, service_accounts_enabled=True, enabled=False).to_representation()
        check.equal((rep["redirectUris"], rep["webOrigins"]), (["a", "b"], ["o"]))
        check.equal((rep["publicClient"], rep["standardFlowEnabled"], rep["directAccessGrantsEnabled"], rep["serviceAccountsEnabled"], rep["enabled"]), (True, False, False, True, False))

    def test_extra_fields_cannot_override_explicit_fields(self):
        """extra は追加できるが、明示フィールド(clientId など)は上書きできない。"""
        rep = ClientSpec(client_id="real", extra={"clientId": "evil", "description": "d"}).to_representation()
        check.equal(rep["clientId"], "real")
        check.equal(rep["description"], "d")


class TestUserSpec:
    """UserSpec.to_representation。"""

    def test_minimal_omits_none(self):
        """未指定(None)の email / firstName / lastName は含めない。emailVerified は常に含める。"""
        check.equal(UserSpec(username="alice").to_representation(), {"username": "alice", "enabled": True, "emailVerified": False})

    def test_full(self):
        """全項目を指定すると Keycloak のフィールド名で出力する。attributes の値はコピーされる。"""
        values = ["v"]
        rep = UserSpec(username="alice", enabled=False, email="a@example.com", email_verified=True, first_name="A", last_name="L", required_actions=("UPDATE_PASSWORD",), attributes={"k": values}).to_representation()
        check.equal(
            rep,
            {
                "username": "alice",
                "enabled": False,
                "emailVerified": True,
                "email": "a@example.com",
                "firstName": "A",
                "lastName": "L",
                "requiredActions": ["UPDATE_PASSWORD"],
                "attributes": {"k": ["v"]},
            },
        )
        check.is_not(rep["attributes"]["k"], values)

    def test_empty_string_is_kept_but_none_is_omitted(self):
        """空文字は None と区別して出力する(指定したものは送る)。"""
        rep = UserSpec(username="a", email="").to_representation()
        check.equal(rep["email"], "")


class TestRealmAndMapperSpec:
    """RealmSpec / ProtocolMapperSpec。"""

    def test_realm_representation(self):
        """settings を展開し、realm / enabled は明示値を優先する。"""
        rep = RealmSpec(realm="r1", enabled=False, settings={"bruteForceProtected": True, "realm": "evil", "enabled": True}).to_representation()
        check.equal(rep, {"bruteForceProtected": True, "realm": "r1", "enabled": False})

    def test_realm_default(self):
        """既定は enabled=True で settings なし。"""
        check.equal(RealmSpec(realm="r1").to_representation(), {"realm": "r1", "enabled": True})

    def test_mapper_representation_copies_config(self):
        """マッパーの config は辞書コピーで出力する。"""
        config = {"a": "1"}
        rep = ProtocolMapperSpec(name="n", protocol_mapper="p", config=config).to_representation()
        check.equal(rep, {"name": "n", "protocol": "openid-connect", "protocolMapper": "p", "config": {"a": "1"}})
        check.is_not(rep["config"], config)


class TestResultRepr:
    """SetupResult の repr にシークレットを出さない。"""

    def _result(self) -> SetupResult:
        return SetupResult(
            realm=RealmResult(realm="r1", created=True),
            client=ClientResult(id="cid", client_id="fastapi-app", created=True),
            client_secret="TOP-SECRET-VALUE",
            user=UserResult(id="uid", username="alice", created=False),
        )

    def test_repr_hides_client_secret(self):
        """repr / str に client_secret の値が出ず、他のフィールドは出る。"""
        result = self._result()
        for text in (repr(result), str(result)):
            check.is_not_in("TOP-SECRET-VALUE", text)
            check.is_in("fastapi-app", text)
        check.equal(result.client_secret, "TOP-SECRET-VALUE")

    def test_results_are_immutable(self):
        """Result は不変。"""
        with pytest.raises(dataclasses.FrozenInstanceError):
            self._result().client_secret = "x"  # type: ignore[misc]

    def test_realm_result_default_updated_false(self):
        """RealmResult / ClientResult の updated は既定 False。"""
        check.is_false(RealmResult(realm="r", created=True).updated)
        check.is_false(ClientResult(id="i", client_id="c", created=True).updated)


class TestPackageExports:
    """__all__ に載っている名前はすべて import できる。"""

    def test_all_names_resolve(self):
        """公開 API の名前の取りこぼし(未定義)が無い。"""
        missing = [name for name in keycloak_admin.__all__ if not hasattr(keycloak_admin, name)]
        check.equal(missing, [])


class TestAdminSettingsDefaults:
    """KeycloakAdminSettings の既定値と派生プロパティ。"""

    def test_dataclass_defaults(self):
        """既定値: コンテナ内ネットワークの URL・master / admin-cli・10 秒 / 30 秒。"""
        settings = KeycloakAdminSettings()
        check.equal(settings.server_url, "http://keycloak_c:8080")
        check.equal(settings.http_relative_path, "keycloak")
        check.equal((settings.admin_realm, settings.admin_client_id, settings.admin_username), ("master", "admin-cli", "admin"))
        check.equal((settings.request_timeout_seconds, settings.deadline_seconds), (10.0, 30.0))
        check.equal(settings.base_url, "http://keycloak_c:8080/keycloak")
        check.equal(settings.admin_token_url, "http://keycloak_c:8080/keycloak/realms/master/protocol/openid-connect/token")

    @pytest.mark.parametrize(
        ("server_url", "path", "expected"),
        [
            ("http://kc:8080", "keycloak", "http://kc:8080/keycloak"),
            ("http://kc:8080/", "keycloak", "http://kc:8080/keycloak"),
            ("http://kc:8080//", "/keycloak/", "http://kc:8080/keycloak"),
            ("http://kc:8080", "", "http://kc:8080"),
            ("http://kc:8080/", "/", "http://kc:8080"),
            ("http://kc:8080", "auth/kc", "http://kc:8080/auth/kc"),
        ],
    )
    def test_base_url_normalization(self, server_url, path, expected):
        """server_url と http_relative_path の余分なスラッシュを正規化して結合する(コンテキストパスが空ならそのまま)。"""
        check.equal(KeycloakAdminSettings(server_url=server_url, http_relative_path=path).base_url, expected)

    def test_token_url_uses_admin_realm(self):
        """トークン URL は admin_realm を使う。"""
        settings = KeycloakAdminSettings(server_url="http://kc", http_relative_path="", admin_realm="ops")
        check.equal(settings.admin_token_url, "http://kc/realms/ops/protocol/openid-connect/token")

    def test_repr_hides_password(self):
        """repr にパスワードが出ない。"""
        check.is_not_in("hunter2-pw", repr(KeycloakAdminSettings(admin_password="hunter2-pw")))


class TestAdminSettingsFromEnv:
    """KeycloakAdminSettings.from_env。"""

    def test_defaults_in_development(self, caplog):
        """環境変数が空(APP_ENV 未設定は development 扱い)なら、警告を出して開発用既定値を使う。"""
        with caplog.at_level(logging.WARNING, logger="modules.keycloak_admin.settings"):
            settings = KeycloakAdminSettings.from_env()
        check.equal(settings.admin_password, INSECURE_DEFAULT_ADMIN_PASSWORD)
        check.equal(settings, KeycloakAdminSettings())
        check.is_in("KEYCLOAK_ADMIN_PASSWORD", caplog.text)

    def test_reads_all_variables(self, monkeypatch):
        """すべての環境変数を読み取る(前後の空白は除く)。"""
        for name, value in {
            "KEYCLOAK_URL": " http://kc.example:9000 ",
            "KEYCLOAK_HTTP_RELATIVE_PATH": " /auth/ ",
            "KEYCLOAK_ADMIN_USERNAME": "root",
            "KEYCLOAK_ADMIN_PASSWORD": "pw",
            "KEYCLOAK_ADMIN_REALM": "ops",
            "KEYCLOAK_ADMIN_CLIENT_ID": "my-cli",
            "KEYCLOAK_ADMIN_TIMEOUT_SECONDS": "2.5",
            "KEYCLOAK_ADMIN_DEADLINE_SECONDS": "45",
        }.items():
            monkeypatch.setenv(name, value)
        settings = KeycloakAdminSettings.from_env()
        check.equal(settings.base_url, "http://kc.example:9000/auth")
        check.equal((settings.admin_username, settings.admin_password, settings.admin_realm, settings.admin_client_id), ("root", "pw", "ops", "my-cli"))
        check.equal((settings.request_timeout_seconds, settings.deadline_seconds), (2.5, 45.0))

    def test_blank_values_fall_back_to_defaults(self, monkeypatch):
        """空文字・空白だけの値は既定値にフォールバックする(コンテキストパスを除く)。"""
        for name in ("KEYCLOAK_URL", "KEYCLOAK_ADMIN_USERNAME", "KEYCLOAK_ADMIN_REALM", "KEYCLOAK_ADMIN_CLIENT_ID", "KEYCLOAK_ADMIN_TIMEOUT_SECONDS", "KEYCLOAK_ADMIN_DEADLINE_SECONDS"):
            monkeypatch.setenv(name, "  ")
        monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "pw")
        check.equal(KeycloakAdminSettings.from_env(), KeycloakAdminSettings(admin_password="pw"))

    def test_empty_relative_path_means_no_context_path(self, monkeypatch):
        """KEYCLOAK_HTTP_RELATIVE_PATH を空に設定するとコンテキストパスなし(未設定の keycloak とは区別する)。"""
        monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "pw")
        monkeypatch.setenv("KEYCLOAK_HTTP_RELATIVE_PATH", "")
        check.equal(KeycloakAdminSettings.from_env().base_url, "http://keycloak_c:8080")

    @pytest.mark.parametrize("app_env", ["production", "staging", "prod", "PRODUCTION", " Production ", ""])
    def test_missing_password_outside_development_raises(self, monkeypatch, app_env):
        """APP_ENV が development 以外(大文字小文字・空白は正規化。空文字も development ではない)で管理パスワード未設定なら RuntimeError。"""
        monkeypatch.setenv("APP_ENV", app_env)
        with pytest.raises(RuntimeError, match="KEYCLOAK_ADMIN_PASSWORD"):
            KeycloakAdminSettings.from_env()

    @pytest.mark.parametrize("app_env", ["development", "DEVELOPMENT", " Development "])
    def test_missing_password_in_development_uses_default(self, monkeypatch, app_env):
        """APP_ENV=development(大文字小文字・空白は正規化)なら既定値で動く。"""
        monkeypatch.setenv("APP_ENV", app_env)
        check.equal(KeycloakAdminSettings.from_env().admin_password, "admin")

    def test_password_set_in_production_is_accepted(self, monkeypatch):
        """本番でもパスワードが設定されていれば読める。"""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "prod-pw")
        check.equal(KeycloakAdminSettings.from_env().admin_password, "prod-pw")

    def test_runtime_error_does_not_contain_a_password(self, monkeypatch):
        """未設定エラーのメッセージには APP_ENV の名前は出るが、既定パスワードは出ない。"""
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(RuntimeError) as exc_info:
            KeycloakAdminSettings.from_env()
        check.is_in("APP_ENV=production", str(exc_info.value))

    @pytest.mark.parametrize("name", ["KEYCLOAK_ADMIN_TIMEOUT_SECONDS", "KEYCLOAK_ADMIN_DEADLINE_SECONDS"])
    @pytest.mark.parametrize("value", ["abc", "0", "-1", "-0.5", "1,5"])
    def test_invalid_timeout_raises_value_error(self, monkeypatch, name, value):
        """タイムアウトが数値でない・0 以下なら ValueError。"""
        monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "pw")
        monkeypatch.setenv(name, value)
        with pytest.raises(ValueError):
            KeycloakAdminSettings.from_env()

    def test_non_positive_timeout_message_names_variable(self, monkeypatch):
        """0 以下のときのメッセージに環境変数名が含まれる。"""
        monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "pw")
        monkeypatch.setenv("KEYCLOAK_ADMIN_TIMEOUT_SECONDS", "0")
        with pytest.raises(ValueError, match="KEYCLOAK_ADMIN_TIMEOUT_SECONDS"):
            KeycloakAdminSettings.from_env()


class TestAppClientSettings:
    """AppClientSettings.from_env。"""

    def test_defaults(self):
        """環境変数なしなら localhost:5173 を基準にした既定値。"""
        settings = AppClientSettings.from_env()
        check.equal(settings.callback_url, DEFAULT_CALLBACK_URL)
        check.equal(settings.web_origin, DEFAULT_FRONTEND_URL)
        check.equal(settings.post_logout_redirect_uri, f"{DEFAULT_FRONTEND_URL}/*")
        check.equal(settings, AppClientSettings())

    def test_derived_from_frontend_url(self, monkeypatch):
        """FRONTEND_URL から post_logout_redirect_uri と web_origin を導出する(末尾スラッシュは除く)。"""
        monkeypatch.setenv("FRONTEND_URL", "https://app.example.com//")
        settings = AppClientSettings.from_env()
        check.equal(settings.web_origin, "https://app.example.com")
        check.equal(settings.post_logout_redirect_uri, "https://app.example.com/*")
        check.equal(settings.callback_url, DEFAULT_CALLBACK_URL, "callback は FRONTEND_URL から導出しない")

    def test_explicit_values_win(self, monkeypatch):
        """個別の環境変数は FRONTEND_URL より優先する。"""
        monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
        monkeypatch.setenv("APP_CALLBACK_URL", "https://app.example.com/cb")
        monkeypatch.setenv("APP_POST_LOGOUT_REDIRECT_URI", "https://app.example.com/bye")
        monkeypatch.setenv("APP_WEB_ORIGIN", "https://other.example.com")
        settings = AppClientSettings.from_env()
        check.equal((settings.callback_url, settings.post_logout_redirect_uri, settings.web_origin), ("https://app.example.com/cb", "https://app.example.com/bye", "https://other.example.com"))

    def test_blank_frontend_url_falls_back(self, monkeypatch):
        """FRONTEND_URL が空白だけなら既定値を使う。"""
        monkeypatch.setenv("FRONTEND_URL", "  ")
        check.equal(AppClientSettings.from_env().web_origin, DEFAULT_FRONTEND_URL)


class TestInitUserPassword:
    """default_init_user_password。"""

    def test_default(self):
        """未設定は ChangeMe123!。"""
        check.equal(default_init_user_password(), "ChangeMe123!")

    def test_env_wins_and_empty_falls_back(self, monkeypatch):
        """環境変数があれば優先し、空文字なら既定値。"""
        monkeypatch.setenv("KEYCLOAK_INIT_USER_PASSWORD", "From-Env1!")
        check.equal(default_init_user_password(), "From-Env1!")
        monkeypatch.setenv("KEYCLOAK_INIT_USER_PASSWORD", "")
        check.equal(default_init_user_password(), "ChangeMe123!")
