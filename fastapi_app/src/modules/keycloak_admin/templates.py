"""レルムのテンプレート (02 §3.1 / §3.2) を冪等に適用する関数群。

テナントの払い出し・停止・再開・削除 (CP の払い出しサービス) と、開発用シード (CLI) の両方が使う。
**払い出しとシードで同じ関数を使い、Keycloak を直接いじる別経路を持たない** (02 §7.1)。

============================== =====================================================================
関数                           内容
============================== =====================================================================
:func:`ensure_tenant_realm`    レルム ``tenant-{tenant_code}``・ロール・``fastapi-app``・マッパー・``tenant-user-admin``
:func:`ensure_control_plane_realm` レルム ``control-plane``・ロール ``saas_admin`` / ``saas_viewer``・``fastapi-cp``
:func:`ensure_tenant_user`     ユーザー (メール・姓・名必須)・パスワード・レルムロール
:func:`set_realm_enabled`      停止・再開 (:mod:`.realms` の関数)
:func:`delete_realm_if_exists` 物理削除 (:mod:`.realms` の関数)
:func:`create_provisioner_admin_client` 払い出し用の管理クライアント
:func:`create_tenant_user_admin_client` AP のユーザー管理用の管理クライアント (``tenant-user-admin``)
============================== =====================================================================

いずれも「無ければ作成、あれば設定を反映」で収束する。再実行しても同じ状態になる。

秘匿値の扱い:
    クライアントシークレットは ``KC_CLIENT_SECRET_SEED`` から導出して設定する (02 §3.3)。戻り値には含めない。
    ユーザーのパスワードはログ・例外メッセージ・戻り値に含めない。

使用例::

    with create_provisioner_admin_client() as admin:
        result = ensure_tenant_realm(admin, tenant_code="alpha", tenant_id=tenant_id, display_name="Alpha")
        ensure_tenant_user(admin, realm_name=result.realm_name, username="alice", email="alice@example.com",
                           first_name="Alice", last_name="Liddell", roles=["tenant_admin"], password=temp_password, temporary=True)
"""
import dataclasses
import logging
import os
import re
import uuid
from collections.abc import Sequence

from .admin_client import KeycloakAdminClient
from .client_secret import client_secret_seed_from_env, derive_client_secret
from .clients import (
    audience_mapper,
    ensure_client,
    ensure_protocol_mapper,
    get_service_account_user_id,
    hardcoded_claim_mapper,
    list_protocol_mappers,
    require_client_internal_id,
)
from .errors import KeycloakAdminError
from .models import ClientSpec, ControlPlaneRealmResult, RealmSpec, TenantRealmResult, UserSpec
from .realms import delete_realm_if_exists, ensure_realm, set_realm_enabled, validate_realm_name
from .roles import ensure_default_realm_roles, ensure_realm_role, ensure_user_client_roles, ensure_user_realm_roles
from .settings import KeycloakAdminSettings, PlatformClientSettings
from .token_provider import ClientCredentialsTokenProvider
from .users import ensure_user, set_user_password

logger = logging.getLogger(__name__)

__all__ = [
    "CONTROL_PLANE_REALM_NAME",
    "CP_ROLES",
    "TENANT_ROLES",
    "TENANT_USER_ADMIN_CLIENT_ID",
    "TENANT_USER_ADMIN_ROLES",
    "create_provisioner_admin_client",
    "create_tenant_user_admin_client",
    "delete_realm_if_exists",
    "ensure_control_plane_realm",
    "ensure_tenant_realm",
    "ensure_tenant_user",
    "set_realm_enabled",
    "tenant_realm_name",
]

# --------------------------------------------------------------------------- 定数

# テナントレルム名の接頭辞 (``tenant-{tenant_code}``)。modules.auth.plane.TENANT_REALM_PREFIX と同じ値。
TENANT_REALM_PREFIX = "tenant-"

# CP のレルム名。modules.auth.plane.CP_REALM_NAME と同じ値。
CONTROL_PLANE_REALM_NAME = "control-plane"

