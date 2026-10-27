"""複数の ensure 操作を組み合わせた払い出し手順。

:func:`setup_realm_client_user` は旧シェルスクリプト ``keycloak_c/setup_realm_client_user.sh`` と同じ
6 ステップ (管理トークン取得 → レルム → クライアント → シークレット取得 → ユーザー → パスワード) を行う。

将来のテナントテンプレート (レルムロール、``tenant_id`` クレームマッパー、Audience マッパー、
``tenant-user-admin`` サービスアカウント等) は、本モジュールに別の手順関数として追加し、
:mod:`~modules.keycloak_admin.roles` / :mod:`~modules.keycloak_admin.clients` の ensure 関数を組み合わせて実装する。
"""
from collections.abc import Callable

from .admin_client import KeycloakAdminClient
from .clients import ensure_client, get_client_secret
from .models import ClientSpec, RealmSpec, SetupResult, UserSpec
from .realms import ensure_realm
from .settings import AppClientSettings
from .users import ensure_user, set_user_password

# 進捗メッセージの出力先。秘匿値を含むメッセージは渡さない。
ProgressReporter = Callable[[str], None]


def _ignore_progress(message: str) -> None:
    """進捗メッセージを捨てる既定の reporter。

    Args:
        message: 進捗メッセージ。
    """


def build_app_client_spec(client_id: str, app_settings: AppClientSettings) -> ClientSpec:
    """BFF (FastAPI) 用の confidential クライアントの仕様を作る。

    旧シェルスクリプトと同じ設定 (認可コードフロー + パスワードグラント有効、サービスアカウント無効)。
    パスワードグラントは開発用ログインバイパス (``/api/auth/dev-login``) が使用する。

    Args:
        client_id: クライアント ID。
        app_settings: リダイレクト URI 等の設定。

    Returns:
        ClientSpec: クライアントの仕様。
    """
    return ClientSpec(
        client_id=client_id,
        redirect_uris=(app_settings.callback_url,),
        web_origins=(app_settings.web_origin,),
        post_logout_redirect_uris=(app_settings.post_logout_redirect_uri,),
        public_client=False,
        standard_flow_enabled=True,
        direct_access_grants_enabled=True,
        service_accounts_enabled=False,
    )


def setup_realm_client_user(
    admin: KeycloakAdminClient,
    *,
    realm: str,
    client_spec: ClientSpec,
    username: str,
    password: str,
    report: ProgressReporter = _ignore_progress,
) -> SetupResult:
    """レルム・クライアント・ユーザーを冪等に作成し、クライアントシークレットを返す。

    旧シェルスクリプトと同じ手順・同じ進捗メッセージ。既存のリソースは作り直さず、
    クライアントの設定のみ毎回反映する。ユーザーのパスワードは毎回上書きする (一時パスワードではない)。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        client_spec: クライアントのあるべき状態。
        username: ユーザー名。
        password: ユーザーに設定するパスワード。
        report: 進捗メッセージの出力先 (CLI では ``print``)。

    Returns:
        SetupResult: 結果。``client_secret`` を含むため取り扱いに注意する。

    Raises:
        ValueError: レルム名が不正な場合。
        KeycloakAdminError: Admin API の呼び出しに失敗した場合。
    """
    report("[1/6] Get admin access token")
    admin.authenticate()

    report(f"[2/6] Ensure realm exists: {realm}")
    realm_result = ensure_realm(admin, RealmSpec(realm=realm))
    report("  - Realm created" if realm_result.created else "  - Realm already exists")

    report(f"[3/6] Ensure client exists: {client_spec.client_id}")
    client_result = ensure_client(admin, realm, client_spec, update_existing=True)
    report("  - Client created" if client_result.created else "  - Client already exists")
    if not client_result.created:
        report("  - Ensure client settings (directAccessGrants / redirect URIs)")

    report("[4/6] Fetch client secret")
    client_secret = get_client_secret(admin, realm, client_result.id)

    report(f"[5/6] Ensure user exists: {username}")
    user_result = ensure_user(admin, realm, UserSpec(username=username, enabled=True, email_verified=False))
    report("  - User created" if user_result.created else "  - User already exists")

    report("[6/6] Set user password")
    set_user_password(admin, realm, user_result.id, password, temporary=False)

    return SetupResult(realm=realm_result, client=client_result, client_secret=client_secret, user=user_result)
