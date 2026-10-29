"""テナントレルムのユーザー管理 (AP のユーザー管理。01 PF-USR-01..03、02 §3.1)。

テナントレルムのサービスアカウント ``tenant-user-admin`` (``realm-management`` の ``manage-users`` /
``view-users`` / ``query-users`` のみ) の権限で動く操作だけを置く。管理クライアントは
:func:`~modules.keycloak_admin.templates.create_tenant_user_admin_client` で作る。

払い出し用の :mod:`.users` / :mod:`.roles` との違い:
    - **作成は冪等にしない** (:func:`create_user`)。既存のユーザー名・メールアドレスは 409 として返す。
      ``ensure_user`` は既存ユーザーを採用するため、AP から使うと既存ユーザーのパスワードを上書きしてしまう。
    - ロールは ``GET /roles/{name}`` (``view-realm`` が必要で 403 になる) を使わず、
      ``GET /users/{id}/role-mappings/realm/available`` から ID を得て付与する (tenant-provisioning スキル §3.2)。
    - 付与・解除できるロールは呼び出し側が渡す許可リスト (``tenant_admin`` / ``member``) に限る。
      ``realm-management`` のクライアントロールや、許可リスト外のレルムロールは扱わない。

いずれも秘匿値 (パスワード・トークン) をログ・例外メッセージ・戻り値に含めない。
"""
import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from .admin_client import KeycloakAdminClient, created_id_from_location
from .errors import KeycloakAdminError
from .models import UserSpec
from .realms import validate_realm_name
from .users import find_user, set_user_password

logger = logging.getLogger(__name__)

__all__ = [
    "RoleChange",
    "create_user",
    "delete_user_if_exists",
    "get_user",
    "get_user_direct_realm_roles",
    "get_user_effective_realm_roles",
    "logout_user",
    "set_user_enabled",
    "set_user_realm_roles",
    "update_user_names",
]

# PUT /users/{id} で既存の値を送り直すプロフィール項目。
# 既定のユーザープロフィールでメール・姓・名は必須のため、送らなかった項目が欠落扱いにならないよう常に含める。
_PROFILE_KEYS = ("username", "email", "firstName", "lastName")


@dataclass(frozen=True, slots=True)
class RoleChange:
    """:func:`set_user_realm_roles` の結果。

    Attributes:
        before: 変更前に直接付与されていた、許可リスト内のロール。
        after: 変更後に直接付与されている、許可リスト内のロール。
        added: 今回付与したロール。
        removed: 今回解除したロール。
    """

    before: tuple[str, ...]
    after: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]

    @property
    def changed(self) -> bool:
        """付与・解除のいずれかを行ったか。"""
        return bool(self.added or self.removed)


def get_user(admin: KeycloakAdminClient, realm: str, user_id: str) -> dict | None:
    """ユーザーを内部 ID で取得する。

    Args:
        admin: 管理クライアント。
        realm: レルム名。
        user_id: ユーザーの内部 ID (トークンの ``sub``)。

    Returns:
        dict | None: UserRepresentation。存在しない場合は ``None``。
    """
    realm = validate_realm_name(realm)
    return admin.get_json_or_none(admin.realm_url(realm, "users", user_id), operation=f"query user in realm {realm}")


def create_user(admin: KeycloakAdminClient, realm: str, spec: UserSpec, *, password: str, temporary: bool, roles: Sequence[str], allowed_roles: Collection[str]) -> str:
    """ユーザーを新規作成し、パスワードとレルムロールを設定する (冪等にしない)。

    途中 (パスワード・ロールの設定) で失敗した場合は、作成したユーザーを削除してから例外を送出する
    (中途半端なユーザーを残さない。削除にも失敗した場合はログに残す)。

    Args:
        admin: 管理クライアント (``tenant-user-admin``)。
        realm: レルム名。
        spec: ユーザーの内容 (メール・姓・名を含めること)。
        password: 初期パスワード。ログ・例外・戻り値には含めない。
        temporary: 一時パスワードにするか (``spec.required_actions`` に ``UPDATE_PASSWORD`` も含めること)。
        roles: 付与するレルムロール。
        allowed_roles: 付与を許可するレルムロール。

    Returns:
        str: 作成したユーザーの内部 ID。

    Raises:
        ValueError: レルム名が不正、パスワードが空、または許可されないロールを含む場合。
        KeycloakAdminError: 作成に失敗した場合。ユーザー名・メールアドレスの重複は ``status_code == 409``。
    """
    realm = validate_realm_name(realm)
    if not password:
        raise ValueError("password must not be empty")
    _require_allowed_roles(roles, allowed_roles)

    response = admin.request("POST", admin.realm_url(realm, "users"), operation=f"create user in realm {realm}", expected=(201,), json=spec.to_representation())
    user_id = created_id_from_location(response)
    if not user_id:
        user = find_user(admin, realm, spec.username)
        if user is None or not user.get("id"):
            raise KeycloakAdminError(f"resolve created user id in realm {realm}")
        user_id = user["id"]

    try:
        set_user_password(admin, realm, user_id, password, temporary=temporary)
        if roles:
            set_user_realm_roles(admin, realm, user_id, roles, allowed_roles=allowed_roles)
    except Exception:
        _delete_quietly(admin, realm, user_id)
        raise
    logger.info("テナントレルムにユーザーを作成しました: realm=%s user_id=%s", realm, user_id)
    return user_id


