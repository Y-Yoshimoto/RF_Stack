# -*- coding: utf-8 -*-
"""modules.keycloak_admin.templates(レルムのテンプレート・ユーザー・停止/削除・管理クライアント)のテスト。

``fake_server.FakeKeycloakServer``(状態を持つ Keycloak のフェイク。``httpx.MockTransport``)に対して実行する。
ensure_* は「無い → 作成」「ある」「作成時 409」の 3 分岐を確認する。
"""
import json
import uuid

import pytest
import pytest_check as check

from modules.keycloak_admin import KeycloakAdminError
from modules.keycloak_admin.client_secret import derive_client_secret
from modules.keycloak_admin.realms import set_realm_enabled
from modules.keycloak_admin.settings import PlatformClientSettings
from modules.keycloak_admin.templates import (
    TENANT_USER_ADMIN_CLIENT_ID,
    TENANT_USER_ADMIN_ROLES,
    create_provisioner_admin_client,
    delete_realm_if_exists,
    ensure_control_plane_realm,
    ensure_tenant_realm,
    ensure_tenant_user,
    tenant_realm_name,
)
from modules.keycloak_admin.token_provider import ClientCredentialsTokenProvider, PasswordGrantTokenProvider

from .fake_server import FakeKeycloakServer

SEED = "seed-for-templates-test"
TENANT_ID = uuid.UUID("0194e6a0-0000-7000-8000-00000000a1fa")
OTHER_TENANT_ID = uuid.UUID("0194e6a0-0000-7000-8000-00000000b2fb")
SETTINGS = PlatformClientSettings(app_client_id="fastapi-app", cp_client_id="fastapi-cp", frontend_url="http://app.test", callback_url="http://app.test/api/auth/callback", direct_access_grants_enabled=True)
PROD_SETTINGS = PlatformClientSettings(app_client_id="fastapi-app", cp_client_id="fastapi-cp", frontend_url="http://app.test", callback_url="http://app.test/api/auth/callback", direct_access_grants_enabled=False)
PASSWORD = "Temp-Passw0rd-VALUE!"


@pytest.fixture
def server() -> FakeKeycloakServer:
    return FakeKeycloakServer()


def provision(server: FakeKeycloakServer, *, tenant_code="alpha", tenant_id=TENANT_ID, enabled=True, settings=SETTINGS):
    """テナントレルムのテンプレートを適用する(毎回新しい管理クライアントを使う)。"""
    with server.admin() as admin:
        return ensure_tenant_realm(admin, tenant_code=tenant_code, tenant_id=tenant_id, display_name="Alpha Inc.", enabled=enabled, settings=settings, secret_seed=SEED)


def login_client(state, client_id="fastapi-app") -> dict:
    return state.client_by_client_id(client_id)


def mappers_of(state, client_id="fastapi-app") -> dict[str, dict]:
    client = login_client(state, client_id)
    return {m["name"]: m for m in state.mappers.get(client["id"], {}).values()}


