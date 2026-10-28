#!/usr/bin/env python
# coding:utf-8
"""ログイン完了時のユーザー同期（01 PF-USR-04 / 05）と AP の初期データ（デフォルト組織。PF-ORG-04）、
各リクエストでのユーザーの有効性の確認（PF-USR-03 のセッション失効）。

FastAPI に依存しない。いずれも **テナントコンテキスト下の AP セッション**（``app_runtime``、RLS）で呼ぶ。

払い出し時の AP の初期データの作成方法（05 #31）:
    CP は AP に書き込まない（CP → AP の依存は集計・物理削除のみ。``app_cp_agent`` に INSERT を与えない）。
    初期管理者のユーザー行は、最初のログイン時に :func:`sync_user_on_login` が作る。デフォルト組織は、
    同じ処理の中で「そのテナントに組織の行が 1 件も無い（論理削除済みを含む）」ときに作る。
    論理削除済みを含めて判定するため、管理者が全組織を削除しても再作成しない。

ログイン処理（auth-keycloak 担当）からの使い方::

    from main_app.services.user_sync import sync_user_on_login
    from main_app.services.errors import UserDeactivatedError

    with tenant_scope(TenantContext(tenant_id=tid, tenant_code=code, user_id=..., plane="app")):
        with open_app_session() as session:
            try:
                result = sync_user_on_login(session, tenant_id=tid, idp_subject=claims["sub"], email=claims.get("email"),
                                            display_name=claims.get("name") or claims.get("preferred_username"))
            except UserDeactivatedError:
                ...  # ログインを拒否する（セッションを作らない。コールバックは login_rejected）

各リクエストでの確認（PF-USR-03。AP のルーターの依存関数から）::

    require_active_session_user(session, idp_subject=user["sub"])  # UserDeactivatedError / UserNotSyncedError → セッション破棄 + 401
"""
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from main_app.models import TOrganization, TUser
from main_app.repositories import organizations as org_repo
from main_app.repositories import users as user_repo
from main_app.services.common import change, record_audit, utc_now
from main_app.services.errors import UserDeactivatedError, UserNotSyncedError
from modules.tenancy.context import TenantContext, require_tenant_context

logger = logging.getLogger(__name__)

# デフォルト組織の名前（01 PF-ORG-04）
DEFAULT_ORGANIZATION_NAME = "デフォルト組織"

# 監査ログの操作（03 §7）
ACTION_USER_CREATE = "user.create"
ACTION_USER_SYNC = "user.sync"
ACTION_ORGANIZATION_CREATE = "organization.create"


