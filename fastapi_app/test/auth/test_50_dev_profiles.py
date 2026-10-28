# -*- coding: utf-8 -*-
"""modules.auth.dev_profiles(開発用の認証情報の唯一の定義)のテスト。"""
import dataclasses

import pytest
import pytest_check as check

from modules.auth import dev_profiles
from modules.auth.dev_profiles import ALPHA, BETA, DEV_CP_USERS, DEV_PROFILES, DEV_TENANT_USERS, DEV_TENANTS, DEV_USERS, DevTenant, DevUser, require_development_environment
from modules.auth.plane import CP_REALM_NAME, PLANE_ROLES, Plane

PLAIN_PASSWORD = "Dev-Passw0rd!"


def _user(**overrides) -> DevUser:
    values = dict(plane=Plane.APP, realm="tenant-alpha", tenant_code="alpha", username="u1", email="u1@example.com", first_name="U", last_name="One", roles=("member",))
    values.update(overrides)
    return DevUser(**values)


class TestPasswordOnlyInDevelopment:
    """APP_ENV=development 以外では password が RuntimeError。"""

    @pytest.mark.parametrize("app_env", ["production", "staging", "test", "prod", "Production", "", "developmentx", "dev"])
    def test_password_is_refused_outside_development(self, monkeypatch, app_env):
        """APP_ENV が development 以外(未知の値・空文字を含む)なら、開発用パスワードを返さず RuntimeError にする。"""
        monkeypatch.setenv("APP_ENV", app_env)
        with pytest.raises(RuntimeError) as exc_info:
            _ = DEV_PROFILES["alpha-admin"].password
        check.is_not_in(PLAIN_PASSWORD, str(exc_info.value))

    @pytest.mark.parametrize("app_env", ["development", "Development", " development "])
    def test_password_is_returned_in_development(self, monkeypatch, app_env):
        """APP_ENV=development(大文字小文字・前後の空白は無視)なら開発用パスワードを返す。"""
        monkeypatch.setenv("APP_ENV", app_env)
        check.equal(DEV_PROFILES["alpha-admin"].password, PLAIN_PASSWORD)

    def test_unset_app_env_defaults_to_development(self, monkeypatch):
        """APP_ENV が未設定なら development として扱う(環境変数の既定値)。"""
        monkeypatch.delenv("APP_ENV", raising=False)
        check.equal(DEV_PROFILES["cp-admin"].password, PLAIN_PASSWORD)

    @pytest.mark.parametrize("user", DEV_USERS, ids=lambda u: u.username)
    def test_every_user_is_guarded(self, monkeypatch, user):
        """シード対象のすべてのユーザーで、development 以外では password を取れない。"""
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(RuntimeError):
            _ = user.password

    def test_require_development_environment_message_has_no_secret(self, monkeypatch):
        """拒否のメッセージには APP_ENV の値だけを含み、パスワードを含まない。"""
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(RuntimeError, match="APP_ENV=production") as exc_info:
            require_development_environment()
        check.is_not_in(PLAIN_PASSWORD, str(exc_info.value))

    def test_password_is_not_in_repr_or_comparison(self):
        """パスワードの値は repr に出ず、等価比較にも使われない。"""
        user = DEV_PROFILES["alpha-admin"]
        check.is_not_in(PLAIN_PASSWORD, repr(user))
        check.is_true(dataclasses.replace(user, dev_password="other") == user)


