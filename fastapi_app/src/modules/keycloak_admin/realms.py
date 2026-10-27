"""レルムの冪等な作成・更新。"""
import logging
import re

from .admin_client import KeycloakAdminClient
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
