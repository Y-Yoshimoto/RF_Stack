"""開発用の認証情報 (テナント・ユーザー・開発用ログインのプロファイル) の唯一の定義 (02 §7)。

開発用ログイン (``GET /api/auth/dev-login?as=<profile>``) とシード (CP の払い出しサービスを CLI から呼ぶもの) の
両方がここを読む。テナント・ユーザーを足す場合もここだけを変更する。

============== ================= =============== ==========================
プロファイル   レルム            ユーザー名      ロール
============== ================= =============== ==========================
``cp-admin``   ``control-plane`` ``cp-admin``    ``saas_admin``
``cp-viewer``  ``control-plane`` ``cp-viewer``   ``saas_viewer``
``alpha-admin`` ``tenant-alpha`` ``alpha-admin`` ``tenant_admin``
``alpha-member`` ``tenant-alpha`` ``alpha-member`` ``member``
``beta-member`` ``tenant-beta``  ``beta-member`` ``member`` (クロステナントの確認用)
============== ================= =============== ==========================

シード対象 (:data:`DEV_USERS`) は上表に加え、各テナントの 2 人目の ``member`` (``alpha-member2`` / ``beta-member2``) と
``beta`` の ``tenant_admin`` (``beta-admin``) を含む (02 §7.1: 各テナントに tenant_admin 1・member 2)。

開発用パスワード:
    開発専用の固定値。:attr:`DevUser.password` は ``APP_ENV=development`` 以外では :class:`RuntimeError` を送出し、
    値を返さない (本番相当の環境で誤って読み込まれても使われない)。
"""
import os
from dataclasses import dataclass, field

from .environment import validate_realm_name
from .plane import CP_REALM_NAME, PLANE_ROLES, TENANT_REALM_PREFIX, Plane, is_valid_tenant_code

# 開発用の固定パスワード。APP_ENV=development 以外では DevUser.password が返さない。
_DEV_PASSWORD = "Dev-Passw0rd!"

# ``as`` を省略したときの開発用ログインのプロファイル。
DEFAULT_DEV_PROFILE = "alpha-admin"

# 開発用ユーザーのメールアドレスのドメイン (RFC 2606 の予約ドメイン)。
DEV_EMAIL_DOMAIN = "example.com"


def require_development_environment() -> None:
    """``APP_ENV=development`` であることを確認する。

    Raises:
        RuntimeError: ``APP_ENV`` が ``development`` 以外の場合。
    """
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env != "development":
        raise RuntimeError(f"開発用の認証情報は APP_ENV=development でのみ使用できます (APP_ENV={app_env})。")


@dataclass(frozen=True, kw_only=True)
class DevTenant:
    """開発用テナント。

    Attributes:
        tenant_code: テナントコード (01 §5.1)。
        display_name: テナント名 (レルムの表示名)。
    """

    tenant_code: str
    display_name: str

    def __post_init__(self) -> None:
        """tenant_code の形式を検証する。

        Raises:
            ValueError: 形式に合わない場合。
        """
        if not is_valid_tenant_code(self.tenant_code):
            raise ValueError(f"invalid tenant_code: {self.tenant_code}")

    @property
    def realm_name(self) -> str:
        """テナントレルム名 (``tenant-{tenant_code}``) を返す。"""
        return f"{TENANT_REALM_PREFIX}{self.tenant_code}"