def delete_user_if_exists(admin: KeycloakAdminClient, realm: str, user_id: str) -> bool:
    """ユーザーを削除する。既に無ければ何もしない。

    AP のユーザーは論理削除もしない (``is_active`` で無効化する) ため、通常の運用では使わない。
    作成の補償 (AP の行を作れなかった場合) と、動作確認の後始末に使う。

    Args:
        admin: 管理クライアント。
        realm: レルム名。
        user_id: ユーザーの内部 ID。

    Returns:
        bool: 削除した場合は ``True``、存在しなかった場合は ``False``。
    """
    realm = validate_realm_name(realm)
    response = admin.request("DELETE", admin.realm_url(realm, "users", user_id), operation=f"delete user in realm {realm}", expected=(204, 404))
    deleted = response.status_code == 204
    if deleted:
        logger.info("テナントレルムのユーザーを削除しました: realm=%s user_id=%s", realm, user_id)
    return deleted


def update_user_names(admin: KeycloakAdminClient, realm: str, user_id: str, *, first_name: str, last_name: str) -> None:
    """ユーザーの姓・名を更新する (既存のユーザー名・メールは送り直す)。

    Args:
        admin: 管理クライアント。
        realm: レルム名。
        user_id: ユーザーの内部 ID。
        first_name: 名 (空不可)。
        last_name: 姓 (空不可)。

    Raises:
        ValueError: 姓・名が空の場合。
        KeycloakAdminError: ユーザーが存在しない (404)、または更新に失敗した場合。
    """
    if not first_name or not last_name:
        raise ValueError("first_name and last_name are required")
    _put_user(admin, realm, user_id, {"firstName": first_name, "lastName": last_name}, operation="update user names")


def set_user_enabled(admin: KeycloakAdminClient, realm: str, user_id: str, enabled: bool) -> None:
    """ユーザーの有効/無効を切り替える (無効なユーザーはログイン・トークン更新ができない)。

    既に発行済みのセッションを失効させるには、あわせて :func:`logout_user` を呼ぶ。

    Args:
        admin: 管理クライアント。
        realm: レルム名。
        user_id: ユーザーの内部 ID。
        enabled: 有効にするか。

    Raises:
        KeycloakAdminError: ユーザーが存在しない (404)、または更新に失敗した場合。
    """
    _put_user(admin, realm, user_id, {"enabled": enabled}, operation="set user enabled")
    logger.info("テナントレルムのユーザーの有効/無効を切り替えました: realm=%s user_id=%s enabled=%s", realm, user_id, enabled)


def logout_user(admin: KeycloakAdminClient, realm: str, user_id: str) -> None:
    """ユーザーの Keycloak のセッションをすべて失効させる (リフレッシュトークンが使えなくなる)。

    Args:
        admin: 管理クライアント。
        realm: レルム名。
        user_id: ユーザーの内部 ID。

    Raises:
        KeycloakAdminError: ユーザーが存在しない (404)、または失敗した場合。
    """
    realm = validate_realm_name(realm)
    admin.request("POST", admin.realm_url(realm, "users", user_id, "logout"), operation=f"logout user sessions in realm {realm}", expected=(204,))
    logger.info("テナントレルムのユーザーのセッションを失効させました: realm=%s user_id=%s", realm, user_id)


def get_user_direct_realm_roles(admin: KeycloakAdminClient, realm: str, user_id: str) -> list[dict]:
    """ユーザーに直接付与されたレルムロールを返す (複合ロールは展開しない)。

    Args:
        admin: 管理クライアント。
        realm: レルム名。
        user_id: ユーザーの内部 ID。

    Returns:
        list[dict]: RoleRepresentation の一覧。
    """
    realm = validate_realm_name(realm)
    return admin.get_json(admin.realm_url(realm, "users", user_id, "role-mappings", "realm"), operation=f"query user realm roles in realm {realm}") or []


def get_user_effective_realm_roles(admin: KeycloakAdminClient, realm: str, user_id: str) -> list[str]:
    """ユーザーの実効レルムロール名を返す (既定ロール ``default-roles-*`` などの複合ロールを展開する)。

    Args:
        admin: 管理クライアント。
        realm: レルム名。
        user_id: ユーザーの内部 ID。

    Returns:
        list[str]: ロール名 (昇順)。
    """
    realm = validate_realm_name(realm)
    roles = admin.get_json(admin.realm_url(realm, "users", user_id, "role-mappings", "realm", "composite"), operation=f"query user effective realm roles in realm {realm}") or []
    return sorted({role["name"] for role in roles if role.get("name")})


