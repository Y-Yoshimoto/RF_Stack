#!/usr/bin/env python
# coding:utf-8
"""開発用ログインバイパスのユニットテスト。

KeyCloak への通信を伴う部分は対象外とし、有効/無効の判定と
入力検証（プロファイル・遷移先）を検証する。
"""
import pytest

from main_app.route.auth import dev_login
from modules.auth import dev_profiles
from modules.auth.environment import KeyCloakEnvironmentVariables
from modules.auth.plane import Plane

# ------------------------------------------------ 有効/無効の判定


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", "on"])
def test_dev_login_enabled_in_development(monkeypatch, value):
    """development かつ明示的に有効化された場合のみ有効になること。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", value)

    assert KeyCloakEnvironmentVariables().is_dev_login_enabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no"])
def test_dev_login_disabled_without_opt_in(monkeypatch, value):
    """明示的に有効化しない限り無効であること。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", value)

    assert KeyCloakEnvironmentVariables().is_dev_login_enabled() is False


def test_dev_login_disabled_in_production(monkeypatch):
    """本番環境では有効化を要求されても無効であること。"""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", "true")

    assert KeyCloakEnvironmentVariables().is_dev_login_enabled() is False


def test_validate_dev_login_raises_in_production(monkeypatch):
    """本番環境で有効化を要求された場合は起動を止めること。"""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", "true")

    with pytest.raises(RuntimeError, match="AUTH_DEV_LOGIN_ENABLED"):
        KeyCloakEnvironmentVariables().validate_dev_login()


def test_validate_dev_login_passes_in_development(monkeypatch):
    """開発環境では有効化されていても起動を妨げないこと。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_DEV_LOGIN_ENABLED", "true")

    KeyCloakEnvironmentVariables().validate_dev_login()


# ------------------------------------------------------ 遷移先の検証


@pytest.mark.parametrize("path", ["/button", "/fetch", "/", "/a/b?c=d"])
def test_validate_next_path_accepts_paths(path):
    """同一オリジン内のパスは許可されること。"""
    assert dev_login._validate_next_path(path) == path


@pytest.mark.parametrize(
    "path",
    ["https://evil.example.com", "//evil.example.com", "/\\evil.example.com", "http://localhost:5173/button", "button", ""],
)
def test_validate_next_path_rejects_external(path):
    """絶対 URL / プロトコル相対 URL は拒否すること(オープンリダイレクト防止)。"""
    if path == "":
        # 空文字は既定値にフォールバックする
        assert dev_login._validate_next_path(path) == dev_login.DEFAULT_NEXT_PATH
        return
    with pytest.raises(ValueError):
        dev_login._validate_next_path(path)


# -------------------------------------------------------- プロファイル


def _user(plane, realm, tenant_code=None, roles=("member",)):
    """テスト用の DevUser を作る。"""
    return dev_profiles.DevUser(plane=plane, realm=realm, tenant_code=tenant_code, username="u", email="u@example.com", first_name="U", last_name="Ser", roles=roles)


def test_profiles_match_spec():
    """02 §7.2 の表のプロファイルが定義され、旧 default (tenant-a) が無いこと。"""
    assert set(dev_profiles.DEV_PROFILES) == {"cp-admin", "cp-viewer", "alpha-admin", "alpha-member", "beta-member"}
    assert dev_profiles.DEFAULT_DEV_PROFILE in dev_profiles.DEV_PROFILES
    assert dev_profiles.DEV_PROFILES["cp-admin"].plane == Plane.CP
    assert dev_profiles.DEV_PROFILES["alpha-admin"].tenant_code == "alpha"
    assert dev_profiles.DEV_PROFILES["alpha-admin"].roles == ("tenant_admin",)
    assert all(user.realm != "tenant-a" for user in dev_profiles.DEV_USERS)


def test_each_tenant_has_one_admin_and_two_members():
    """各テナントに tenant_admin 1・member 2 がシード対象として定義されていること (02 §7.1)。"""
    assert [tenant.tenant_code for tenant in dev_profiles.DEV_TENANTS] == ["alpha", "beta"]
    for tenant in dev_profiles.DEV_TENANTS:
        roles = [user.roles for user in dev_profiles.DEV_TENANT_USERS[tenant.tenant_code]]
        assert roles.count(("tenant_admin",)) == 1
        assert roles.count(("member",)) == 2


def test_password_only_in_development(monkeypatch):
    """開発用パスワードは APP_ENV=development 以外では返さないこと。"""
    profile = dev_profiles.DEV_PROFILES["alpha-admin"]
    monkeypatch.setenv("APP_ENV", "development")
    assert profile.password
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError):
        _ = profile.password


def test_profile_repr_hides_password(monkeypatch):
    """プロファイルの repr にパスワードが出ないこと。"""
    monkeypatch.setenv("APP_ENV", "development")
    profile = dev_profiles.DEV_PROFILES["alpha-admin"]
    assert profile.password not in repr(profile)


@pytest.mark.parametrize(
    ("plane", "realm", "tenant_code"),
    [(Plane.CP, "tenant-alpha", None), (Plane.APP, "control-plane", None), (Plane.APP, "bad realm", "bad"), (Plane.APP, "tenant-alpha", "beta"), (Plane.APP, "tenant-a", "a")],
)
def test_profile_rejects_plane_realm_mismatch(plane, realm, tenant_code):
    """プレーン・レルム・テナントコードの組み合わせが合わないプロファイルは定義時に拒否すること。"""
    with pytest.raises(ValueError):
        _user(plane, realm, tenant_code)


def test_profile_rejects_role_of_other_plane():
    """プレーンの許可リストに無いロールは定義時に拒否すること。"""
    with pytest.raises(ValueError):
        _user(Plane.APP, "tenant-alpha", "alpha", roles=("saas_admin",))


def test_cp_profile_has_no_tenant_code():
    """CP のプロファイルはテナントコードを持たず、既定の遷移先は /cp/ であること。"""
    profile = dev_profiles.DEV_PROFILES["cp-admin"]
    assert profile.tenant_code is None
    assert dev_login.DEFAULT_NEXT_PATHS[profile.plane] == "/cp/"