class TenantContextMismatchError(RuntimeError):
    """引数の ``tenant_id`` と、テナントコンテキストのテナントが一致しない（呼び出し側の誤り。500 系）。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class UserSyncResult:
    """:func:`sync_user_on_login` の結果。

    Attributes:
        user_id: AP のユーザー ID（``t_user.id``）。
        created: 今回ユーザー行を作成したか（IdP の管理画面で直接作られたユーザー、初期管理者の初回ログイン）。
        profile_updated: 表示名・メールアドレスを更新したか。
        email_conflict: メールアドレスがテナント内の別のユーザー行で使われていたため、同期しなかったか。
        default_organization_id: 今回デフォルト組織を作成した場合はその ID。
    """

    user_id: uuid.UUID
    created: bool
    profile_updated: bool
    email_conflict: bool
    default_organization_id: uuid.UUID | None


def sync_user_on_login(session: Session, *, tenant_id: uuid.UUID, idp_subject: str, email: str | None, display_name: str | None) -> UserSyncResult:
    """ログイン完了時に、AP のユーザー行を IdP の利用者 ID で照合して同期し、コミットする（PF-USR-04 / 05）。

    - 行が無ければ作成する（``created_by`` は NULL。監査ログ ``user.create``、``source=login``）
    - 行があれば表示名・メールアドレスを同期する（変わった場合だけ ``version`` を +1、監査ログ ``user.sync``）
    - ``last_login_at`` を更新する（``version`` は変えない。トークン更新では呼ばないこと）
    - 無効化されたユーザー（``is_active = false``）なら何も変更せずに :class:`UserDeactivatedError`
    - テナントに組織の行が 1 件も無ければ（論理削除済みを含む）デフォルト組織を作る（PF-ORG-04。監査ログ ``organization.create``）

    メールアドレスがテナント内の別のユーザー行（IdP で削除・再作成されたユーザーの古い行など）で使われている場合は、
    ログインを止めずにメールアドレスだけ同期しない（``email_conflict``。警告ログ）。
    同時ログインによる一意制約違反は、セーブポイントで吸収して既存の行として扱う。

    Args:
        session: AP のセッション（テナントコンテキスト下）。コミットは本関数が行う。失敗時はロールバックする。
        tenant_id: ログイン先のテナント ID（レジストリで検証済みの値）。コンテキストと一致すること。
        idp_subject: IdP の利用者 ID（トークンの ``sub``）。
        email: メールアドレス（トークンの ``email``。無ければ ``None``）。
        display_name: 表示名（トークンの ``name``、無ければ ``preferred_username`` を推奨）。空なら メール → ``sub`` の順で代用する。

    Returns:
        UserSyncResult: 結果。

    Raises:
        UserDeactivatedError: ユーザーが無効化されている。
        TenantContextMismatchError: ``tenant_id`` がコンテキストと一致しない。
        modules.tenancy.context.TenantContextMissingError: コンテキストが無い。
        ValueError: ``idp_subject`` が空。
        sqlalchemy.exc.SQLAlchemyError: DB の操作に失敗した。
    """
    ctx = _require_context(tenant_id)
    if not idp_subject:
        raise ValueError("idp_subject must not be empty")
    normalized_email = _normalize_email(email)
    name = (display_name or "").strip() or normalized_email or idp_subject
    now = utc_now()

    try:
        user = user_repo.get_user_by_subject(session, idp_subject, for_update=True)
        created = False
        if user is None:
            user, created = _create_user_from_login(session, ctx, idp_subject=idp_subject, email=normalized_email, display_name=name)
        if not user.is_active:
            raise UserDeactivatedError(user.id)

        profile_updated, email_conflict = (False, False) if created else _sync_profile(session, ctx, user, email=normalized_email, display_name=name)
        if created and normalized_email and user.email is None:
            email_conflict = True
        user.last_login_at = now
        default_organization_id = ensure_default_organization(session, ctx)
        session.flush()
        result = UserSyncResult(user_id=user.id, created=created, profile_updated=profile_updated, email_conflict=email_conflict, default_organization_id=default_organization_id)
        session.commit()
    except Exception:
        session.rollback()
        raise

    if created:
        logger.info("ログイン時にユーザー行を作成しました: tenant_id=%s user_id=%s", ctx.tenant_id, result.user_id)
    return result


def ensure_default_organization(session: Session, ctx: TenantContext) -> uuid.UUID | None:
    """テナントに組織の行が 1 件も無ければ（論理削除済みを含む）デフォルト組織を作る（PF-ORG-04。コミットしない）。

    同時ログインで 2 つ作られないよう、作成はセーブポイントの中で行い、組織名の一意制約違反は「既に作られた」として扱う。

    Args:
        session: AP のセッション（テナントコンテキスト下）。
        ctx: テナントコンテキスト。

    Returns:
        uuid.UUID | None: 作成した組織の ID。作成しなかった場合は ``None``。
    """
    if org_repo.any_organization_exists(session):
        return None
    organization = TOrganization(tenant_id=ctx.tenant_id, name=DEFAULT_ORGANIZATION_NAME)
    try:
        with session.begin_nested():
            session.add(organization)
            record_audit(session, ctx, actor_id=None, action=ACTION_ORGANIZATION_CREATE, target_type="organization", target_id=organization.id,
                         payload={"name": organization.name, "source": "default"})
            session.flush()
    except IntegrityError:
        logger.info("デフォルト組織は同時に作成されました: tenant_id=%s", ctx.tenant_id)
        return None
    logger.info("デフォルト組織を作成しました: tenant_id=%s organization_id=%s", ctx.tenant_id, organization.id)
    return organization.id


def require_active_session_user(session: Session, *, idp_subject: str) -> uuid.UUID:
    """セッションのユーザーが AP で有効かを確認し、AP のユーザー ID を返す（PF-USR-03 のセッション失効。読み取りのみ）。

    AP の各リクエストで呼ぶ（AP のルーターの依存関数から。auth-keycloak / fastapi-api-schema 担当が組み込む）。
    例外の場合、呼び出し側はセッションを破棄して 401 を返す。無効化は ``t_user.is_active`` を正とするため、
    無効化した直後の次のリクエストから拒否される（キャッシュしない）。

    Args:
        session: AP のセッション（テナントコンテキスト下）。
        idp_subject: セッションのユーザーの ``sub``。

    Returns:
        uuid.UUID: AP のユーザー ID。

    Raises:
        UserDeactivatedError: ユーザーが無効化されている。
        UserNotSyncedError: ユーザー行が無い（同期前のセッション）。
    """
    user = user_repo.get_user_by_subject(session, idp_subject)
    if user is None:
        raise UserNotSyncedError()
    if not user.is_active:
        raise UserDeactivatedError(user.id)
    return user.id


# --------------------------------------------------------------------------- 補助


def _require_context(tenant_id: uuid.UUID) -> TenantContext:
    """テナントコンテキストを取得し、``tenant_id`` と一致することを確認する。"""
    ctx = require_tenant_context()
    if ctx.tenant_id != tenant_id:
        raise TenantContextMismatchError("tenant_id does not match the tenant context")
    return ctx


def _normalize_email(email: str | None) -> str | None:
    """メールアドレスの前後の空白を除く（空なら ``None``）。大文字小文字は IdP の値のまま保存する。"""
    if email is None:
        return None
    value = email.strip()
    return value or None


def _email_available(session: Session, email: str | None, user_id: uuid.UUID | None) -> bool:
    """メールアドレスが、テナント内の別のユーザー行で使われていないか。"""
    if email is None:
        return True
    owner = user_repo.find_user_id_by_email(session, email)
    return owner is None or owner == user_id


def _create_user_from_login(session: Session, ctx: TenantContext, *, idp_subject: str, email: str | None, display_name: str) -> tuple[TUser, bool]:
    """ログイン時にユーザー行を作る。同時ログインで先に作られていた場合は、その行を返す。

    Returns:
        tuple[TUser, bool]: ユーザーと、今回作成したか。
    """
    stored_email = email if _email_available(session, email, None) else None
    if email and stored_email is None:
        logger.warning("メールアドレスが別のユーザー行で使われているため、メールアドレスなしで作成します: tenant_id=%s", ctx.tenant_id)
    user = TUser(tenant_id=ctx.tenant_id, idp_subject=idp_subject, email=stored_email, display_name=display_name)
    try:
        with session.begin_nested():
            session.add(user)
            record_audit(session, ctx, actor_id=None, action=ACTION_USER_CREATE, target_type="user", target_id=user.id,
                         payload={"source": "login", "email": stored_email, "display_name": display_name})
            session.flush()
    except IntegrityError:
        existing = user_repo.get_user_by_subject(session, idp_subject, for_update=True)
        if existing is None:
            raise
        return existing, False
    return user, True


def _sync_profile(session: Session, ctx: TenantContext, user: TUser, *, email: str | None, display_name: str) -> tuple[bool, bool]:
    """既存のユーザー行の表示名・メールアドレスを IdP の値に揃える。

    トークンにメールアドレスが無い（``email`` が None）場合は、保存済みの値を消さずに残す。
    消すと同じアドレスを別のユーザーが取れてしまい、元のユーザーの次回ログインが ``email_conflict`` になるため。

    Returns:
        tuple[bool, bool]: 更新したか、メールアドレスの重複で同期しなかったか。
    """
    changes: dict[str, dict] = {}
    email_conflict = False
    if user.display_name != display_name:
        changes["display_name"] = change(user.display_name, display_name)
        user.display_name = display_name
    if email is not None and user.email != email:
        if _email_available(session, email, user.id):
            changes["email"] = change(user.email, email)
            user.email = email
        else:
            email_conflict = True
            logger.warning("メールアドレスが別のユーザー行で使われているため同期しません: tenant_id=%s user_id=%s", ctx.tenant_id, user.id)
    if not changes:
        return False, email_conflict
    before_version = user.version
    user.version = before_version + 1
    user.updated_by = None
    record_audit(session, ctx, actor_id=None, action=ACTION_USER_SYNC, target_type="user", target_id=user.id,
                 payload={"source": "login", "changes": changes, "version": change(before_version, user.version)})
    return True, email_conflict