# tenant_code の形式 (01 §5.1)。modules.auth.plane.TENANT_CODE_PATTERN と同じ。
# 本パッケージは FastAPI に依存しないため modules.auth を import せず、同じ式を持つ。
# 予約語 (01 §5.2) の判定は呼び出し側 (払い出しサービス) が行う。
TENANT_CODE_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){2,31}")

# レルムロール (01 §7.5)。
TENANT_ROLES = ("tenant_admin", "member")
TENANT_DEFAULT_ROLES = ("member",)
CP_ROLES = ("saas_admin", "saas_viewer")

_ROLE_DESCRIPTIONS = {
    "tenant_admin": "テナント管理者",
    "member": "テナントの一般ユーザー",
    "saas_admin": "SaaS 管理者 (参照・変更)",
    "saas_viewer": "SaaS 閲覧者 (参照のみ)",
}

# ユーザー管理用サービスアカウント (02 §3.1)。
TENANT_USER_ADMIN_CLIENT_ID = "tenant-user-admin"
# realm-management のクライアントロールのうち付与するもの。ユーザーの作成・無効化と一覧取得に必要な最小限。
# manage-realm / manage-clients など、テナント識別用のマッパーやクライアントを変更できるロールは付与しない (01 §7.1)。
TENANT_USER_ADMIN_ROLES = ("manage-users", "view-users", "query-users")
REALM_MANAGEMENT_CLIENT_ID = "realm-management"

# マッパー名。クライアント内で一意。
TENANT_ID_CLAIM = "tenant_id"
TENANT_ID_MAPPER_NAME = "tenant_id"
AUDIENCE_MAPPER_NAME = "audience"

# テナントレルム・control-plane 共通のレルム設定 (02 §3.2)。
_COMMON_REALM_SETTINGS = {
    "duplicateEmailsAllowed": False,
    "loginWithEmailAllowed": True,
    "registrationAllowed": False,
    "resetPasswordAllowed": False,
    "bruteForceProtected": True,
}

# 払い出し用の管理クライアント (02 §3.1 の cp-provisioner)。
PROVISIONER_CLIENT_ID_ENV = "KEYCLOAK_PROVISIONER_CLIENT_ID"
PROVISIONER_CLIENT_SECRET_ENV = "KEYCLOAK_PROVISIONER_CLIENT_SECRET"
DEFAULT_PROVISIONER_CLIENT_ID = "cp-provisioner"

# PKCE の方式 (modules.auth.token.CODE_CHALLENGE_METHOD と同じ)。
PKCE_METHOD = "S256"


# --------------------------------------------------------------------------- 補助


def tenant_realm_name(tenant_code: str) -> str:
    """tenant_code を検証し、テナントレルム名 (``tenant-{tenant_code}``) を返す。

    Args:
        tenant_code: テナントコード (01 §5.1 の形式)。

    Returns:
        str: レルム名。

    Raises:
        ValueError: tenant_code が形式に合わない場合。
    """
    if not isinstance(tenant_code, str) or not TENANT_CODE_PATTERN.fullmatch(tenant_code):
        raise ValueError("tenant_code must match ^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){2,31}$")
    return validate_realm_name(f"{TENANT_REALM_PREFIX}{tenant_code}")


def _login_client_spec(client_id: str, realm: str, seed: str, settings: PlatformClientSettings, post_logout_path: str) -> ClientSpec:
    """BFF のログイン用 confidential クライアント (Standard Flow + PKCE) の仕様を作る。

    Args:
        client_id: クライアント ID。
        realm: レルム名 (シークレットの導出に使う)。
        seed: シークレット導出用のシード。
        settings: URL 等の設定。
        post_logout_path: ログアウト後の遷移先として許可するパス (例: ``/alpha/*``)。

    Returns:
        ClientSpec: クライアントの仕様。
    """
    return ClientSpec(
        client_id=client_id,
        redirect_uris=(settings.callback_url,),
        web_origins=(settings.frontend_url,),
        post_logout_redirect_uris=(f"{settings.frontend_url}{post_logout_path}",),
        public_client=False,
        standard_flow_enabled=True,
        # パスワードグラントは開発用ログイン (/api/auth/dev-login) 専用。APP_ENV=development のときだけ有効 (02 §3.1)。
        direct_access_grants_enabled=settings.direct_access_grants_enabled,
        service_accounts_enabled=False,
        secret=derive_client_secret(seed, realm, client_id),
        attributes={"pkce.code.challenge.method": PKCE_METHOD},
        extra={"implicitFlowEnabled": False},
    )


