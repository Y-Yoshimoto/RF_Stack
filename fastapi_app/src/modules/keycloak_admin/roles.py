"""レルムロールの冪等な操作。

テナントテンプレート (``tenant_admin`` / ``member`` など) の作成を想定している。
"""
import logging

from .admin_client import KeycloakAdminClient
from .errors import KeycloakAdminError
from .models import RoleResult

logger = logging.getLogger(__name__)


def get_realm_role(admin: KeycloakAdminClient, realm: str, name: str) -> dict | None:
    """レルムロールを取得する。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        name: ロール名。

    Returns:
        dict | None: RoleRepresentation。存在しない場合は ``None``。
    """
    return admin.get_json_or_none(admin.realm_url(realm, "roles", name), operation=f"query realm role {name} in realm {realm}")


def ensure_realm_role(admin: KeycloakAdminClient, realm: str, name: str, *, description: str | None = None) -> RoleResult:
    """レルムロールが存在することを保証する (無ければ作成)。

    既存ロールの説明は更新しない。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        name: ロール名。
        description: ロールの説明 (作成時のみ使用)。

    Returns:
        RoleResult: 結果。

    Raises:
        KeycloakAdminError: Admin API の呼び出しに失敗した場合。
    """
    existing = get_realm_role(admin, realm, name)
    if existing is not None:
        return RoleResult(id=existing["id"], name=name, created=False)

    payload = {"name": name}
    if description is not None:
        payload["description"] = description
    response = admin.request("POST", admin.realm_url(realm, "roles"), operation=f"create realm role {name} in realm {realm}", expected=(201, 409), json=payload)

    # ロール作成の Location は名前ベースのため、ID は取得し直す。
    role = get_realm_role(admin, realm, name)
    if role is None:
        raise KeycloakAdminError(f"resolve realm role {name} in realm {realm}")
    created = response.status_code == 201
    if created:
        logger.info("レルムロールを作成しました: realm=%s name=%s", realm, name)
    return RoleResult(id=role["id"], name=name, created=created)