class TestTenantRealmCreate:
    """ensure_tenant_realm: 何も無い状態から作る。"""

    def test_result(self, server):
        """結果はレルム名・作成有無・クライアント ID を含み、シークレットを含まない。"""
        result = provision(server)
        check.equal((result.realm_name, result.created, result.login_client_id, result.user_admin_client_id), ("tenant-alpha", True, "fastapi-app", TENANT_USER_ADMIN_CLIENT_ID))
        check.is_not_in(derive_client_secret(SEED, "tenant-alpha", "fastapi-app"), repr(result))

    def test_realm_settings(self, server):
        """レルムは表示名・メール重複不可・メールログイン可・登録とパスワードリセット無効・ブルートフォース保護・有効で作られる。"""
        provision(server)
        rep = server.realms["tenant-alpha"].rep
        expected = {
            "realm": "tenant-alpha",
            "enabled": True,
            "displayName": "Alpha Inc.",
            "duplicateEmailsAllowed": False,
            "loginWithEmailAllowed": True,
            "registrationAllowed": False,
            "resetPasswordAllowed": False,
            "bruteForceProtected": True,
        }
        for key, value in expected.items():
            check.equal(rep[key], value, key)

    def test_roles_and_default_roles(self, server):
        """レルムロール tenant_admin / member を作り、既定ロールには member だけを入れる。"""
        provision(server)
        state = server.realms["tenant-alpha"]
        check.is_in("tenant_admin", state.roles)
        check.is_in("member", state.roles)
        check.equal(state.default_composites, ["member"])

    def test_login_client(self, server):
        """ログイン用クライアントは confidential・Standard Flow + PKCE(S256)・Implicit 無効・導出シークレット・URL は設定どおり。"""
        provision(server)
        client = login_client(server.realms["tenant-alpha"])
        check.equal((client["publicClient"], client["standardFlowEnabled"], client["implicitFlowEnabled"], client["serviceAccountsEnabled"]), (False, True, False, False))
        check.equal(client["attributes"]["pkce.code.challenge.method"], "S256")
        check.equal(client["secret"], derive_client_secret(SEED, "tenant-alpha", "fastapi-app"))
        check.equal(client["redirectUris"], ["http://app.test/api/auth/callback"])
        check.equal(client["webOrigins"], ["http://app.test"])
        check.equal(client["attributes"]["post.logout.redirect.uris"], "http://app.test/alpha/*")

    @pytest.mark.parametrize(("settings", "expected"), [(SETTINGS, True), (PROD_SETTINGS, False)])
    def test_direct_access_grants_follow_environment(self, server, settings, expected):
        """パスワードグラント(directAccessGrants)は開発環境の設定のときだけ有効。"""
        provision(server, settings=settings)
        check.equal(login_client(server.realms["tenant-alpha"])["directAccessGrantsEnabled"], expected)

    def test_tenant_id_and_audience_mappers(self, server):
        """tenant_id のハードコードクレーム(ID / アクセストークン / userinfo)と、aud にログイン用クライアントを入れるマッパーを作る。"""
        provision(server)
        mappers = mappers_of(server.realms["tenant-alpha"])
        tenant_mapper = mappers["tenant_id"]
        check.equal(tenant_mapper["protocolMapper"], "oidc-hardcoded-claim-mapper")
        check.equal(tenant_mapper["config"]["claim.name"], "tenant_id")
        check.equal(tenant_mapper["config"]["claim.value"], str(TENANT_ID))
        for flag in ("id.token.claim", "access.token.claim", "userinfo.token.claim"):
            check.equal(tenant_mapper["config"][flag], "true", flag)
        audience = mappers["audience"]
        check.equal(audience["protocolMapper"], "oidc-audience-mapper")
        check.equal(audience["config"]["included.client.audience"], "fastapi-app")

    def test_tenant_user_admin_service_account(self, server):
        """tenant-user-admin はサービスアカウントのみ(導出シークレット)で、realm-management の manage/view/query-users だけを持つ。"""
        provision(server)
        state = server.realms["tenant-alpha"]
        client = login_client(state, TENANT_USER_ADMIN_CLIENT_ID)
        check.equal((client["serviceAccountsEnabled"], client["standardFlowEnabled"], client["directAccessGrantsEnabled"], client["publicClient"]), (True, False, False, False))
        check.equal(client["secret"], derive_client_secret(SEED, "tenant-alpha", TENANT_USER_ADMIN_CLIENT_ID))
        service_user = next(u for u in state.users.values() if u.get("serviceAccountClientId") == client["id"])
        management = state.client_by_client_id("realm-management")
        granted = state.user_client_roles[(service_user["id"], management["id"])]
        check.equal(sorted(granted), sorted(TENANT_USER_ADMIN_ROLES))
        for forbidden in ("manage-realm", "manage-clients", "impersonation", "view-realm"):
            check.is_not_in(forbidden, granted)

    def test_secrets_differ_per_tenant_and_client(self, server):
        """別テナントのレルムには別のシークレットが設定される(テナント間で共有しない)。"""
        provision(server, tenant_code="alpha", tenant_id=TENANT_ID)
        provision(server, tenant_code="beta", tenant_id=OTHER_TENANT_ID)
        secrets = {
            login_client(server.realms["tenant-alpha"])["secret"],
            login_client(server.realms["tenant-beta"])["secret"],
            login_client(server.realms["tenant-alpha"], TENANT_USER_ADMIN_CLIENT_ID)["secret"],
            login_client(server.realms["tenant-beta"], TENANT_USER_ADMIN_CLIENT_ID)["secret"],
        }
        check.equal(len(secrets), 4)

    def test_disabled_realm_can_be_created(self, server):
        """enabled=False を渡すと、無効なレルムとして作られる。"""
        provision(server, enabled=False)
        check.is_false(server.realms["tenant-alpha"].rep["enabled"])