def _check_tenant_id_mapper(admin: KeycloakAdminClient, realm: str, client_internal_id: str, tenant_id: str) -> None:
    """既存の ``tenant_id`` マッパーが別のテナントの値になっていないことを確認する。

    同じレルムに別の tenant_id を上書きすると、そのレルムで発行されるトークンが別テナントを名乗る。
    tenant_code は再利用しない (01 §5.1) ため、食い違いは台帳と Keycloak の不整合であり、自動で直さずに止める。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        client_internal_id: ログイン用クライアントの内部 ID。
        tenant_id: 期待する tenant_id (文字列)。

    Raises:
        KeycloakAdminError: 既存のマッパーの値が異なる場合。
    """
    for mapper in list_protocol_mappers(admin, realm, client_internal_id):
        if mapper.get("name") != TENANT_ID_MAPPER_NAME:
            continue
        current = (mapper.get("config") or {}).get("claim.value")
        if current and current != tenant_id:
            raise KeycloakAdminError(f"ensure tenant_id mapper in realm {realm}", 409, "realm is already bound to another tenant_id")


# --------------------------------------------------------------------------- テンプレート


def ensure_tenant_realm(
    admin: KeycloakAdminClient,
    *,
    tenant_code: str,
    tenant_id: uuid.UUID,
    display_name: str,
    enabled: bool = True,
    settings: PlatformClientSettings | None = None,
    secret_seed: str | None = None,
) -> TenantRealmResult:
    """テナントレルムのテンプレート (02 §3.1 / §3.2) を冪等に適用する。

    作成・反映するもの:
        1. レルム ``tenant-{tenant_code}`` (表示名、メール重複不可、登録・パスワードリセット無効、ブルートフォース保護、``enabled``)
        2. レルムロール ``tenant_admin`` / ``member``、既定ロールに ``member``
        3. ログイン用クライアント (``KEYCLOAK_CLIENT_ID``、既定 ``fastapi-app``): confidential、Standard Flow + PKCE(S256)、
           導出シークレット、``directAccessGrants`` は ``APP_ENV=development`` のときだけ
        4. マッパー: ``tenant_id`` のハードコードクレーム (ID / アクセストークン・userinfo)、Audience (``aud`` にログイン用クライアント)
        5. サービスアカウント ``tenant-user-admin`` (導出シークレット) と ``realm-management`` の
           ``manage-users`` / ``view-users`` / ``query-users``

    既存のレルムにも毎回設定を反映する (``enabled`` も引数の値に揃える。停止中のテナントを再実行する場合は ``enabled=False`` を渡す)。

    Args:
        admin: Admin API クライアント (:func:`create_provisioner_admin_client`)。
        tenant_code: テナントコード (01 §5.1 の形式。予約語の判定は呼び出し側)。
        tenant_id: テナント台帳の tenant_id。トークンの ``tenant_id`` クレームになる。
        display_name: レルムの表示名 (ログイン画面に出る)。
        enabled: レルムを有効にするか。
        settings: クライアントの URL 等の設定。省略時は環境変数 (:meth:`PlatformClientSettings.from_env`)。
        secret_seed: シークレット導出用のシード。省略時は ``KC_CLIENT_SECRET_SEED`` (:func:`client_secret_seed_from_env`)。

    Returns:
        TenantRealmResult: 結果 (シークレットは含まない)。

    Raises:
        ValueError: tenant_code の形式が不正、または tenant_id が UUID でない場合。
        RuntimeError: 本番相当の環境でシードが未設定の場合。
        KeycloakAdminError: Admin API の呼び出しに失敗した、またはレルムが別の tenant_id に紐づいている場合。
    """
    realm = tenant_realm_name(tenant_code)
    tenant_id_value = str(uuid.UUID(str(tenant_id)))
    settings = settings or PlatformClientSettings.from_env()
    seed = secret_seed or client_secret_seed_from_env()

    realm_result = ensure_realm(admin, RealmSpec(realm=realm, enabled=enabled, settings={**_COMMON_REALM_SETTINGS, "displayName": display_name}))

    for role in TENANT_ROLES:
        ensure_realm_role(admin, realm, role, description=_ROLE_DESCRIPTIONS[role])
    ensure_default_realm_roles(admin, realm, TENANT_DEFAULT_ROLES)

    login_client_id = settings.app_client_id
    login_client = ensure_client(admin, realm, _login_client_spec(login_client_id, realm, seed, settings, f"/{tenant_code}/*"))
    _check_tenant_id_mapper(admin, realm, login_client.id, tenant_id_value)
    ensure_protocol_mapper(admin, realm, login_client.id, hardcoded_claim_mapper(TENANT_ID_MAPPER_NAME, TENANT_ID_CLAIM, tenant_id_value))
    ensure_protocol_mapper(admin, realm, login_client.id, audience_mapper(AUDIENCE_MAPPER_NAME, login_client_id))

    user_admin_spec = ClientSpec(
        client_id=TENANT_USER_ADMIN_CLIENT_ID,
        public_client=False,
        standard_flow_enabled=False,
        direct_access_grants_enabled=False,
        service_accounts_enabled=True,
        secret=derive_client_secret(seed, realm, TENANT_USER_ADMIN_CLIENT_ID),
        extra={"implicitFlowEnabled": False},
    )
    user_admin_client = ensure_client(admin, realm, user_admin_spec)
    service_account_user_id = get_service_account_user_id(admin, realm, user_admin_client.id)
    realm_management_id = require_client_internal_id(admin, realm, REALM_MANAGEMENT_CLIENT_ID)
    ensure_user_client_roles(admin, realm, service_account_user_id, realm_management_id, TENANT_USER_ADMIN_ROLES)

    logger.info("テナントレルムのテンプレートを適用しました: realm=%s created=%s enabled=%s", realm, realm_result.created, enabled)
    return TenantRealmResult(realm_name=realm, created=realm_result.created, login_client_id=login_client_id, user_admin_client_id=TENANT_USER_ADMIN_CLIENT_ID)


