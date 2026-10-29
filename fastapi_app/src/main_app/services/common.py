#!/usr/bin/env python
# coding:utf-8
"""AP のサービス層で共有する部品（未指定の表現、操作者の解決、監査ログ、IdP エラーの要約、ビュー）。

FastAPI に依存しない。テナントはテナントコンテキスト（:func:`modules.tenancy.context.require_tenant_context`）から得る。
"""
import datetime as dt
import enum
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

from sqlmodel import Session

from main_app.models import TOrganization, TUser
from main_app.repositories import users as user_repo
from main_app.repositories.audit_log import add_ap_audit_log
from modules.errors.request_id import get_request_id
from modules.keycloak_admin.errors import KeycloakAdminError
from modules.keycloak_admin.templates import TENANT_ROLES
from modules.tenancy.context import TenantContext

logger = logging.getLogger(__name__)


class _UnsetType(enum.Enum):
    """「指定なし」を表す番兵の型（``None`` = 値を消す、と区別する。03 §1 の PATCH）。"""

    UNSET = enum.auto()

    def __repr__(self) -> str:
        """``UNSET`` と表示する。"""
        return "UNSET"

    def __bool__(self) -> bool:
        """偽として扱う。"""
        return False


# PATCH で送られなかった項目を表す値。``if value is UNSET`` で判定する。
UNSET: Final = _UnsetType.UNSET
type Maybe[T] = T | _UnsetType


def utc_now() -> dt.datetime:
    """現在時刻（UTC、タイムゾーン付き）を返す。"""
    return dt.datetime.now(dt.UTC)


def resolve_actor_id(session: Session, ctx: TenantContext, actor_subject: str | None) -> uuid.UUID | None:
    """操作者の AP のユーザー ID を解決する（監査ログの ``actor_id``、``created_by`` / ``updated_by``）。

    Args:
        session: AP のセッション。
        ctx: テナントコンテキスト。
        actor_subject: 操作者の IdP の利用者 ID。``None`` ならコンテキストの ``user_id``（セッションの ``sub``）。

    Returns:
        uuid.UUID | None: ユーザー ID。操作者が分からない・ユーザー行が無い場合は ``None``（システム処理として記録する）。
    """
    subject = actor_subject or (str(ctx.user_id) if ctx.user_id is not None else None)
    if not subject:
        return None
    user = user_repo.get_user_by_subject(session, subject)
    if user is None:
        logger.warning("操作者のユーザー行が見つかりません（ログイン時の同期前のセッション）: tenant_id=%s", ctx.tenant_id)
        return None
    return user.id


def record_audit(session: Session, ctx: TenantContext, *, actor_id: uuid.UUID | None, action: str, target_type: str, target_id: uuid.UUID, payload: dict[str, Any] | None) -> None:
    """AP 監査ログを追記する（業務データの変更と同じトランザクション。コミットは呼び出し側）。

    Args:
        session: AP のセッション。
        ctx: テナントコンテキスト。
        actor_id: 操作者のユーザー ID（システム処理は ``None``）。
        action: 操作（``resource.verb``）。
        target_type: 対象の種別。
        target_id: 対象の ID。
        payload: 変更前後の差分など（**秘匿値を含めない**）。
    """
    add_ap_audit_log(session, tenant_id=ctx.tenant_id, actor_id=actor_id, action=action, target_type=target_type, target_id=target_id, payload=payload, request_id=get_request_id())


def summarize_idp_error(operation: str, exc: BaseException) -> str:
    """IdP の操作の失敗を、秘匿値を含まない要約にする（``KeycloakAdminError.detail`` は含めない）。

    Args:
        operation: 操作名。
        exc: 例外。

    Returns:
        str: 例: ``operation=create_user; error=KeycloakAdminError; http_status=400``。
    """
    parts = [f"operation={operation}", f"error={type(exc).__name__}"]
    if isinstance(exc, KeycloakAdminError) and exc.status_code is not None:
        parts.append(f"http_status={exc.status_code}")
    return "; ".join(parts)