class TestTenantRealmExisting:
    """ensure_tenant_realm: すでにある(再実行で同じ状態に収束する)。"""

    def test_rerun_converges_without_creating_anything(self, server):
        """再実行しても POST(作成)は一切行わず、結果は created=False。"""
        provision(server)
        before = server.snapshot()
        posts_before = len(server.writes_to("POST", ".*"))
        result = provision(server)
        check.is_false(result.created)
        check.equal(len(server.writes_to("POST", ".*")), posts_before, "2 回目は作成しない")
        check.equal(server.snapshot(), before, "状態が変わらない")

    def test_existing_settings_are_reapplied(self, server):
        """既存のレルム・クライアントの設定は毎回反映される(手で変えられた設定が元に戻る)。"""
        provision(server)
        state = server.realms["tenant-alpha"]
        state.rep["registrationAllowed"] = True
        login_client(state)["secret"] = "tampered"
        login_client(state)["publicClient"] = True
        provision(server)
        check.is_false(state.rep["registrationAllowed"])
        check.equal(login_client(state)["secret"], derive_client_secret(SEED, "tenant-alpha", "fastapi-app"))
        check.is_false(login_client(state)["publicClient"])

    def test_enabled_flag_is_applied_to_existing_realm(self, server):
        """停止中のテナントを再実行する場合は enabled=False を渡せ、既存レルムにも反映される。"""
        provision(server)
        provision(server, enabled=False)
        check.is_false(server.realms["tenant-alpha"].rep["enabled"])
        provision(server, enabled=True)
        check.is_true(server.realms["tenant-alpha"].rep["enabled"])

    def test_existing_matching_tenant_id_mapper_is_left_alone(self, server):
        """同じ tenant_id の既存マッパーは更新しない(PUT しない)。"""
        provision(server)
        provision(server)
        check.equal(server.writes_to("PUT", "protocol-mappers"), [])


class TestTenantRealmConflictOnCreate:
    """ensure_tenant_realm: 作成時に 409(並行実行で先に作成された)でも既存として扱い、最後まで収束する。"""

    @pytest.mark.parametrize(
        "path_regex",
        [r"/admin/realms$", r"/roles$", r"/clients$", r"/protocol-mappers/models$"],
        ids=["realm", "role", "client", "mapper"],
    )
    def test_conflict_is_treated_as_existing(self, server, path_regex):
        """レルム・ロール・クライアント・マッパーの作成が 409 を返しても例外にならず、完全なテンプレートが適用される。"""
        server.race_on_create("POST", path_regex)
        result = provision(server)
        check.equal([rule.used for rule in server.rules], [1], "409 を実際に返した")
        state = server.realms["tenant-alpha"]
        check.equal(result.realm_name, "tenant-alpha")
        check.is_in("tenant_admin", state.roles)
        check.equal(state.default_composites, ["member"])
        check.equal(login_client(state)["secret"], derive_client_secret(SEED, "tenant-alpha", "fastapi-app"))
        check.equal(set(mappers_of(state)), {"tenant_id", "audience"})
        check.equal(mappers_of(state)["tenant_id"]["config"]["claim.value"], str(TENANT_ID))

    def test_conflict_on_service_account_client(self, server):
        """tenant-user-admin の作成が 409 でも収束する(2 回目のクライアント作成)。"""
        server.race_on_create("POST", r"/clients$", times=2)
        provision(server)
        check.equal([rule.used for rule in server.rules], [2])
        state = server.realms["tenant-alpha"]
        check.is_not_none(login_client(state, TENANT_USER_ADMIN_CLIENT_ID))

    def test_other_errors_are_not_swallowed(self, server):
        """409 以外のエラー(500)は握りつぶさず KeycloakAdminError にする。"""
        server.fail("POST", r"/roles$", 500)
        with pytest.raises(KeycloakAdminError) as exc_info:
            provision(server)
        check.equal(exc_info.value.status_code, 500)


