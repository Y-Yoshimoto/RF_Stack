"""Keycloak Admin REST API の冪等な操作部品 (FastAPI 非依存)。

コントロールプレーンによるテナント払い出し (レルム・クライアント・ロール・ユーザーの作成) と、
開発用 CLI (``python -m modules.keycloak_admin.cli``) の両方から使う。

構成:
    - :mod:`.settings` — 環境変数からの接続設定
    - :mod:`.token_provider` — 管理トークンの取得 (パスワードグラント / クライアントクレデンシャル。差し替え可能)
    - :mod:`.admin_client` — HTTP クライアント (タイムアウト・締め切り・401 再試行)
    - :mod:`.realms` / :mod:`.clients` / :mod:`.users` / :mod:`.roles` — 冪等な ensure 系関数
    - :mod:`.provisioning` — ensure 関数を組み合わせた手順
    - :mod:`.cli` — 旧 ``setup_realm_client_user.sh`` 相当の CLI

使用例::

    from modules.keycloak_admin import KeycloakAdminClient, ensure_realm, ensure_realm_role

    with KeycloakAdminClient.from_env() as admin:
        ensure_realm(admin, "tenant-a")
        ensure_realm_role(admin, "tenant-a", "tenant_admin")
"""
from .admin_client import KeycloakAdminClient
from .clients import audience_mapper, ensure_client, ensure_protocol_mapper, find_client, get_client_secret, hardcoded_claim_mapper
from .errors import KeycloakAdminAuthError, KeycloakAdminConnectionError, KeycloakAdminError, KeycloakAdminTimeoutError
from .models import (
    ClientResult,
    ClientSpec,
    ProtocolMapperResult,
    ProtocolMapperSpec,
    RealmResult,
    RealmSpec,
    RoleResult,
    SetupResult,
    UserResult,
    UserSpec,
)
from .provisioning import build_app_client_spec, setup_realm_client_user
from .realms import ensure_realm, get_realm, validate_realm_name
from .roles import ensure_realm_role, get_realm_role
from .settings import AppClientSettings, KeycloakAdminSettings
from .token_provider import AdminTokenProvider, ClientCredentialsTokenProvider, PasswordGrantTokenProvider
from .users import ensure_user, find_user, set_user_password

__all__ = [
    "AdminTokenProvider",
    "AppClientSettings",
    "ClientCredentialsTokenProvider",
    "ClientResult",
    "ClientSpec",
    "KeycloakAdminAuthError",
    "KeycloakAdminClient",
    "KeycloakAdminConnectionError",
    "KeycloakAdminError",
    "KeycloakAdminSettings",
    "KeycloakAdminTimeoutError",
    "PasswordGrantTokenProvider",
    "ProtocolMapperResult",
    "ProtocolMapperSpec",
    "RealmResult",
    "RealmSpec",
    "RoleResult",
    "SetupResult",
    "UserResult",
    "UserSpec",
    "audience_mapper",
    "build_app_client_spec",
    "ensure_client",
    "ensure_protocol_mapper",
    "ensure_realm",
    "ensure_realm_role",
    "ensure_user",
    "find_client",
    "find_user",
    "get_client_secret",
    "get_realm",
    "get_realm_role",
    "hardcoded_claim_mapper",
    "set_user_password",
    "setup_realm_client_user",
    "validate_realm_name",
]