def ensure_control_plane_realm(admin: KeycloakAdminClient, *, settings: PlatformClientSettings | None = None, secret_seed: str | None = None) -> ControlPlaneRealmResult:
    """CP のレルム ``control-plane`` (02 §3.1) を冪等に作成・反映する。

    作成・反映するもの: レルム (テナントレルムと同じ安全設定)、レルムロール ``saas_admin`` / ``saas_viewer``
    (既定ロールには含めない)、ログイン用クライアント (``KEYCLOAK_CP_CLIENT_ID``、既定 ``fastapi-cp``。
    confidential、Standard Flow + PKCE(S256)、導出シークレット、``directAccessGrants`` は開発のみ)、Audience マッパー。

    Args:
        admin: Admin API クライアント。
        settings: クライアントの URL 等の設定。省略時は環境変数。
        secret_seed: シークレット導出用のシード。省略時は ``KC_CLIENT_SECRET_SEED``。

    Returns:
        ControlPlaneRealmResult: 結果 (シークレットは含まない)。

    Raises:
        RuntimeError: 本番相当の環境でシードが未設定の場合。
        KeycloakAdminError: Admin API の呼び出しに失敗した場合。
    """
    realm = CONTROL_PLANE_REALM_NAME
    settings = settings or PlatformClientSettings.from_env()
    seed = secret_seed or client_secret_seed_from_env()

    realm_result = ensure_realm(admin, RealmSpec(realm=realm, enabled=True, settings={**_COMMON_REALM_SETTINGS, "displayName": "Control Plane"}))
    for role in CP_ROLES:
        ensure_realm_role(admin, realm, role, description=_ROLE_DESCRIPTIONS[role])

    login_client_id = settings.cp_client_id
    login_client = ensure_client(admin, realm, _login_client_spec(login_client_id, realm, seed, settings, "/cp/*"))
    ensure_protocol_mapper(admin, realm, login_client.id, audience_mapper(AUDIENCE_MAPPER_NAME, login_client_id))

    logger.info("control-plane レルムを適用しました: created=%s", realm_result.created)
    return ControlPlaneRealmResult(realm_name=realm, created=realm_result.created, login_client_id=login_client_id)