class TestTenantIdMapperGuard:
    """既存の tenant_id マッパーが別の値なら、上書きせず 409 で止まる。"""

    def test_different_tenant_id_stops_with_409(self, server):
        """同じレルムに別の tenant_id でテンプレートを適用すると KeycloakAdminError(409)。マッパーの値は変わらない。"""
        provision(server, tenant_id=TENANT_ID)
        with pytest.raises(KeycloakAdminError) as exc_info:
            provision(server, tenant_id=OTHER_TENANT_ID)
        check.equal(exc_info.value.status_code, 409)
        check.equal(mappers_of(server.realms["tenant-alpha"])["tenant_id"]["config"]["claim.value"], str(TENANT_ID))

    def test_stops_before_touching_mappers_and_later_steps(self, server):
        """食い違いを検出したら、マッパーの作成・更新も、tenant-user-admin の設定も行わない。"""
        provision(server, tenant_id=TENANT_ID)
        written_before = len(server.writes)
        with pytest.raises(KeycloakAdminError):
            provision(server, tenant_id=OTHER_TENANT_ID)
        new_writes = server.writes[written_before:]
        check.equal([w for w in new_writes if "protocol-mappers" in w[1]], [])
        check.equal([w for w in new_writes if "role-mappings" in w[1]], [])
        check.equal([w for w in new_writes if TENANT_USER_ADMIN_CLIENT_ID in json_text(w[2])], [])

    def test_error_message_does_not_reveal_the_other_tenant_id(self, server):
        """エラーのメッセージに、既存・指定どちらの tenant_id の値も含めない。"""
        provision(server, tenant_id=TENANT_ID)
        with pytest.raises(KeycloakAdminError) as exc_info:
            provision(server, tenant_id=OTHER_TENANT_ID)
        check.is_not_in(str(TENANT_ID), str(exc_info.value))
        check.is_not_in(str(OTHER_TENANT_ID), str(exc_info.value))

    def test_empty_existing_claim_value_is_filled(self, server):
        """既存マッパーの claim.value が空なら不一致扱いにせず、正しい値に更新する(PUT)。"""
        provision(server)
        mapper = mappers_of(server.realms["tenant-alpha"])["tenant_id"]
        mapper["config"]["claim.value"] = ""
        provision(server)
        check.equal(mappers_of(server.realms["tenant-alpha"])["tenant_id"]["config"]["claim.value"], str(TENANT_ID))


def json_text(value) -> str:
    return json.dumps(value, default=str)


class TestTenantRealmInputs:
    """入力の検証。検証に失敗したら Keycloak へ何も送らない。"""

    @pytest.mark.parametrize("tenant_code", ["", "ab", "ABC", "a--b", "-abc", "abc-", "abc\n", "a_b", "../x", None, 123])
    def test_invalid_tenant_code(self, server, tenant_code):
        """形式違反の tenant_code は ValueError で、リクエストを送らない。"""
        with pytest.raises(ValueError):
            provision(server, tenant_code=tenant_code)
        check.equal(server.requests, [])

    def test_tenant_realm_name(self):
        """レルム名は tenant-{tenant_code}。"""
        check.equal(tenant_realm_name("acme-1"), "tenant-acme-1")

    @pytest.mark.parametrize("tenant_id", ["not-a-uuid", "", None, 123])
    def test_invalid_tenant_id(self, server, tenant_id):
        """UUID でない tenant_id は ValueError で、リクエストを送らない。"""
        with pytest.raises((ValueError, TypeError, AttributeError)):
            provision(server, tenant_id=tenant_id)
        check.equal(server.requests, [])

    def test_string_uuid_is_accepted_and_normalized(self, server):
        """UUID の文字列(大文字)も受け付け、マッパーには小文字の正規形で入る。"""
        provision(server, tenant_id=str(TENANT_ID).upper())
        check.equal(mappers_of(server.realms["tenant-alpha"])["tenant_id"]["config"]["claim.value"], str(TENANT_ID))


