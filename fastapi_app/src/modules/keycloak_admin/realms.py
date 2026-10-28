"""レルムの冪等な作成・更新。"""
import logging
import re

from .admin_client import KeycloakAdminClient
from .errors import KeycloakAdminError
from .models import RealmResult, RealmSpec

logger = logging.getLogger(__name__)

# アプリ (``modules.auth.environment.REALM_NAME_PATTERN``) がログイン時に受け付けるレルム名と同じ制約。
# これを満たさないレルムを作ってもログインできないため、作成時点で弾く。
# ``$`` は末尾の改行 1 つを許すため、fullmatch で全体一致を取る。
REALM_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def validate_realm_name(realm: str) -> str:
    """レルム名を検証する。

    Args:
        realm: レルム名。

    Returns:
        str: 検証済みのレルム名。

    Raises:
        ValueError: 許可されない文字を含む、または長さが範囲外の場合。
    """
    if not isinstance(realm, str) or not REALM_NAME_PATTERN.fullmatch(realm):
        raise ValueError("realm must match ^[A-Za-z0-9_-]{1,64}$")
    return realm


def get_realm(admin: KeycloakAdminClient, realm: str) -> dict | None:
    """レルムの Representation を取得する。

    Args:
        admin: Admin API クライアント。
        realm: レルム名。

    Returns:
        dict | None: RealmRepresentation。存在しない場合は ``None``。
    """
    return admin.get_json_or_none(admin.realm_url(realm), operation=f"query realm {realm}")


def ensure_realm(admin: KeycloakAdminClient, spec: RealmSpec | str) -> RealmResult:
    """レルムが存在することを保証する (無ければ作成)。

    ``spec.settings`` を指定した場合は、既存レルムにもその設定を部分更新 (PUT) で反映する。
    指定しない場合、既存レルムには何もしない (旧シェルスクリプトと同じ)。

    Args:
        admin: Admin API クライアント。
        spec: レルムのあるべき状態、またはレルム名。

    Returns:
        RealmResult: 結果。

    Raises:
        ValueError: レルム名が不正な場合。
        KeycloakAdminError: Admin API の呼び出しに失敗した場合。
    """
    if isinstance(spec, str):
        spec = RealmSpec(realm=spec)
    realm = validate_realm_name(spec.realm)

    if get_realm(admin, realm) is None:
        response = admin.request("POST", admin.realms_url, operation=f"create realm {realm}", expected=(201, 409), json=spec.to_representation())
        if response.status_code == 201:
            logger.info("レルムを作成しました: %s", realm)
            return RealmResult(realm=realm, created=True)
        # 409: 並行実行などで先に作成された。既存として扱う。
        logger.info("レルムは作成済みでした (409): %s", realm)

    if not spec.settings:
        logger.info("レルムは既に存在します: %s", realm)
        return RealmResult(realm=realm, created=False)

    admin.request("PUT", admin.realm_url(realm), operation=f"update realm {realm}", expected=(204,), json=spec.to_representation())
    logger.info("既存レルムの設定を更新しました: %s", realm)
    return RealmResult(realm=realm, created=False, updated=True)


# 削除を拒否するレルム。master を消すと Keycloak 全体の管理ができなくなる。
PROTECTED_REALMS = frozenset({"master"})


def set_realm_enabled(admin: KeycloakAdminClient, realm_name: str, enabled: bool) -> None:
    """レルムの有効・無効を切り替える (テナントの停止・再開用。01 §6.3)。

    既に指定の状態であれば何もしない (冪等)。無効化したレルムではログイン・トークン更新ができなくなる。
    発行済みのアクセストークンは有効期限まで失効しないため、AP 側の停止判定 (テナントレジストリ) と併用する。

    Args:
        admin: Admin API クライアント。
        realm_name: レルム名。
        enabled: 有効にするか。

    Raises:
        ValueError: レルム名が不正な場合。
        KeycloakAdminError: レルムが存在しない (404)、または Admin API の呼び出しに失敗した場合。
    """
    realm = validate_realm_name(realm_name)
    current = get_realm(admin, realm)
    if current is None:
        raise KeycloakAdminError(f"set enabled={enabled} on realm {realm}", 404, "realm not found")
    if current.get("enabled") is enabled:
        logger.info("レルムは既に enabled=%s です: %s", enabled, realm)
        return
    admin.request("PUT", admin.realm_url(realm), operation=f"set enabled={enabled} on realm {realm}", expected=(204,), json={"realm": realm, "enabled": enabled})
    logger.info("レルムを enabled=%s にしました: %s", enabled, realm)


def delete_realm_if_exists(admin: KeycloakAdminClient, realm_name: str) -> bool:
    """レルムを削除する。既に無ければ何もしない (冪等。01 CP-OPS-08)。

    レルム内のユーザー・クライアント・セッションもすべて消える。``master`` は削除を拒否する。

    Args:
        admin: Admin API クライアント。
        realm_name: レルム名。

    Returns:
        bool: 今回削除した場合は ``True``、存在しなかった場合は ``False``。

    Raises:
        ValueError: レルム名が不正、または削除を拒否するレルムの場合。
        KeycloakAdminError: Admin API の呼び出しに失敗した場合。
    """
    realm = validate_realm_name(realm_name)
    if realm in PROTECTED_REALMS:
        raise ValueError(f"realm {realm} must not be deleted")
    response = admin.request("DELETE", admin.realm_url(realm), operation=f"delete realm {realm}", expected=(204, 404))
    if response.status_code == 404:
        logger.info("レルムは存在しません (削除済み): %s", realm)
        return False
    logger.info("レルムを削除しました: %s", realm)
    return True
