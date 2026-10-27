"""ユーザーとパスワードの冪等な操作。"""
import logging

from .admin_client import KeycloakAdminClient, created_id_from_location
from .errors import KeycloakAdminError
from .models import UserResult, UserSpec

logger = logging.getLogger(__name__)


def find_user(admin: KeycloakAdminClient, realm: str, username: str) -> dict | None:
    """ユーザー名 (完全一致) でユーザーを検索する。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        username: ユーザー名。

    Returns:
        dict | None: UserRepresentation。存在しない場合は ``None``。
    """
    users = admin.get_json(admin.realm_url(realm, "users"), operation=f"query users in realm {realm}", params={"username": username, "exact": "true"})
    # Keycloak はユーザー名を小文字に正規化して保存するため、大文字小文字を無視して照合する。
    normalized = username.lower()
    return next((user for user in users or [] if (user.get("username") or "").lower() == normalized), None)


def _require_user_id(admin: KeycloakAdminClient, realm: str, username: str) -> str:
    """ユーザーを検索して内部 ID を返す。見つからなければ例外にする。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        username: ユーザー名。

    Returns:
        str: ユーザーの内部 ID。

    Raises:
        KeycloakAdminError: 見つからない場合。
    """
    user = find_user(admin, realm, username)
    if user is None or not user.get("id"):
        raise KeycloakAdminError(f"resolve user id for {username} in realm {realm}")
    return user["id"]


def ensure_user(admin: KeycloakAdminClient, realm: str, spec: UserSpec | str) -> UserResult:
    """ユーザーが存在することを保証する (無ければ作成)。

    既存ユーザーの属性は更新しない (旧シェルスクリプトと同じ)。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        spec: ユーザーのあるべき状態、またはユーザー名。

    Returns:
        UserResult: 結果。

    Raises:
        KeycloakAdminError: Admin API の呼び出しに失敗した場合。
    """
    if isinstance(spec, str):
        spec = UserSpec(username=spec)

    existing = find_user(admin, realm, spec.username)
    if existing is not None:
        logger.info("ユーザーは既に存在します: realm=%s username=%s", realm, spec.username)
        return UserResult(id=existing["id"], username=spec.username, created=False)

    response = admin.request(
        "POST", admin.realm_url(realm, "users"), operation=f"create user {spec.username} in realm {realm}", expected=(201, 409), json=spec.to_representation()
    )
    if response.status_code == 409:
        # 並行実行などで先に作成された (またはメールアドレス重複)。ユーザー名で見つかれば既存として扱う。
        user = find_user(admin, realm, spec.username)
        if user is None:
            raise KeycloakAdminError(f"create user {spec.username} in realm {realm}", 409, "conflict (duplicate email?)")
        return UserResult(id=user["id"], username=spec.username, created=False)

    user_id = created_id_from_location(response) or _require_user_id(admin, realm, spec.username)
    logger.info("ユーザーを作成しました: realm=%s username=%s", realm, spec.username)
    return UserResult(id=user_id, username=spec.username, created=True)


def set_user_password(admin: KeycloakAdminClient, realm: str, user_id: str, password: str, *, temporary: bool = False) -> None:
    """ユーザーのパスワードを設定する (既存のパスワードは上書き)。

    ``temporary=True`` の場合、次回ログイン時にパスワード変更が要求される。
    パスワードはログ・例外メッセージに含めない。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        user_id: ユーザーの内部 ID。
        password: 設定するパスワード。
        temporary: 一時パスワードにするか。

    Raises:
        KeycloakAdminError: 設定に失敗した場合 (パスワードポリシー違反を含む)。
    """
    payload = {"type": "password", "temporary": temporary, "value": password}
    admin.request("PUT", admin.realm_url(realm, "users", user_id, "reset-password"), operation=f"set user password in realm {realm}", expected=(204,), json=payload)
    logger.info("ユーザーのパスワードを設定しました: realm=%s user_id=%s temporary=%s", realm, user_id, temporary)