class TestControlPlaneRealm:
    """ensure_control_plane_realm。"""

    def apply(self, server):
        with server.admin() as admin:
            return ensure_control_plane_realm(admin, settings=SETTINGS, secret_seed=SEED)

    def test_create(self, server):
        """control-plane レルムを作り、CP のロール(既定ロールには入れない)・CP のクライアント・audience マッパーを設定する。tenant_id マッパーは作らない。"""
        result = self.apply(server)
        check.equal((result.realm_name, result.created, result.login_client_id), ("control-plane", True, "fastapi-cp"))
        state = server.realms["control-plane"]
        check.is_in("saas_admin", state.roles)
        check.is_in("saas_viewer", state.roles)
        check.is_not_in("tenant_admin", state.roles)
        check.equal(state.default_composites, [])
        client = login_client(state, "fastapi-cp")
        check.equal(client["secret"], derive_client_secret(SEED, "control-plane", "fastapi-cp"))
        check.equal(client["attributes"]["post.logout.redirect.uris"], "http://app.test/cp/*")
        check.equal(set(mappers_of(state, "fastapi-cp")), {"audience"})

    def test_existing_is_idempotent(self, server):
        """再実行は何も作成せず、状態が変わらない。"""
        self.apply(server)
        before, posts = server.snapshot(), len(server.writes_to("POST", ".*"))
        result = self.apply(server)
        check.is_false(result.created)
        check.equal(server.snapshot(), before)
        check.equal(len(server.writes_to("POST", ".*")), posts)

    @pytest.mark.parametrize("path_regex", [r"/admin/realms$", r"/roles$", r"/clients$", r"/protocol-mappers/models$"])
    def test_conflict_on_create(self, server, path_regex):
        """作成時の 409 は既存として扱い、最後まで収束する。"""
        server.race_on_create("POST", path_regex)
        self.apply(server)
        check.equal([rule.used for rule in server.rules], [1], "409 を実際に返した")
        state = server.realms["control-plane"]
        check.is_in("saas_admin", state.roles)
        check.equal(set(mappers_of(state, "fastapi-cp")), {"audience"})


