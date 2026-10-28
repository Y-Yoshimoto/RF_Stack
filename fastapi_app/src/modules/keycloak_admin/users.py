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


# Keycloak の既定のユーザープロフィールで必須の項目 (UserSpec の属性名, UserRepresentation のキー)。
# いずれかが空のユーザーはログイン時に "Account is not fully set up" で拒否される。
_REQUIRED_PROFILE_FIELDS = (("email", "email"), ("first_name", "firstName"), ("last_name", "lastName"))


def _fill_missing_profile(admin: KeycloakAdminClient, realm: str, existing: dict, spec: UserSpec) -> bool:
    """既存ユーザーのメール・姓・名のうち空の項目だけを ``spec`` の値で埋める。

    既に値がある項目は変更しない。更新時は既存の値を含めた表現を PUT する
    (ユーザープロフィールの検証で、送らなかった必須項目が欠落扱いにならないようにするため)。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        existing: 既存ユーザーの UserRepresentation。
        spec: 埋める値を持つユーザー仕様。

    Returns:
        bool: 更新した場合は ``True``。
    """
    representation = {key: existing.get(key) for key in ("username", "email", "firstName", "lastName") if existing.get(key)}
    changed = False
    for spec_name, key in _REQUIRED_PROFILE_FIELDS:
        value = getattr(spec, spec_name)
        if value and not existing.get(key):
            representation[key] = value
            changed = True
    if not changed:
        return False
    if spec.email and representation.get("email") == spec.email:
        representation["emailVerified"] = spec.email_verified
    admin.request("PUT", admin.realm_url(realm, "users", existing["id"]), operation=f"update user {spec.username} in realm {realm}", expected=(204,), json=representation)
    logger.info("ユーザーの未設定のプロフィール項目を補いました: realm=%s username=%s", realm, spec.username)
    return True


def ensure_user(admin: KeycloakAdminClient, realm: str, spec: UserSpec | str, *, fill_missing_profile: bool = False) -> UserResult:
    """ユーザーが存在することを保証する (無ければ作成)。

    既存ユーザーの属性は原則として更新しない (旧シェルスクリプトと同じ)。
    ``fill_missing_profile`` が真の場合に限り、既存ユーザーのメール・姓・名のうち
    **空の項目だけ** を ``spec`` の値で埋める (既に値がある項目は上書きしない)。
    メール・姓・名の無いユーザーはパスワードグラントが ``Account is not fully set up`` で失敗するため、
    過去にユーザー名だけで作成したユーザーを救済する目的で使う。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。
        spec: ユーザーのあるべき状態、またはユーザー名。
        fill_missing_profile: 既存ユーザーの空のプロフィール項目を埋めるか。

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
        if fill_missing_profile:
            _fill_missing_profile(admin, realm, existing, spec)
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