def ensure_tenant_user(
    admin: KeycloakAdminClient,
    *,
    realm_name: str,
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    roles: Sequence[str],
    password: str,
    temporary: bool,
) -> str:
    """ユーザーを冪等に作成し、パスワードとレルムロールを設定する。

    - 新規ユーザー: メール (確認済み)・姓・名を設定して作成する。``temporary`` なら必須アクション ``UPDATE_PASSWORD`` を付ける
    - 既存ユーザー: メール・姓・名のうち**空の項目だけ**を埋める (既存の値は上書きしない)
    - パスワード: **既存ユーザーでも毎回設定し直す** (払い出しの再実行で返す一時パスワード、シードの開発用パスワードを確実に有効にするため)
    - ロール: ``roles`` のうち不足分だけを追加する (余分なロールは外さない)

    レルムロールは事前に作成済みであること (:func:`ensure_tenant_realm` / :func:`ensure_control_plane_realm`)。
    control-plane のユーザーにも使える。

    Args:
        admin: Admin API クライアント。
        realm_name: レルム名。
        username: ユーザー名 (Keycloak は小文字に正規化する)。
        email: メールアドレス (レルム内で一意)。
        first_name: 名。
        last_name: 姓。
        roles: 付与するレルムロール。
        password: パスワード。ログ・例外・戻り値には含めない。
        temporary: 一時パスワードにするか (初回ログイン時に変更を要求する)。

    Returns:
        str: ユーザーの内部 ID。

    Raises:
        ValueError: レルム名が不正、またはメール・姓・名・パスワードが空の場合。
        KeycloakAdminError: Admin API の呼び出しに失敗した (パスワードポリシー違反、メール重複、存在しないロールを含む) 場合。
    """
    realm = validate_realm_name(realm_name)
    if not (username and email and first_name and last_name):
        # Keycloak の既定のユーザープロフィールでは必須。欠けるとログインが "Account is not fully set up" で失敗する。
        raise ValueError("username, email, first_name and last_name are required")
    if not password:
        raise ValueError("password must not be empty")

    spec = UserSpec(
        username=username,
        enabled=True,
        email=email,
        email_verified=True,
        first_name=first_name,
        last_name=last_name,
        required_actions=("UPDATE_PASSWORD",) if temporary else (),
    )
    user = ensure_user(admin, realm, spec, fill_missing_profile=True)
    set_user_password(admin, realm, user.id, password, temporary=temporary)
    ensure_user_realm_roles(admin, realm, user.id, roles)
    return user.id


# --------------------------------------------------------------------------- 管理クライアント