class TestTenantUser:
    """ensure_tenant_user。"""

    @pytest.fixture
    def realm(self, server):
        provision(server)
        return server.realms["tenant-alpha"]

    def ensure(self, server, **overrides) -> str:
        values = dict(realm_name="tenant-alpha", username="Alice", email="alice@example.com", first_name="Alice", last_name="Liddell", roles=["tenant_admin"], password=PASSWORD, temporary=True)
        values.update(overrides)
        with server.admin() as admin:
            return ensure_tenant_user(admin, **values)

    def test_create_new_user(self, server, realm):
        """無ければ作成する。メールは確認済み、一時パスワード(UPDATE_PASSWORD)、ロール付与。ユーザー名は小文字になる。"""
        user_id = self.ensure(server)
        user = realm.users[user_id]
        check.equal((user["username"], user["email"], user["firstName"], user["lastName"], user["emailVerified"], user["enabled"]), ("alice", "alice@example.com", "Alice", "Liddell", True, True))
        check.equal(realm.passwords[user_id], {"value": PASSWORD, "temporary": True})
        check.is_in("UPDATE_PASSWORD", user["requiredActions"])
        check.equal(realm.user_realm_roles[user_id], ["tenant_admin"])

    def test_non_temporary_password_has_no_required_action(self, server, realm):
        """temporary=False ならパスワードは恒久で、必須アクションを付けない。"""
        user_id = self.ensure(server, temporary=False)
        check.equal(realm.passwords[user_id]["temporary"], False)
        check.is_not_in("UPDATE_PASSWORD", realm.users[user_id].get("requiredActions", []))

    def test_existing_user_password_is_reset_every_time(self, server, realm):
        """既存ユーザーでもパスワードを毎回設定し直す(再実行で返す一時パスワードを有効にする)。ユーザーは再作成しない。"""
        first = self.ensure(server, password="First-Passw0rd!")
        second = self.ensure(server, password="Second-Passw0rd!")
        check.equal(first, second)
        check.equal(realm.passwords[first]["value"], "Second-Passw0rd!")
        check.equal(len(server.writes_to("POST", r"/users$")), 1)

    def test_existing_user_only_fills_empty_profile_fields(self, server, realm):
        """既存ユーザーはメール・姓・名のうち空の項目だけを埋め、既存の値は上書きしない。"""
        user_id = self.ensure(server, first_name="Original", last_name="Name")
        realm.users[user_id]["lastName"] = ""
        self.ensure(server, first_name="Changed", last_name="Filled", email="changed@example.com")
        user = realm.users[user_id]
        check.equal((user["firstName"], user["lastName"], user["email"]), ("Original", "Filled", "alice@example.com"))

    def test_roles_only_added_never_removed(self, server, realm):
        """ロールは不足分だけを追加し、余分なロールは外さない。"""
        user_id = self.ensure(server, roles=["member"])
        self.ensure(server, roles=["tenant_admin"])
        check.equal(sorted(realm.user_realm_roles[user_id]), ["member", "tenant_admin"])
        self.ensure(server, roles=["tenant_admin", "member"])
        check.equal(sorted(realm.user_realm_roles[user_id]), ["member", "tenant_admin"], "重複して付与しない")

    def test_conflict_on_create_is_treated_as_existing(self, server, realm):
        """作成時の 409(先に作成された)は既存ユーザーとして扱い、パスワードとロールを設定する。"""
        server.race_on_create("POST", r"/users$")
        user_id = self.ensure(server)
        check.equal([rule.used for rule in server.rules], [1], "409 を実際に返した")
        check.equal(realm.passwords[user_id]["value"], PASSWORD)
        check.equal(realm.user_realm_roles[user_id], ["tenant_admin"])
        check.equal(len(realm.users), 2, "サービスアカウントのユーザー + Alice")

    def test_duplicate_email_conflict_is_an_error(self, server, realm):
        """別ユーザー名で同じメールを使うと 409 で、既存ユーザーとして扱えないため KeycloakAdminError にする。"""
        self.ensure(server, username="alice")
        with pytest.raises(KeycloakAdminError) as exc_info:
            self.ensure(server, username="bob")
        check.equal(exc_info.value.status_code, 409)

    @pytest.mark.parametrize("field", ["username", "email", "first_name", "last_name", "password"])
    def test_required_fields(self, server, field):
        """ユーザー名・メール・姓・名・パスワードが空なら ValueError で、Keycloak へ何も送らない。"""
        with pytest.raises(ValueError):
            self.ensure(server, **{field: ""})
        check.equal(server.requests, [])

    def test_invalid_realm_name(self, server):
        """不正なレルム名は ValueError。"""
        with pytest.raises(ValueError):
            self.ensure(server, realm_name="bad realm/../")
        check.equal(server.requests, [])

    def test_missing_realm_role_is_an_error(self, server, realm):
        """存在しないロールの付与は KeycloakAdminError(404)。"""
        with pytest.raises(KeycloakAdminError) as exc_info:
            self.ensure(server, roles=["no_such_role"])
        check.equal(exc_info.value.status_code, 404)

    def test_password_is_not_exposed_in_errors(self, server, realm):
        """パスワード設定の失敗(ポリシー違反)でも、例外にパスワードの値を含めない。"""
        server.fail("PUT", r"/reset-password$", 400)
        with pytest.raises(KeycloakAdminError) as exc_info:
            self.ensure(server)
        check.is_not_in(PASSWORD, str(exc_info.value))
        check.is_not_in(PASSWORD, repr(exc_info.value))

    def test_works_for_control_plane_users(self, server):
        """control-plane レルムのユーザーにも使える。"""
        with server.admin() as admin:
            ensure_control_plane_realm(admin, settings=SETTINGS, secret_seed=SEED)
        user_id = self.ensure(server, realm_name="control-plane", username="cp-admin", email="cp-admin@example.com", roles=["saas_admin"], temporary=False)
        check.equal(server.realms["control-plane"].user_realm_roles[user_id], ["saas_admin"])