def change(before: Any, after: Any) -> dict[str, Any]:
    """監査ログの ``payload`` に入れる変更前後の組を作る。"""
    return {"before": before, "after": after}


def normalize_tenant_roles(roles: Iterable[str]) -> list[str]:
    """ロールの集まりから、テナントのロール（``tenant_admin`` / ``member``）だけを決まった順（``TENANT_ROLES`` の順）で返す。

    ``t_user.roles``（写し）の値はこの形にそろえる（比較・表示の順を安定させる。CHECK 制約もこの 2 つのみ許可する）。

    Args:
        roles: ロール名（トークンのレルムロール、IdP の実効ロールなど。それ以外のロールは無視する）。

    Returns:
        list[str]: 例: ``["tenant_admin", "member"]``。
    """
    present = {role for role in roles if isinstance(role, str)}
    return [role for role in TENANT_ROLES if role in present]


@dataclass(frozen=True, slots=True, kw_only=True)
class UserView:
    """ユーザーのスナップショット（セッションから切り離した値。API のレスポンスに使う）。

    姓・名・ロールは IdP（Keycloak）が正で、ここに入るのは AP の DB の写し（``t_user.first_name`` / ``last_name`` / ``roles``）。
    写しはログイン時の同期・管理者の作成/更新・詳細の取得（:meth:`main_app.services.user_service.UserService.get_user` は
    IdP から取り直して写しを更新する）で更新される。一覧では最後に同期した時点の値になる。

    Attributes:
        id: ユーザー ID。
        idp_subject: IdP の利用者 ID（Keycloak のテナントレルムの ``sub``）。
        email: メールアドレス。
        display_name: 表示名。
        first_name: 名（写し。未同期・IdP で未設定なら ``None``）。
        last_name: 姓（写し。未同期・IdP で未設定なら ``None``）。
        roles: テナントのロール（写し。``tenant_admin`` / ``member`` の実効ロールを ``("tenant_admin", "member")`` の順で。未同期は空）。
        is_active: 有効か。
        last_login_at: 最終ログイン日時。
        version: 楽観ロックのバージョン（``ETag``）。
        created_at: 作成日時。
        updated_at: 更新日時。
    """

    id: uuid.UUID
    idp_subject: str
    email: str | None
    display_name: str
    is_active: bool
    last_login_at: dt.datetime | None
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    first_name: str | None = None
    last_name: str | None = None
    roles: tuple[str, ...] = ()

    @classmethod
    def from_model(cls, user: TUser) -> "UserView":
        """モデルから作る（未読み込みの列はここで読み込まれる）。"""
        return cls(
            id=user.id,
            idp_subject=user.idp_subject,
            email=user.email,
            display_name=user.display_name,
            first_name=user.first_name,
            last_name=user.last_name,
            roles=tuple(normalize_tenant_roles(user.roles or ())),
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            version=user.version,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UserNameView:
    """ID から表示名を引くための最小のユーザー情報（ToDo のアクティビティの参照先の解決など）。

    Attributes:
        id: ユーザー ID。
        display_name: 表示名。
        is_active: 有効か（無効化されたユーザーも含めて返す。画面では「無効」と表示する）。
    """

    id: uuid.UUID
    display_name: str
    is_active: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class OrganizationView:
    """組織のスナップショット（セッションから切り離した値）。

    Attributes:
        id: 組織 ID。
        name: 組織名。
        version: 楽観ロックのバージョン（``ETag``）。
        created_at: 作成日時。
        updated_at: 更新日時。
    """

    id: uuid.UUID
    name: str
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, organization: TOrganization) -> "OrganizationView":
        """モデルから作る。"""
        return cls(id=organization.id, name=organization.name, version=organization.version, created_at=organization.created_at, updated_at=organization.updated_at)
