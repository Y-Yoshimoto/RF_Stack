"""認証のプレーン (アプリケーションプレーン AP / コントロールプレーン CP) の定義。

セッションはプレーン毎に分ける (docs/architecture/01-platform-concepts.md §7.2)。
Cookie 名・Redis のキー空間・Keycloak のクライアント・セッションに載せるロールをプレーン毎に持つ。

============== ==================== ========================= ================================
プレーン       Cookie               レルム                    クライアント
============== ==================== ========================= ================================
``app`` (AP)   ``rf_sid_app``       ``tenant-{tenant_code}``  ``KEYCLOAK_CLIENT_ID`` (既定 ``fastapi-app``)
``cp`` (CP)    ``rf_sid_cp``        ``control-plane``         ``KEYCLOAK_CP_CLIENT_ID`` (既定 ``fastapi-cp``)
============== ==================== ========================= ================================
"""
import re
from enum import StrEnum


class Plane(StrEnum):
    """認証のプレーン。値はセッションの ``plane`` と URL (``/api/auth/{plane}/...``) に使う。"""

    APP = "app"
    CP = "cp"


# プレーン毎のセッション Cookie 名。
# FastAPI の依存関数は modules.auth.dependency の APIKeyCookie でこの名前の Cookie を読む。
APP_SESSION_COOKIE_NAME = "rf_sid_app"
CP_SESSION_COOKIE_NAME = "rf_sid_cp"
SESSION_COOKIE_NAMES: dict[Plane, str] = {Plane.APP: APP_SESSION_COOKIE_NAME, Plane.CP: CP_SESSION_COOKIE_NAME}

# コントロールプレーンのレルム名 (固定)。
CP_REALM_NAME = "control-plane"

# テナントレルム名の接頭辞 (``tenant-{tenant_code}``)。
TENANT_REALM_PREFIX = "tenant-"

# セッションに載せるレルムロール (プレーン毎の許可リスト)。
# Keycloak の既定ロール (offline_access, uma_authorization, default-roles-*) やテーマ固有のロールは載せない。
APP_ROLES = frozenset({"tenant_admin", "member"})
CP_ROLES = frozenset({"saas_admin", "saas_viewer"})
PLANE_ROLES: dict[Plane, frozenset[str]] = {Plane.APP: APP_ROLES, Plane.CP: CP_ROLES}

# tenant_code の形式 (01 §5.1)。3〜32 文字、英小文字・数字・ハイフン。先頭・末尾・連続のハイフンは不可。
# fullmatch で使う ("$" は末尾の改行 1 つを許してしまうため、アンカーには頼らない)。
TENANT_CODE_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){2,31}")


def is_valid_tenant_code(tenant_code: str | None) -> bool:
    """tenant_code が 01 §5.1 の形式かどうかを返す。

    Args:
        tenant_code: 判定対象 (外部入力)。

    Returns:
        bool: 形式に合う場合は ``True``。
    """
    return isinstance(tenant_code, str) and TENANT_CODE_PATTERN.fullmatch(tenant_code) is not None


def tenant_code_from_realm(realm: str) -> str | None:
    """テナントレルム名 (``tenant-{tenant_code}``) から tenant_code を取り出す。

    正はテナントレジストリであり、本関数はレジストリを引かない経路 (開発用ログイン) の補助にのみ使う。

    Args:
        realm: レルム名。

    Returns:
        str | None: tenant_code。接頭辞が無い場合は ``None``。
    """
    if not realm.startswith(TENANT_REALM_PREFIX):
        return None
    return realm[len(TENANT_REALM_PREFIX):] or None


def filter_roles(plane: Plane, roles: object) -> list[str]:
    """トークンのレルムロールから、プレーンで扱うロールだけを取り出す。

    Args:
        plane: プレーン。
        roles: ``realm_access.roles`` の値 (リスト以外は空として扱う)。

    Returns:
        list[str]: 許可リストに含まれるロール (重複なし、名前順)。
    """
    if not isinstance(roles, list):
        return []
    allowed = PLANE_ROLES[plane]
    return sorted({role for role in roles if isinstance(role, str) and role in allowed})
