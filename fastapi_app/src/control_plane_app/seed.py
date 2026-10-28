#!/usr/bin/env python
# coding:utf-8
"""開発用シード（02 §7.1）。何度実行しても同じ状態に収束する（冪等）。

fastapi_app コンテナ内（``src`` が ``PYTHONPATH``）で実行する。ホストからは::

    make d-run SERVICE=fastapi_app CMD="uv run python -m control_plane_app.seed"

作成するもの（定義の正は :mod:`modules.auth.dev_profiles`）:
    1. ``control-plane`` レルム（:func:`~modules.keycloak_admin.templates.ensure_control_plane_realm`）と
       CP のユーザー（``cp-admin``: ``saas_admin``、``cp-viewer``: ``saas_viewer``）
    2. 開発用テナント（``alpha`` / ``beta``）を **払い出しサービス**（:class:`TenantProvisioningService`）で作成する。
       台帳に無ければ ``onboard``、``FAILED`` / ``PROVISIONING`` なら ``retry``、``ACTIVE`` ならスキップ。
       初期管理者は各テナントの ``tenant_admin`` ユーザー
    3. 各テナントのユーザー（``tenant_admin`` 1・``member`` 2）を開発用パスワード（一時パスワードではない）で作成・更新する

Keycloak を直接いじる別経路は持たない（払い出しと同じコードを通す）。管理クライアントは操作ごとに作り直す
（締め切り 30 秒は生成時点から数えるため）。

安全策:
    ``APP_ENV=development`` が **明示的に** 設定されていない場合は何もせず終了する（未設定も拒否）。

終了コード:
    0: 成功 / 1: 失敗 / 2: APP_ENV が development でない
"""
import argparse
import logging
import os
import sys
from dataclasses import dataclass

from sqlmodel import Session

from control_plane_app.models.sql_models import TenantStatus
from control_plane_app.repositories import tenant_repository as repo
from control_plane_app.services.errors import TenantServiceError
from control_plane_app.services.tenant_provisioning import SYSTEM_ACTOR, InitialAdminSpec, TenantProvisioningService
from modules.auth.dev_profiles import DEV_CP_USERS, DEV_TENANT_USERS, DEV_TENANTS, DevTenant, DevUser
from modules.keycloak_admin.admin_client import KeycloakAdminClient
from modules.keycloak_admin.errors import KeycloakAdminError
from modules.keycloak_admin.templates import create_provisioner_admin_client, ensure_control_plane_realm, ensure_tenant_user

logger = logging.getLogger(__name__)

TENANT_ADMIN_ROLE = "tenant_admin"


@dataclass(frozen=True, kw_only=True)
class SeededTenant:
    """シードしたテナントの結果（表示用。パスワードは含めない）。

    Attributes:
        tenant_code: テナントコード。
        tenant_id: テナント ID。
        status: シード後の状態。
        action: 実施した操作（``onboard`` / ``retry`` / ``skip``）。
        users: 作成・更新したユーザー名。
    """

    tenant_code: str
    tenant_id: str | None
    status: str
    action: str
    users: tuple[str, ...]


def require_explicit_development() -> None:
    """``APP_ENV=development`` が明示的に設定されていることを確認する。

    Raises:
        RuntimeError: 未設定、または ``development`` 以外の場合。
    """
    app_env = os.environ.get("APP_ENV", "").strip().lower()
    if app_env != "development":
        raise RuntimeError(f"開発用シードは APP_ENV=development でのみ実行できます (APP_ENV={app_env or '<unset>'})")


def _ensure_user(admin: KeycloakAdminClient, user: DevUser) -> None:
    """開発用ユーザーを開発用パスワードで作成・更新する。"""
    ensure_tenant_user(
        admin,
        realm_name=user.realm,
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        roles=list(user.roles),
        password=user.password,
        temporary=False,
    )


def seed_control_plane() -> tuple[str, ...]:
    """``control-plane`` レルムと CP のユーザーを作成・更新する。

    Returns:
        tuple[str, ...]: 作成・更新したユーザー名。
    """
    with create_provisioner_admin_client() as admin:
        ensure_control_plane_realm(admin)
    with create_provisioner_admin_client() as admin:
        for user in DEV_CP_USERS:
            _ensure_user(admin, user)
    return tuple(user.username for user in DEV_CP_USERS)


