"""レルムロールの冪等な操作。

テナントテンプレート (``tenant_admin`` / ``member`` など) の作成を想定している。
"""
import logging
from collections.abc import Iterable, Sequence

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


def _require_realm_roles(admin: KeycloakAdminClient, realm: str, names: Iterable[str]) -> list[dict]:
    """レルムロールをすべて取得する。1 つでも無ければ例外にする。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        names: ロール名。

    Returns:
        list[dict]: RoleRepresentation (``names`` の順、重複なし)。

    Raises:
        KeycloakAdminError: 存在しないロールがある場合。
    """
    roles: list[dict] = []
    for name in dict.fromkeys(names):
        role = get_realm_role(admin, realm, name)
        if role is None:
            raise KeycloakAdminError(f"resolve realm role {name} in realm {realm}", 404, "role not found")
        roles.append(role)
    return roles


def _role_refs(roles: Iterable[dict]) -> list[dict]:
    """ロールの付与 API に送る最小限の表現 (``id`` と ``name``) に変換する。

    Args:
        roles: RoleRepresentation。

    Returns:
        list[dict]: ``[{"id": ..., "name": ...}, ...]``。
    """
    return [{"id": role["id"], "name": role["name"]} for role in roles]


def ensure_default_realm_roles(admin: KeycloakAdminClient, realm: str, names: Sequence[str]) -> list[str]:
    """レルムの既定ロール (``default-roles-{realm}``) に、指定のレルムロールが含まれることを保証する。

    既定ロールは新規ユーザーに自動で付与される複合ロール。既に含まれているロールは追加しない。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        names: 既定ロールに含めるレルムロール名 (事前に作成済みであること)。

    Returns:
        list[str]: 今回追加したロール名。

    Raises:
        KeycloakAdminError: レルム・ロールが存在しない、または Admin API の呼び出しに失敗した場合。
    """
    representation = admin.get_json(admin.realm_url(realm), operation=f"query realm {realm}")
    default_role_name = ((representation or {}).get("defaultRole") or {}).get("name") or f"default-roles-{realm.lower()}"
    url = admin.realm_url(realm, "roles", default_role_name, "composites")
    current = admin.get_json(admin.realm_url(realm, "roles", default_role_name, "composites", "realm"), operation=f"query default roles in realm {realm}") or []
    current_names = {role.get("name") for role in current}
    missing = [role for role in _require_realm_roles(admin, realm, names) if role["name"] not in current_names]
    if not missing:
        return []
    admin.request("POST", url, operation=f"add default roles in realm {realm}", expected=(204,), json=_role_refs(missing))
    added = [role["name"] for role in missing]
    logger.info("既定ロールにレルムロールを追加しました: realm=%s roles=%s", realm, added)
    return added


def ensure_user_realm_roles(admin: KeycloakAdminClient, realm: str, user_id: str, names: Sequence[str]) -> list[str]:
    """ユーザーにレルムロールが直接付与されていることを保証する (不足分だけ追加し、余分は外さない)。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        user_id: ユーザーの内部 ID。
        names: 付与するレルムロール名 (事前に作成済みであること)。

    Returns:
        list[str]: 今回追加したロール名。

    Raises:
        KeycloakAdminError: ロールが存在しない、または Admin API の呼び出しに失敗した場合。
    """
    url = admin.realm_url(realm, "users", user_id, "role-mappings", "realm")
    current_names = {role.get("name") for role in admin.get_json(url, operation=f"query user realm roles in realm {realm}") or []}
    missing = [role for role in _require_realm_roles(admin, realm, names) if role["name"] not in current_names]
    if not missing:
        return []
    admin.request("POST", url, operation=f"add user realm roles in realm {realm}", expected=(204,), json=_role_refs(missing))
    added = [role["name"] for role in missing]
    logger.info("ユーザーにレルムロールを付与しました: realm=%s user_id=%s roles=%s", realm, user_id, added)
    return added


def ensure_user_client_roles(admin: KeycloakAdminClient, realm: str, user_id: str, client_internal_id: str, names: Sequence[str]) -> list[str]:
    """ユーザーにクライアントロールが直接付与されていることを保証する (不足分だけ追加し、余分は外さない)。

    サービスアカウント ``tenant-user-admin`` への ``realm-management`` ロールの付与に使う。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        user_id: ユーザー (サービスアカウントユーザーを含む) の内部 ID。
        client_internal_id: ロールを持つクライアントの内部 ID (例: ``realm-management``)。
        names: 付与するクライアントロール名。

    Returns:
        list[str]: 今回追加したロール名。

    Raises:
        KeycloakAdminError: ロールが存在しない、または Admin API の呼び出しに失敗した場合。
    """
    url = admin.realm_url(realm, "users", user_id, "role-mappings", "clients", client_internal_id)
    current_names = {role.get("name") for role in admin.get_json(url, operation=f"query user client roles in realm {realm}") or []}
    missing: list[dict] = []
    for name in dict.fromkeys(names):
        if name in current_names:
            continue
        role = admin.get_json_or_none(admin.realm_url(realm, "clients", client_internal_id, "roles", name), operation=f"query client role {name} in realm {realm}")
        if role is None:
            raise KeycloakAdminError(f"resolve client role {name} in realm {realm}", 404, "role not found")
        missing.append(role)
    if not missing:
        return []
    admin.request("POST", url, operation=f"add user client roles in realm {realm}", expected=(204,), json=_role_refs(missing))
    added = [role["name"] for role in missing]
    logger.info("ユーザーにクライアントロールを付与しました: realm=%s user_id=%s roles=%s", realm, user_id, added)
    return added
