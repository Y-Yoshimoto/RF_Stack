"""Keycloak Admin REST API の冪等な操作部品 (FastAPI 非依存)。

コントロールプレーンによるテナント払い出し (レルム・クライアント・ロール・ユーザーの作成) と、
開発用 CLI (``python -m modules.keycloak_admin.cli``) の両方から使う。

構成:
    - :mod:`.settings` — 環境変数からの接続設定
    - :mod:`.token_provider` — 管理トークンの取得 (パスワードグラント / クライアントクレデンシャル。差し替え可能)
    - :mod:`.admin_client` — HTTP クライアント (タイムアウト・締め切り・401 再試行)
    - :mod:`.realms` / :mod:`.clients` / :mod:`.users` / :mod:`.roles` — 冪等な ensure 系関数
    - :mod:`.client_secret` — クライアントシークレットの導出 (``KC_CLIENT_SECRET_SEED`` + HMAC-SHA256)
    - :mod:`.provisioning` — ensure 関数を組み合わせた手順 (旧シェルスクリプト相当)
    - :mod:`.templates` — レルムのテンプレート (テナントレルム・control-plane)、ユーザー、停止・削除、払い出し用・ユーザー管理用の管理クライアント
    - :mod:`.tenant_users` — AP のユーザー管理 (``tenant-user-admin`` の権限で動く作成・無効化・ロール変更)
    - :mod:`.cli` — 旧 ``setup_realm_client_user.sh`` 相当の CLI

使用例::

    from modules.keycloak_admin import KeycloakAdminClient, ensure_realm, ensure_realm_role

    with KeycloakAdminClient.from_env() as admin:
        ensure_realm(admin, "tenant-a")
        ensure_realm_role(admin, "tenant-a", "tenant_admin")
"""
from .admin_client import KeycloakAdminClient
from .client_secret import client_secret_seed_from_env, derive_client_secret
from .clients import (
    audience_mapper,
    ensure_client,
    ensure_protocol_mapper,
    find_client,
    get_client_secret,
    get_service_account_user_id,
    hardcoded_claim_mapper,
    require_client_internal_id,
)
from .errors import KeycloakAdminAuthError, KeycloakAdminConnectionError, KeycloakAdminError, KeycloakAdminTimeoutError
from .models import (
    ClientResult,
    ClientSpec,
    ControlPlaneRealmResult,
    ProtocolMapperResult,
    ProtocolMapperSpec,
    RealmResult,
    RealmSpec,
    RoleResult,
    SetupResult,
    TenantRealmResult,
    UserResult,
    UserSpec,
)
from .provisioning import build_app_client_spec, setup_realm_client_user
from .realms import delete_realm_if_exists, ensure_realm, get_realm, set_realm_enabled, validate_realm_name
from .roles import ensure_default_realm_roles, ensure_realm_role, ensure_user_client_roles, ensure_user_realm_roles, get_realm_role
from .settings import AppClientSettings, KeycloakAdminSettings, PlatformClientSettings
from .templates import create_provisioner_admin_client, create_tenant_user_admin_client, ensure_control_plane_realm, ensure_tenant_realm, ensure_tenant_user, tenant_realm_name
from .token_provider import AdminTokenProvider, ClientCredentialsTokenProvider, PasswordGrantTokenProvider
from .users import ensure_user, find_user, set_user_password

__all__ = [
    "AdminTokenProvider",
    "AppClientSettings",
    "ClientCredentialsTokenProvider",
    "ClientResult",
    "ClientSpec",
    "ControlPlaneRealmResult",
    "KeycloakAdminAuthError",
    "KeycloakAdminClient",
    "KeycloakAdminConnectionError",
    "KeycloakAdminError",
    "KeycloakAdminSettings",
    "KeycloakAdminTimeoutError",
    "PasswordGrantTokenProvider",
    "PlatformClientSettings",
    "ProtocolMapperResult",
    "ProtocolMapperSpec",
    "RealmResult",
    "RealmSpec",
    "RoleResult",
    "SetupResult",
    "TenantRealmResult",
    "UserResult",
    "UserSpec",
    "audience_mapper",
    "build_app_client_spec",
    "client_secret_seed_from_env",
    "create_provisioner_admin_client",
    "create_tenant_user_admin_client",
    "delete_realm_if_exists",
    "derive_client_secret",
    "ensure_client",
    "ensure_control_plane_realm",
    "ensure_default_realm_roles",
    "ensure_protocol_mapper",
    "ensure_realm",
    "ensure_realm_role",
    "ensure_tenant_realm",
    "ensure_tenant_user",
    "ensure_user",
    "ensure_user_client_roles",
    "ensure_user_realm_roles",
    "find_client",
    "find_user",
    "get_client_secret",
    "get_realm",
    "get_realm_role",
    "get_service_account_user_id",
    "hardcoded_claim_mapper",
    "require_client_internal_id",
    "set_realm_enabled",
    "set_user_password",
    "setup_realm_client_user",
    "tenant_realm_name",
    "validate_realm_name",
]