def set_user_realm_roles(admin: KeycloakAdminClient, realm: str, user_id: str, roles: Sequence[str], *, allowed_roles: Collection[str]) -> RoleChange:
    """許可リスト内のレルムロールの直接付与を ``roles`` に揃える (許可リスト外のロールには触れない)。

    付与するロールの ID は ``GET /users/{id}/role-mappings/realm/available`` から得る
    (``tenant-user-admin`` は ``GET /roles/{name}`` を呼べないため)。

    Args:
        admin: 管理クライアント。
        realm: レルム名。
        user_id: ユーザーの内部 ID。
        roles: 直接付与された状態にするロール (許可リスト内)。
        allowed_roles: 付与・解除を許可するロール。

    Returns:
        RoleChange: 変更前後と差分。

    Raises:
        ValueError: 許可されないロールを含む場合。
        KeycloakAdminError: 付与するロールがレルムに無い、または Admin API の呼び出しに失敗した場合。
    """
    realm = validate_realm_name(realm)
    desired = _require_allowed_roles(roles, allowed_roles)
    allowed = set(allowed_roles)
    url = admin.realm_url(realm, "users", user_id, "role-mappings", "realm")

    current = [role for role in get_user_direct_realm_roles(admin, realm, user_id) if role.get("name") in allowed]
    current_names = {role["name"] for role in current}
    to_remove = [role for role in current if role["name"] not in desired]
    to_add_names = [name for name in desired if name not in current_names]

    to_add: list[dict] = []
    if to_add_names:
        available = admin.get_json(admin.realm_url(realm, "users", user_id, "role-mappings", "realm", "available"), operation=f"query available realm roles in realm {realm}") or []
        by_name = {role.get("name"): role for role in available}
        for name in to_add_names:
            role = by_name.get(name)
            if role is None or not role.get("id"):
                raise KeycloakAdminError(f"resolve realm role {name} in realm {realm}", 404, "role not available")
            to_add.append(role)
        admin.request("POST", url, operation=f"add user realm roles in realm {realm}", expected=(204,), json=_role_refs(to_add))
    if to_remove:
        admin.request("DELETE", url, operation=f"remove user realm roles in realm {realm}", expected=(204,), json=_role_refs(to_remove))

    after = sorted((current_names - {role["name"] for role in to_remove}) | {role["name"] for role in to_add})
    change = RoleChange(
        before=tuple(sorted(current_names)),
        after=tuple(after),
        added=tuple(sorted(role["name"] for role in to_add)),
        removed=tuple(sorted(role["name"] for role in to_remove)),
    )
    if change.changed:
        logger.info("ユーザーのレルムロールを変更しました: realm=%s user_id=%s added=%s removed=%s", realm, user_id, list(change.added), list(change.removed))
    return change


# --------------------------------------------------------------------------- 補助


def _require_allowed_roles(roles: Sequence[str], allowed_roles: Collection[str]) -> list[str]:
    """ロールが許可リスト内であることを確認し、重複を除いて返す。

    Args:
        roles: ロール名。
        allowed_roles: 許可するロール名。

    Returns:
        list[str]: 重複を除いたロール名 (指定順)。

    Raises:
        ValueError: 許可されないロールを含む場合。
    """
    if isinstance(roles, str):
        raise ValueError("roles must be a sequence of role names, not a string")
    unique = list(dict.fromkeys(roles))
    disallowed = [role for role in unique if role not in allowed_roles]
    if disallowed:
        raise ValueError(f"roles not allowed: {disallowed}")
    return unique


def _role_refs(roles: Sequence[dict]) -> list[dict]:
    """ロールの付与・解除 API に送る最小限の表現 (``id`` と ``name``) に変換する。"""
    return [{"id": role["id"], "name": role["name"]} for role in roles]


def _put_user(admin: KeycloakAdminClient, realm: str, user_id: str, changes: dict[str, Any], *, operation: str) -> None:
    """既存のプロフィール項目に ``changes`` を重ねて ``PUT /users/{id}`` する。

    Args:
        admin: 管理クライアント。
        realm: レルム名。
        user_id: ユーザーの内部 ID。
        changes: 変更する項目 (UserRepresentation のキー)。
        operation: 操作の説明 (例外メッセージ用)。

    Raises:
        KeycloakAdminError: ユーザーが存在しない (404)、または更新に失敗した場合。
    """
    realm = validate_realm_name(realm)
    existing = get_user(admin, realm, user_id)
    if existing is None:
        raise KeycloakAdminError(f"{operation} in realm {realm}", 404, "user not found")
    representation = {key: existing[key] for key in _PROFILE_KEYS if existing.get(key)}
    representation.update(changes)
    admin.request("PUT", admin.realm_url(realm, "users", user_id), operation=f"{operation} in realm {realm}", expected=(204,), json=representation)


def _delete_quietly(admin: KeycloakAdminClient, realm: str, user_id: str) -> None:
    """作成途中で失敗したユーザーを削除する (補償。失敗してもログに残すだけにする)。"""
    try:
        delete_user_if_exists(admin, realm, user_id)
    except KeycloakAdminError as exc:
        logger.warning("作成途中のユーザーを削除できませんでした: realm=%s user_id=%s error=%s status=%s", realm, user_id, type(exc).__name__, exc.status_code)