@dataclass(frozen=True, kw_only=True)
class DevUser:
    """開発用ユーザー (シード対象であり、開発用ログインのプロファイルにもなる)。

    Attributes:
        plane: ログイン先のプレーン。
        realm: レルム。CP は ``control-plane``、AP は ``tenant-{tenant_code}``。
        username: ユーザー名。
        email: メールアドレス。
        first_name: 名。
        last_name: 姓。
        roles: 付与するレルムロール (プレーンの許可リスト内)。
        tenant_code: AP のテナントコード (CP は ``None``)。
        next_path: 開発用ログインで ``next`` を省略したときの遷移先。``None`` ならプレーンの既定。
        dev_password: 開発用パスワードの値。直接読まず :attr:`password` を使う。``repr`` には出さない。
    """

    plane: Plane
    realm: str
    username: str
    email: str
    first_name: str
    last_name: str
    roles: tuple[str, ...]
    tenant_code: str | None = None
    next_path: str | None = None
    dev_password: str = field(default=_DEV_PASSWORD, repr=False, compare=False)

    def __post_init__(self) -> None:
        """プレーン・レルム・テナントコード・ロールの組み合わせを検証する (定義時の誤りを早期に検出する)。

        Raises:
            ValueError: 組み合わせが合わない場合。
        """
        validate_realm_name(self.realm)
        if (self.plane == Plane.CP) != (self.realm == CP_REALM_NAME):
            raise ValueError(f"realm {self.realm} does not match plane {self.plane.value}")
        if self.plane == Plane.APP:
            if not is_valid_tenant_code(self.tenant_code) or self.realm != f"{TENANT_REALM_PREFIX}{self.tenant_code}":
                raise ValueError(f"tenant_code {self.tenant_code} does not match realm {self.realm}")
        elif self.tenant_code is not None:
            raise ValueError("cp user must not have tenant_code")
        if not self.roles or not set(self.roles) <= PLANE_ROLES[self.plane]:
            raise ValueError(f"roles {self.roles} are not allowed for plane {self.plane.value}")
        if not (self.username and self.email and self.first_name and self.last_name):
            raise ValueError("username, email, first_name and last_name are required")

    @property
    def password(self) -> str:
        """開発用パスワードを返す。

        Returns:
            str: パスワード。

        Raises:
            RuntimeError: ``APP_ENV=development`` 以外の場合。
        """
        require_development_environment()
        return self.dev_password


def _tenant_user(tenant: DevTenant, username: str, role: str, first_name: str, last_name: str) -> DevUser:
    """テナントの開発用ユーザーを作る。

    Args:
        tenant: テナント。
        username: ユーザー名。
        role: レルムロール。
        first_name: 名。
        last_name: 姓。

    Returns:
        DevUser: ユーザー。
    """
    return DevUser(
        plane=Plane.APP,
        realm=tenant.realm_name,
        tenant_code=tenant.tenant_code,
        username=username,
        email=f"{username}@{DEV_EMAIL_DOMAIN}",
        first_name=first_name,
        last_name=last_name,
        roles=(role,),
    )


def _cp_user(username: str, role: str, last_name: str) -> DevUser:
    """CP の開発用ユーザーを作る。

    Args:
        username: ユーザー名。
        role: レルムロール。
        last_name: 姓。

    Returns:
        DevUser: ユーザー。
    """
    return DevUser(plane=Plane.CP, realm=CP_REALM_NAME, username=username, email=f"{username}@{DEV_EMAIL_DOMAIN}", first_name="Control Plane", last_name=last_name, roles=(role,))


# 開発用テナント (02 §7.1)。
ALPHA = DevTenant(tenant_code="alpha", display_name="Alpha")
BETA = DevTenant(tenant_code="beta", display_name="Beta")
DEV_TENANTS: tuple[DevTenant, ...] = (ALPHA, BETA)

# CP のユーザー (control-plane レルム)。
DEV_CP_USERS: tuple[DevUser, ...] = (
    _cp_user("cp-admin", "saas_admin", "Admin"),
    _cp_user("cp-viewer", "saas_viewer", "Viewer"),
)

# テナント毎のユーザー (tenant_code -> ユーザー)。各テナントに tenant_admin 1・member 2 (02 §7.1)。
DEV_TENANT_USERS: dict[str, tuple[DevUser, ...]] = {
    ALPHA.tenant_code: (
        _tenant_user(ALPHA, "alpha-admin", "tenant_admin", "Alpha", "Admin"),
        _tenant_user(ALPHA, "alpha-member", "member", "Alpha", "Member"),
        _tenant_user(ALPHA, "alpha-member2", "member", "Alpha", "Member2"),
    ),
    BETA.tenant_code: (
        _tenant_user(BETA, "beta-admin", "tenant_admin", "Beta", "Admin"),
        _tenant_user(BETA, "beta-member", "member", "Beta", "Member"),
        _tenant_user(BETA, "beta-member2", "member", "Beta", "Member2"),
    ),
}

# シード対象の全ユーザー。
DEV_USERS: tuple[DevUser, ...] = DEV_CP_USERS + tuple(user for users in DEV_TENANT_USERS.values() for user in users)


# 開発用ログインのプロファイル (02 §7.2)。キーは ``as`` に渡す名前。
_USERS_BY_NAME: dict[str, DevUser] = {user.username: user for user in DEV_USERS}
DEV_PROFILES: dict[str, DevUser] = {name: _USERS_BY_NAME[name] for name in ("cp-admin", "cp-viewer", "alpha-admin", "alpha-member", "beta-member")}