def _initial_admin_of(tenant: DevTenant) -> DevUser:
    """テナントの初期管理者（最初の ``tenant_admin``）を返す。"""
    for user in DEV_TENANT_USERS[tenant.tenant_code]:
        if TENANT_ADMIN_ROLE in user.roles:
            return user
    raise RuntimeError(f"tenant_admin is not defined for {tenant.tenant_code}")


def seed_tenant(session: Session, tenant: DevTenant) -> SeededTenant:
    """開発用テナントを払い出しサービスで作成し、ユーザーを作成・更新する。

    Args:
        session: CP DB（``cp_runtime``）のセッション。
        tenant: 開発用テナント。

    Returns:
        SeededTenant: 結果。

    Raises:
        TenantServiceError: 払い出しに失敗した場合。
        KeycloakAdminError: ユーザーの作成に失敗した場合。
    """
    admin_user = _initial_admin_of(tenant)
    initial_admin = InitialAdminSpec(email=admin_user.email, username=admin_user.username, first_name=admin_user.first_name, last_name=admin_user.last_name)
    existing = repo.get_tenant_by_code(session, tenant.tenant_code)
    existing_id, existing_status = (existing.id, existing.status) if existing is not None else (None, None)
    session.rollback()

    if existing_status is None:
        action = "onboard"
        with create_provisioner_admin_client() as admin:
            result = TenantProvisioningService(session, admin).onboard(tenant_code=tenant.tenant_code, name=tenant.display_name, initial_admin=initial_admin, actor=SYSTEM_ACTOR)
        tenant_id, status = result.tenant.id, result.tenant.status
    elif existing_status in (TenantStatus.FAILED, TenantStatus.PROVISIONING):
        action = "retry"
        with create_provisioner_admin_client() as admin:
            result = TenantProvisioningService(session, admin).retry(existing_id, initial_admin=initial_admin, actor=SYSTEM_ACTOR)
        tenant_id, status = result.tenant.id, result.tenant.status
    elif existing_status == TenantStatus.ACTIVE:
        action = "skip"
        tenant_id, status = existing_id, existing_status
    else:
        # 停止中・削除要求中などは開発者の操作の結果とみなし、触らない
        logger.warning("テナント %s は %s のため、シードを省略します", tenant.tenant_code, existing_status)
        return SeededTenant(tenant_code=tenant.tenant_code, tenant_id=str(existing_id), status=str(existing_status), action="skip", users=())

    # 初期管理者の一時パスワードは、ここで開発用パスワードに置き換わる
    users = DEV_TENANT_USERS[tenant.tenant_code]
    with create_provisioner_admin_client() as admin:
        for user in users:
            _ensure_user(admin, user)
    return SeededTenant(tenant_code=tenant.tenant_code, tenant_id=str(tenant_id), status=str(status), action=action, users=tuple(user.username for user in users))


def run_seed(session: Session) -> list[SeededTenant]:
    """シード全体を実行する。

    Args:
        session: CP DB（``cp_runtime``）のセッション。

    Returns:
        list[SeededTenant]: テナントごとの結果。
    """
    require_explicit_development()
    cp_users = seed_control_plane()
    print(f"control-plane: users={', '.join(cp_users)}")
    results = []
    for tenant in DEV_TENANTS:
        seeded = seed_tenant(session, tenant)
        print(f"{seeded.tenant_code}: action={seeded.action} status={seeded.status} tenant_id={seeded.tenant_id} users={', '.join(seeded.users)}")
        results.append(seeded)
    return results


def main(argv: list[str] | None = None) -> int:
    """CLI のエントリポイント。

    Args:
        argv: コマンドライン引数（``None`` なら ``sys.argv[1:]``）。

    Returns:
        int: 終了コード。
    """
    parser = argparse.ArgumentParser(prog="python -m control_plane_app.seed", description="開発用のレルム・テナント・ユーザーを冪等に作成する（APP_ENV=development のみ）。")
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ (INFO) を標準エラーに出力する")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    try:
        require_explicit_development()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    from modules.tenancy.providers import dispose_providers, get_cp_sessionmaker

    try:
        with get_cp_sessionmaker()() as session:
            run_seed(session)
    except (TenantServiceError, KeycloakAdminError, ValueError, RuntimeError) as exc:
        # 例外メッセージには秘匿値を含めない設計（services/errors.py、keycloak_admin/errors.py）
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        dispose_providers()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