def create_provisioner_admin_client() -> KeycloakAdminClient:
    """払い出し用の管理クライアントを環境変数から作る。

    - ``APP_ENV=development``: ``KEYCLOAK_ADMIN_REALM`` (既定 master) / ``admin-cli`` に、
      ``KEYCLOAK_ADMIN_USERNAME`` / ``KEYCLOAK_ADMIN_PASSWORD`` でパスワードグラント
    - それ以外: ``KEYCLOAK_PROVISIONER_CLIENT_ID`` (既定 ``cp-provisioner``) / ``KEYCLOAK_PROVISIONER_CLIENT_SECRET`` の
      クライアントクレデンシャル。管理ユーザーのパスワードは読まない

    締め切りは ``KEYCLOAK_ADMIN_DEADLINE_SECONDS`` (既定 30 秒、CP-ONB-06)。生成時点から数えるため、
    **1 回の払い出し (1 テナント) ごとに作り、使い終わったら閉じる** (``with`` 文)。

    Returns:
        KeycloakAdminClient: 管理クライアント。

    Raises:
        RuntimeError: 必要な資格情報が環境変数に無い場合。
        ValueError: タイムアウト値が不正な場合。
    """
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env == "development":
        return KeycloakAdminClient.from_settings(KeycloakAdminSettings.from_env())

    settings = KeycloakAdminSettings.from_env(require_admin_password=False)
    client_id = os.getenv(PROVISIONER_CLIENT_ID_ENV, "").strip() or DEFAULT_PROVISIONER_CLIENT_ID
    client_secret = os.getenv(PROVISIONER_CLIENT_SECRET_ENV, "")
    if not client_secret:
        raise RuntimeError(f"{PROVISIONER_CLIENT_SECRET_ENV} が未設定です。APP_ENV={app_env} では払い出しに {client_id} のクライアントクレデンシャルを使います。")
    token_provider = ClientCredentialsTokenProvider(settings.admin_token_url, client_id, client_secret)
    return KeycloakAdminClient.from_settings(settings, token_provider=token_provider)


def create_tenant_user_admin_client(realm_name: str, *, secret_seed: str | None = None, settings: KeycloakAdminSettings | None = None) -> KeycloakAdminClient:
    """テナントレルムのユーザー管理用サービスアカウント ``tenant-user-admin`` の管理クライアントを作る (02 §3.1)。

    AP のユーザー管理 (作成・無効化・ロール変更) 専用。権限は ``realm-management`` の ``manage-users`` /
    ``view-users`` / ``query-users`` のみで、そのレルムのユーザーしか操作できない。AP から
    :func:`create_provisioner_admin_client` (``cp-provisioner``) を使わないこと (01 §7.1)。

    - トークン: ``{base_url}/realms/{realm_name}/protocol/openid-connect/token`` のクライアントクレデンシャル
    - シークレット: ``KC_CLIENT_SECRET_SEED`` から導出 (02 §3.3。払い出しで設定した値と同じ)
    - 接続先・タイムアウト・締め切りは ``KEYCLOAK_URL`` 等 (:meth:`KeycloakAdminSettings.from_env`)。管理ユーザーのパスワードは読まない

    締め切りは生成時点から数えるため、**1 回の操作 (API の 1 リクエスト) ごとに ``with`` で作る**。
    操作できる API の範囲は :mod:`modules.keycloak_admin.tenant_users` を参照する。

    Args:
        realm_name: テナントレルム名 (``tenant-{tenant_code}``)。
        secret_seed: シークレット導出用のシード。省略時は ``KC_CLIENT_SECRET_SEED``。
        settings: 接続設定。省略時は環境変数。``admin_realm`` は ``realm_name`` で置き換える。

    Returns:
        KeycloakAdminClient: 管理クライアント。

    Raises:
        ValueError: レルム名がテナントレルムの形式でない場合 (``master`` / ``control-plane`` 等は拒否する)。
        RuntimeError: 本番相当の環境でシードが未設定の場合。
    """
    realm = validate_realm_name(realm_name)
    if not realm.startswith(TENANT_REALM_PREFIX) or not TENANT_CODE_PATTERN.fullmatch(realm.removeprefix(TENANT_REALM_PREFIX)):
        raise ValueError("realm_name must be a tenant realm (tenant-{tenant_code})")
    seed = secret_seed or client_secret_seed_from_env()
    base_settings = settings or KeycloakAdminSettings.from_env(require_admin_password=False)
    realm_settings = dataclasses.replace(base_settings, admin_realm=realm, admin_client_id=TENANT_USER_ADMIN_CLIENT_ID, admin_password="")
    token_provider = ClientCredentialsTokenProvider(realm_settings.admin_token_url, TENANT_USER_ADMIN_CLIENT_ID, derive_client_secret(seed, realm, TENANT_USER_ADMIN_CLIENT_ID))
    return KeycloakAdminClient.from_settings(realm_settings, token_provider=token_provider)