class TestDefinitions:
    """シード対象・プロファイル定義の整合。"""

    def test_dev_tenants_are_the_seeded_alpha_and_beta(self):
        """開発用テナントは alpha / beta で、レルム名は tenant-{code}。"""
        check.equal([t.tenant_code for t in DEV_TENANTS], ["alpha", "beta"])
        check.equal((ALPHA.realm_name, BETA.realm_name), ("tenant-alpha", "tenant-beta"))

    def test_each_tenant_has_one_admin_and_two_members(self):
        """各テナントに tenant_admin 1・member 2 のユーザーがいる(02 §7.1)。"""
        for tenant in DEV_TENANTS:
            users = DEV_TENANT_USERS[tenant.tenant_code]
            roles = sorted(role for user in users for role in user.roles)
            check.equal(roles, ["member", "member", "tenant_admin"], tenant.tenant_code)
            check.is_true(all(user.realm == tenant.realm_name and user.tenant_code == tenant.tenant_code for user in users))

    def test_cp_users(self):
        """CP のユーザーは control-plane レルムで、saas_admin / saas_viewer を 1 人ずつ持つ。"""
        check.equal(sorted(role for user in DEV_CP_USERS for role in user.roles), ["saas_admin", "saas_viewer"])
        check.is_true(all(user.realm == CP_REALM_NAME and user.plane == Plane.CP and user.tenant_code is None for user in DEV_CP_USERS))

    def test_profiles_reference_seeded_users(self):
        """開発用ログインのプロファイルは、シード対象のユーザーだけを指す(シードされないユーザーでログインさせない)。"""
        check.equal(set(DEV_PROFILES), {"cp-admin", "cp-viewer", "alpha-admin", "alpha-member", "beta-member"})
        for name, user in DEV_PROFILES.items():
            check.is_in(user, DEV_USERS)
            check.equal(user.username, name)

    def test_usernames_and_emails_are_unique(self):
        """ユーザー名とメールアドレスは重複しない(レルムをまたいで一意)。"""
        check.equal(len({u.username for u in DEV_USERS}), len(DEV_USERS))
        check.equal(len({u.email for u in DEV_USERS}), len(DEV_USERS))

    def test_profile_fields_are_complete(self):
        """Keycloak の既定のユーザープロフィールで必須のメール・姓・名がすべて埋まっていて、ロールはプレーンの許可リスト内。"""
        for user in DEV_USERS:
            check.is_true(user.email.endswith("@example.com"), user.username)
            check.is_true(user.first_name and user.last_name, user.username)
            check.is_true(set(user.roles) <= PLANE_ROLES[user.plane], user.username)


class TestValidation:
    """定義時の誤りの検出。"""

    def test_valid_user(self):
        """正しい組み合わせは作れる。"""
        check.equal(_user().realm, "tenant-alpha")

    @pytest.mark.parametrize(
        "overrides",
        [
            {"realm": "tenant-beta"},  # tenant_code と食い違うレルム
            {"realm": CP_REALM_NAME},  # AP なのに control-plane
            {"tenant_code": None},
            {"tenant_code": "Alpha"},
            {"plane": Plane.CP},  # CP なのにテナントレルム
            {"roles": ()},
            {"roles": ("saas_admin",)},  # AP のユーザーに CP のロール
            {"roles": ("member", "unknown")},
            {"email": ""},
            {"first_name": ""},
            {"last_name": ""},
            {"username": ""},
            {"realm": "bad realm"},
        ],
    )
    def test_invalid_combinations_are_rejected(self, overrides):
        """プレーン・レルム・テナントコード・ロール・必須項目の矛盾は ValueError にする。"""
        with pytest.raises(ValueError):
            _user(**overrides)

    def test_cp_user_must_not_have_tenant_code(self):
        """CP のユーザーに tenant_code は付けられない。"""
        with pytest.raises(ValueError):
            _user(plane=Plane.CP, realm=CP_REALM_NAME, roles=("saas_admin",), tenant_code="alpha")

    @pytest.mark.parametrize("code", ["ab", "Abc", "a--b", "abc\n", ""])
    def test_dev_tenant_code_format_is_validated(self, code):
        """開発用テナントのコードは 01 §5.1 の形式でなければならない。"""
        with pytest.raises(ValueError):
            DevTenant(tenant_code=code, display_name="X")

    def test_module_exposes_single_default_profile(self):
        """既定のプロファイルは DEV_PROFILES に存在する。"""
        check.is_in(dev_profiles.DEFAULT_DEV_PROFILE, DEV_PROFILES)
