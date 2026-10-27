"""旧 ``keycloak_c/setup_realm_client_user.sh`` 相当の CLI。

fastapi_app コンテナ内で実行する。ホストからは次のように実行する::

    make d-run SERVICE=fastapi_app CMD="uv run python -m modules.keycloak_admin.cli tenant-a fastapi-app user001"

引数・出力はシェル版と同じ。最後に ``.env`` に設定する ``KEYCLOAK_CLIENT_SECRET`` を標準出力に表示する。
接続情報の環境変数は :mod:`modules.keycloak_admin.settings` を参照。

終了コード:
    0: 成功 / 1: 引数不正または Keycloak 操作の失敗
"""
import argparse
import logging
import sys

from .admin_client import KeycloakAdminClient
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
"""


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
    try:
        settings = KeycloakAdminSettings.from_env()
        client_spec = build_app_client_spec(args.client_id, AppClientSettings.from_env())
        with KeycloakAdminClient.from_settings(settings) as admin:
            result = setup_realm_client_user(admin, realm=args.realm_name, client_spec=client_spec, username=args.username, password=password, report=print)
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
    print("Set this to your .env if needed:")
    print(f"KEYCLOAK_CLIENT_ID={result.client.client_id}")
    print(f"KEYCLOAK_CLIENT_SECRET={result.client_secret}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