class TestRealmEnabledAndDeletion:
    """停止・再開・物理削除。"""

    def test_set_realm_enabled_switches_and_is_idempotent(self, server):
        """停止・再開で enabled が切り替わり、既に指定の状態なら書き込まない。"""
        provision(server)
        with server.admin() as admin:
            set_realm_enabled(admin, "tenant-alpha", False)
            check.is_false(server.realms["tenant-alpha"].rep["enabled"])
            writes = len(server.writes)
            set_realm_enabled(admin, "tenant-alpha", False)
            check.equal(len(server.writes), writes, "既に無効なら何もしない")
            set_realm_enabled(admin, "tenant-alpha", True)
            check.is_true(server.realms["tenant-alpha"].rep["enabled"])

    def test_set_realm_enabled_on_missing_realm(self, server):
        """存在しないレルムの停止は KeycloakAdminError(404)。"""
        with server.admin() as admin, pytest.raises(KeycloakAdminError) as exc_info:
            set_realm_enabled(admin, "tenant-ghost", False)
        check.equal(exc_info.value.status_code, 404)

    def test_delete_existing_realm(self, server):
        """存在するレルムを削除すると True を返し、レルムが消える。"""
        provision(server)
        with server.admin() as admin:
            check.is_true(delete_realm_if_exists(admin, "tenant-alpha"))
        check.is_not_in("tenant-alpha", server.realms)

    def test_delete_missing_realm_is_idempotent(self, server):
        """無いレルムの削除は False を返し、例外にならない(再実行できる)。"""
        with server.admin() as admin:
            check.is_false(delete_realm_if_exists(admin, "tenant-ghost"))

    def test_delete_twice(self, server):
        """続けて 2 回削除すると、1 回目は True、2 回目は False。"""
        provision(server)
        with server.admin() as admin:
            results = [delete_realm_if_exists(admin, "tenant-alpha"), delete_realm_if_exists(admin, "tenant-alpha")]
        check.equal(results, [True, False])

    def test_master_realm_is_never_deleted(self, server):
        """master は ValueError で拒否し、Keycloak へ削除リクエストを送らない。"""
        with server.admin() as admin, pytest.raises(ValueError):
            delete_realm_if_exists(admin, "master")
        check.equal(server.requests, [])

    @pytest.mark.parametrize("name", ["", "bad realm", "../master", "a/b", "tenant-x\n"])
    def test_invalid_realm_name_is_rejected(self, server, name):
        """不正なレルム名(パス区切りなど)の削除は ValueError で、リクエストを送らない。"""
        with server.admin() as admin, pytest.raises(ValueError):
            delete_realm_if_exists(admin, name)
        check.equal(server.requests, [])

    def test_delete_failure_is_raised(self, server):
        """削除が 500 で失敗したら KeycloakAdminError を送出する(呼び出し側が失敗として記録できる)。"""
        provision(server)
        server.fail("DELETE", r"/tenant-alpha$", 500)
        with server.admin() as admin, pytest.raises(KeycloakAdminError):
            delete_realm_if_exists(admin, "tenant-alpha")
        check.is_in("tenant-alpha", server.realms)


class TestProvisionerAdminClient:
    """create_provisioner_admin_client: 環境ごとの資格情報。"""

    def test_development_uses_password_grant(self, monkeypatch):
        """開発環境は master / admin-cli のパスワードグラント。"""
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "dev-admin-pw")
        with create_provisioner_admin_client() as admin:
            check.is_instance(admin.token_provider, PasswordGrantTokenProvider)

    def test_production_uses_client_credentials_without_admin_password(self, monkeypatch):
        """本番相当の環境は cp-provisioner のクライアントクレデンシャルで、管理ユーザーのパスワードは不要。"""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("KEYCLOAK_PROVISIONER_CLIENT_SECRET", "provisioner-secret")
        monkeypatch.delenv("KEYCLOAK_ADMIN_PASSWORD", raising=False)
        with create_provisioner_admin_client() as admin:
            check.is_instance(admin.token_provider, ClientCredentialsTokenProvider)
            check.equal(admin.token_provider.client_id, "cp-provisioner")

    def test_production_client_id_is_configurable(self, monkeypatch):
        """クライアント ID は KEYCLOAK_PROVISIONER_CLIENT_ID で変えられる。"""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("KEYCLOAK_PROVISIONER_CLIENT_ID", "my-provisioner")
        monkeypatch.setenv("KEYCLOAK_PROVISIONER_CLIENT_SECRET", "provisioner-secret")
        with create_provisioner_admin_client() as admin:
            check.equal(admin.token_provider.client_id, "my-provisioner")

    def test_production_without_secret_names_only_the_variable(self, monkeypatch):
        """本番相当でシークレット未設定なら RuntimeError。メッセージには変数名だけを含み、値を含めない。"""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "admin-pw-should-not-leak")
        monkeypatch.delenv("KEYCLOAK_PROVISIONER_CLIENT_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="KEYCLOAK_PROVISIONER_CLIENT_SECRET") as exc_info:
            create_provisioner_admin_client()
        check.is_not_in("admin-pw-should-not-leak", str(exc_info.value))

    def test_deadline_is_thirty_seconds_by_default(self, monkeypatch):
        """締め切りの既定は 30 秒。"""
        monkeypatch.setenv("APP_ENV", "development")
        with create_provisioner_admin_client() as admin:
            deadline_left = admin._deadline - admin._clock()
        check.is_true(29.0 < deadline_left <= 30.0)
