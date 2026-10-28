"""旧 ``keycloak_c/setup_realm_client_user.sh`` 相当の CLI。

fastapi_app コンテナ内で実行する。ホストからは次のように実行する::

    make d-run SERVICE=fastapi_app CMD="uv run python -m modules.keycloak_admin.cli tenant-a fastapi-app user001"

引数・出力はシェル版と同じ。最後にクライアントシークレットを標準出力に表示する。

クライアントシークレットは ``KC_CLIENT_SECRET_SEED`` から導出した値
(:func:`~modules.keycloak_admin.client_secret.derive_client_secret`) をクライアントに設定する。
BFF も同じ式で導出するため、``.env`` にシークレットを転記する必要はない。

ユーザーには必ずメール・姓・名を設定する (Keycloak の既定のユーザープロフィールで必須のため。
欠けているとパスワードグラントが ``Account is not fully set up`` で失敗する)。
未指定時の既定値は ``{username}@example.com`` / ``{username}`` / ``User``。既存ユーザーは空の項目だけを補う。

接続情報の環境変数は :mod:`modules.keycloak_admin.settings` を参照。

終了コード:
    0: 成功 / 1: 引数不正または Keycloak 操作の失敗
"""
import argparse
import logging
import sys

from .admin_client import KeycloakAdminClient
from .client_secret import client_secret_seed_from_env, derive_client_secret
from .errors import KeycloakAdminError
from .provisioning import build_app_client_spec, setup_realm_client_user
from .settings import AppClientSettings, KeycloakAdminSettings, default_init_user_password

logger = logging.getLogger(__name__)

_ENVIRONMENT_HELP = """\
Environment variables:
  KEYCLOAK_URL                      default: http://keycloak_c:8080
  KEYCLOAK_HTTP_RELATIVE_PATH       default: keycloak
  KEYCLOAK_ADMIN_USERNAME           default: admin
  KEYCLOAK_ADMIN_PASSWORD           default: admin (APP_ENV=development only)
  KEYCLOAK_ADMIN_REALM              default: master
  KEYCLOAK_ADMIN_CLIENT_ID          default: admin-cli
  KEYCLOAK_ADMIN_TIMEOUT_SECONDS    default: 10 (per request)
  KEYCLOAK_ADMIN_DEADLINE_SECONDS   default: 30 (whole run)
  APP_CALLBACK_URL                  default: http://localhost:5173/api/auth/callback
  APP_POST_LOGOUT_REDIRECT_URI      default: ${FRONTEND_URL}/*
  APP_WEB_ORIGIN                    default: ${FRONTEND_URL}
  FRONTEND_URL                      default: http://localhost:5173
  KEYCLOAK_INIT_USER_PASSWORD       default for user_password when arg omitted
  KC_CLIENT_SECRET_SEED             seed for the derived client secret (dev default: APP_ENV=development only)
"""

# メール・姓・名の未指定時の既定値 (開発用)。
DEFAULT_EMAIL_DOMAIN = "example.com"
DEFAULT_LAST_NAME = "User"


def build_parser() -> argparse.ArgumentParser:
    """引数パーサを作る。

    Returns:
        argparse.ArgumentParser: 引数パーサ。
    """
    parser = argparse.ArgumentParser(
        prog="python -m modules.keycloak_admin.cli",
        description="Keycloak に Realm / Client / User を冪等に作成し、クライアントシークレットを表示する。",
        epilog=_ENVIRONMENT_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("realm_name", help="Realm name to create/update (tenant)")
    parser.add_argument("client_id", help="Client ID to create/update")
    parser.add_argument("username", help="Username to create/update")
    parser.add_argument("user_password", nargs="?", default=None, help='Optional. Default: KEYCLOAK_INIT_USER_PASSWORD or "ChangeMe123!"')
    parser.add_argument("--email", default=None, help=f"User email. Default: <username>@{DEFAULT_EMAIL_DOMAIN}")
    parser.add_argument("--first-name", default=None, help="User first name. Default: <username>")
    parser.add_argument("--last-name", default=None, help=f'User last name. Default: "{DEFAULT_LAST_NAME}"')
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ (INFO) を標準エラーに出力する")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI のエントリポイント。

    Args:
        argv: コマンドライン引数 (``None`` なら ``sys.argv[1:]``)。

    Returns:
        int: 終了コード。
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    password = args.user_password or default_init_user_password()
    email = args.email or f"{args.username}@{DEFAULT_EMAIL_DOMAIN}"
    first_name = args.first_name or args.username
    last_name = args.last_name or DEFAULT_LAST_NAME
    try:
        settings = KeycloakAdminSettings.from_env()
        secret = derive_client_secret(client_secret_seed_from_env(), args.realm_name, args.client_id)
        client_spec = build_app_client_spec(args.client_id, AppClientSettings.from_env(), secret=secret)
        with KeycloakAdminClient.from_settings(settings) as admin:
            result = setup_realm_client_user(
                admin,
                realm=args.realm_name,
                client_spec=client_spec,
                username=args.username,
                password=password,
                email=email,
                first_name=first_name,
                last_name=last_name,
                report=print,
            )
    except (KeycloakAdminError, ValueError, RuntimeError) as exc:
        # 例外メッセージには秘匿値を含めない設計 (errors.py 参照)。
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print("Done.")
    print(f"Realm:        {result.realm.realm}")
    print(f"Client ID:    {result.client.client_id}")
    print(f"Username:     {result.user.username}")
    print(f"Client Secret:{result.client_secret}")
    print()
    print("The client secret is derived from KC_CLIENT_SECRET_SEED; the BFF derives the same value (no .env change needed).")
    print(f"KEYCLOAK_CLIENT_ID={result.client.client_id}")
    print(f"KEYCLOAK_CLIENT_SECRET={result.client_secret}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
