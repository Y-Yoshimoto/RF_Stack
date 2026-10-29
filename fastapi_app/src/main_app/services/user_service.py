#!/usr/bin/env python
# coding:utf-8
"""テナント内のユーザー管理（01 §8 PF-USR-01..03、§7.5。``/api/v1/users`` から使う）。

FastAPI に依存しない。AP のセッション（テナントコンテキスト下、``app_runtime``）と、テナントレルムの
``tenant-user-admin`` の管理クライアントを作る関数を受け取り、**コミットはサービスが行う**。
認可（``tenant_admin`` のみ変更可）はルーターで行う。テナントはコンテキストから得る（引数に取らない）。

使用例（ルーターから）::

    service = UserService(session)                                   # session: AppSessionDep
    result = service.create_user(email="alice@example.com", first_name="Alice", last_name="Liddell", roles=["member"])
    # result.temporary_password はレスポンスで一度だけ返す（Cache-Control: no-store）。ログ・DB に残さない
    view = service.update_user(user_id, expected_version=if_match, is_active=False)

公開メソッドと例外（HTTP ステータスは :mod:`main_app.services.errors`）:

| メソッド | 例外 |
| --- | --- |
| :meth:`UserService.list_users` | ``UserValidationError``（並び替えキー、``ids`` の形式・件数） |
| :meth:`UserService.get_user` | ``UserNotFoundError``, ``IdentityProviderOperationError`` |
| :meth:`UserService.get_user_roles` | ``UserNotFoundError``, ``IdentityProviderOperationError`` |
| :meth:`UserService.create_user` | ``UserValidationError``, ``InvalidUserRoleError``, ``UserAlreadyExistsError``, ``IdentityProviderOperationError`` |
| :meth:`UserService.update_user` | ``UserNotFoundError``, ``UserVersionConflictError``, ``UserValidationError``, ``InvalidUserRoleError``, ``UserSelfModificationError``, ``IdentityProviderOperationError`` |

IdP と AP の DB の整合:
    - 作成: IdP にユーザーを作成（一時パスワード・ロール）→ AP の行と監査ログをコミット。AP 側が失敗したら IdP のユーザーを削除する（補償）
    - 更新: AP の行をロック（``SELECT ... FOR UPDATE``）して ``version`` を確認 → IdP を変更 → AP の行と監査ログをコミット。
      IdP が失敗したら AP は変更しない（502）。IdP の操作は同じ値の再実行で同じ状態に収束する
    - 表示名は IdP の姓・名から作る（``"{名} {姓}"``。Keycloak の ``name`` クレームと同じ）。ログイン時の同期（PF-USR-04）で上書きされないよう、
      変更は IdP の姓・名に対して行う

姓・名・ロールの写し（``t_user.first_name`` / ``last_name`` / ``roles``）:
    IdP が正で、AP の DB には一覧表示用の写しを持つ（一覧でユーザーごとに IdP へ問い合わせないため）。写しは次のときに更新する。
    - ログイン時の同期（:func:`main_app.services.user_sync.sync_user_on_login`。トークンの ``given_name`` / ``family_name`` / レルムロール）
    - 作成・更新（:meth:`UserService.create_user` / :meth:`UserService.update_user`。IdP に設定した値）
    - 詳細の取得（:meth:`UserService.get_user`。IdP から取り直し、違えば写しを更新してコミットする）
    ロールの写しは実効ロール（レルムの既定ロール ``member`` を含む）のうち ``tenant_admin`` / ``member``。作成・更新では
    IdP に問い合わせ直さず「直接付与したロール + 既定ロール（``TENANT_DEFAULT_ROLES``）」とする。

無効化（PF-USR-03）:
    IdP のユーザーを無効化し、IdP のセッションをすべて失効させる（リフレッシュトークンが使えなくなる）。AP の ``is_active`` を
    false にし、BFF のセッションは次のリクエストで :func:`main_app.services.user_sync.require_active_session_user` により拒否する。
    ``tenant_admin`` を外した場合も IdP のセッションを失効させる（BFF のセッションのロールはログイン時の値のため、
    アクセストークンの期限で更新に失敗させて再ログインを促す）。
"""
import logging
import re
import secrets
import string
import uuid
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from main_app.models import TUser
from main_app.repositories import users as user_repo
from main_app.repositories.keyset import ListSort, Page, normalize_limit
from main_app.services.common import UNSET, Maybe, UserView, change, normalize_tenant_roles, record_audit, resolve_actor_id, summarize_idp_error
from main_app.services.errors import (
    IdentityProviderOperationError,
    InvalidUserRoleError,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserSelfModificationError,
    UserValidationError,
    UserVersionConflictError,
)
from main_app.services.user_sync import apply_idp_profile
from modules.keycloak_admin import tenant_users as kc_users
from modules.keycloak_admin.admin_client import KeycloakAdminClient
from modules.keycloak_admin.errors import KeycloakAdminError
from modules.keycloak_admin.models import UserSpec
from modules.keycloak_admin.templates import TENANT_DEFAULT_ROLES, TENANT_ROLES, create_tenant_user_admin_client, tenant_realm_name
from modules.tenancy.context import TenantContext, require_tenant_context

logger = logging.getLogger(__name__)

# 付与できるロール（01 §7.5。realm-management のロール等は付与させない）
ROLE_TENANT_ADMIN = "tenant_admin"
ROLE_MEMBER = "member"
ASSIGNABLE_ROLES: tuple[str, ...] = TENANT_ROLES
DEFAULT_ROLES: tuple[str, ...] = (ROLE_MEMBER,)

# 入力の上限
EMAIL_MAX_LENGTH = 254
NAME_MAX_LENGTH = 100
USERNAME_MAX_LENGTH = 255
_EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_USERNAME_PATTERN = re.compile(r"[A-Za-z0-9._@+-]{3,255}")

# 一覧の並び替えキー
USER_SORT_KEYS: tuple[str, ...] = tuple(user_repo.USER_SORT_COLUMNS)

# 一覧の ID 指定（``ids``）の上限（重複を除いた件数）
MAX_LIST_USER_IDS = 100

# 一時パスワード（01 PF-USR-02）
TEMPORARY_PASSWORD_LENGTH = 20
_PASSWORD_SYMBOLS = "!@#$%^&*-_=+"
_PASSWORD_CLASSES = (string.ascii_lowercase, string.ascii_uppercase, string.digits, _PASSWORD_SYMBOLS)

# 監査ログの操作（03 §7）
ACTION_USER_CREATE = "user.create"
ACTION_USER_UPDATE = "user.update"
ACTION_USER_ACTIVATE = "user.activate"
ACTION_USER_DEACTIVATE = "user.deactivate"

# tenant-user-admin の管理クライアントを作る関数（引数はテナントレルム名）
type TenantUserAdminFactory = Callable[[str], KeycloakAdminClient]


def generate_temporary_password(length: int = TEMPORARY_PASSWORD_LENGTH) -> str:
    """一時パスワードを生成する（英大文字・英小文字・数字・記号を最低 1 文字ずつ含む）。

    Args:
        length: 長さ（4 以上）。

    Returns:
        str: 一時パスワード。**ログ・DB・監査ログに残さないこと。**
    """
    if length < len(_PASSWORD_CLASSES):
        raise ValueError("length is too short")
    alphabet = "".join(_PASSWORD_CLASSES)
    chars = [secrets.choice(chars) for chars in _PASSWORD_CLASSES] + [secrets.choice(alphabet) for _ in range(length - len(_PASSWORD_CLASSES))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def compose_display_name(first_name: str, last_name: str) -> str:
    """IdP の姓・名から表示名を作る（Keycloak の ``name`` クレームと同じ ``"{名} {姓}"``）。"""
    return " ".join(part for part in (first_name.strip(), last_name.strip()) if part)


@dataclass(frozen=True, slots=True, kw_only=True)
class UserCreateResult:
    """:meth:`UserService.create_user` の結果。

    Attributes:
        user: 作成したユーザー。
        username: ログインに使うユーザー名。
        roles: 付与したロール。
        temporary_password: 一時パスワード。**レスポンスで一度だけ返し、どこにも保存しない**（PF-USR-02）。
    """

    user: UserView
    username: str
    roles: tuple[str, ...]
    temporary_password: str

    def __repr__(self) -> str:
        """一時パスワードを含めない。"""
        return f"UserCreateResult(user={self.user!r}, username={self.username!r}, roles={self.roles!r}, temporary_password=***)"


class UserService:
    """テナント内のユーザー管理（1 リクエストごとにインスタンスを作る）。

    Args:
        session: AP のセッション（テナントコンテキスト下）。
        kc_admin_factory: テナントレルム名から ``tenant-user-admin`` の管理クライアントを作る関数
            （既定 :func:`modules.keycloak_admin.templates.create_tenant_user_admin_client`。1 操作ごとに作って閉じる）。
        actor_subject: 操作者の IdP の利用者 ID。省略時はテナントコンテキストの ``user_id``（セッションの ``sub``）。
        password_generator: 一時パスワードの生成関数（テスト用）。
    """

    def __init__(
        self,
        session: Session,
        kc_admin_factory: TenantUserAdminFactory = create_tenant_user_admin_client,
        *,
        actor_subject: str | None = None,
        password_generator: Callable[[], str] = generate_temporary_password,
    ) -> None:
        """依存を保持する（DB・Keycloak にはまだ接続しない）。"""
        self._session = session
        self._kc_admin_factory = kc_admin_factory
        self._actor_subject = actor_subject
        self._password_generator = password_generator

    # ------------------------------------------------------------------ 参照
    def list_users(
        self,
        *,
        limit: int = 50,
        sort: str = user_repo.DEFAULT_USER_SORT,
        after: tuple[Any, uuid.UUID] | None = None,
        is_active: bool | None = None,
        ids: Sequence[uuid.UUID] | None = None,
    ) -> Page[UserView]:
        """テナント内のユーザーの一覧（無効化されたユーザーを含む。``is_active`` / ``ids`` で絞り込める）。

        姓・名・ロールは AP の DB の写し（最後に同期した時点の値。IdP には問い合わせない）。

        Args:
            limit: 件数（1〜200 に補正）。
            sort: 並び替え（``display_name`` / ``created_at``、先頭の ``-`` で降順）。
            after: 起点（前のページの ``next_after``）。
            is_active: 有効/無効で絞り込む。
            ids: ユーザー ID で絞り込む（組織のメンバー・ToDo の担当者の表示用。重複は除き最大 :data:`MAX_LIST_USER_IDS` 件）。
                存在しない ID・他テナントの ID は結果に含まれない（エラーにしない）。空なら 0 件。

        Returns:
            Page[UserView]: ページ。

        Raises:
            UserValidationError: 並び替えキーが不正（``field="sort"``）、``ids`` が不正（``field="ids"``、
                ``reason`` は ``type`` / ``format`` / ``too_many``）。
        """
        require_tenant_context()
        try:
            list_sort = ListSort.parse(sort, USER_SORT_KEYS)
        except ValueError:
            raise UserValidationError("sort", "unsupported") from None
        id_filter = None if ids is None else _validate_ids(ids)
        page = user_repo.list_users(self._session, sort=list_sort, after=after, limit=normalize_limit(limit), is_active=is_active, ids=id_filter)
        return Page(items=[UserView.from_model(user) for user in page.items], next_after=page.next_after)

    def get_user(self, user_id: uuid.UUID) -> UserView:
        """ユーザーを取得する。姓・名・メール・ロールは IdP を正として取り直し、写しと違えば更新してコミットする。

        - 表示名は IdP の姓・名から作る（どちらも未設定なら保存済みの表示名のまま）。メールは IdP で未設定なら保存済みの値を残す
        - 値が変わったら ``version`` を +1 し、監査ログ ``user.sync``（``source=idp``）を残す。写しの初回の埋め込みだけなら
          ``version`` は変えない（:func:`main_app.services.user_sync.apply_idp_profile`）
        - 有効/無効（``is_active``）は AP の DB を正とし、ここでは変えない（PF-USR-03 のセッション失効の判定に使うため）
        - IdP にユーザーが無い（IdP で直接削除された）場合は、警告ログを残して写しのまま返す
        - IdP への問い合わせ中は DB のトランザクションを持たない（問い合わせの後で行をロックして比較する）

        Raises:
            UserNotFoundError: 存在しない（他テナントを含む。IdP には問い合わせない）。
            IdentityProviderOperationError: IdP の問い合わせに失敗した（AP の DB は変更しない）。
        """
        ctx = require_tenant_context()
        subject = self._require_user(user_id).idp_subject
        self._session.rollback()  # IdP の問い合わせの間、トランザクション（とスナップショット）を持たない
        realm = tenant_realm_name(ctx.tenant_code)
        operation = "get_user"
        try:
            with self._kc_admin_factory(realm) as admin:
                representation = kc_users.get_user(admin, realm, subject)
                effective: list[str] = []
                if representation is not None:
                    operation = "get_user_roles"
                    effective = kc_users.get_user_effective_realm_roles(admin, realm, subject)
        except KeycloakAdminError as exc:
            raise IdentityProviderOperationError(operation, summarize_idp_error(operation, exc)) from exc

        try:
            user = self._require_user(user_id, for_update=True)
            if representation is None:
                logger.warning("IdP にユーザーが見つからないため、写しのまま返します: tenant_id=%s user_id=%s", ctx.tenant_id, user.id)
                view = UserView.from_model(user)
                self._session.rollback()
                return view
            first_name = _idp_name(representation.get("firstName"))
            last_name = _idp_name(representation.get("lastName"))
            composed = compose_display_name(first_name or "", last_name or "")
            email = representation.get("email") if isinstance(representation.get("email"), str) else None
            updated, _ = apply_idp_profile(
                self._session, ctx, user, source="idp", email=(email or "").strip() or None, display_name=composed or UNSET,
                first_name=first_name, last_name=last_name, roles=normalize_tenant_roles(effective),
            )
            self._session.flush()
            view = UserView.from_model(user)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        if updated:
            logger.info("詳細の取得で IdP の値に同期しました: tenant_id=%s user_id=%s", ctx.tenant_id, view.id)
        return view

    def get_user_roles(self, user_id: uuid.UUID) -> list[str]:
        """ユーザーの実効ロールのうち、テナントのロール（``tenant_admin`` / ``member``）を返す（IdP に問い合わせる）。

        Raises:
            UserNotFoundError: 存在しない（他テナントを含む）。
            IdentityProviderOperationError: IdP の問い合わせに失敗した。
        """
        ctx = require_tenant_context()
        user = self._require_user(user_id)
        realm = tenant_realm_name(ctx.tenant_code)
        try:
            with self._kc_admin_factory(realm) as admin:
                effective = kc_users.get_user_effective_realm_roles(admin, realm, user.idp_subject)
        except KeycloakAdminError as exc:
            raise IdentityProviderOperationError("get_user_roles", summarize_idp_error("get_user_roles", exc)) from exc
        return [role for role in ASSIGNABLE_ROLES if role in effective]

    # ------------------------------------------------------------------ 作成（PF-USR-01 / 02）
    def create_user(self, *, email: str, first_name: str, last_name: str, roles: Sequence[str] = DEFAULT_ROLES, username: str | None = None) -> UserCreateResult:
        """IdP のテナントレルムにユーザーを作成し、AP のユーザー行を作成してコミットする（PF-USR-01 / 02）。

        IdP のユーザーは一時パスワード（初回ログイン時に変更必須）・メール確認済みで作る。メールは送らない。

        Args:
            email: メールアドレス（テナント内で一意。PF-USR-06）。
            first_name: 名。
            last_name: 姓。
            roles: 付与するロール（``tenant_admin`` / ``member`` のみ。1 つ以上）。
            username: ログインに使うユーザー名（省略時はメールアドレス）。

        Returns:
            UserCreateResult: 結果（一時パスワードを含む）。

        Raises:
            UserValidationError: 入力が不正。
            InvalidUserRoleError: 付与できないロール。
            UserAlreadyExistsError: ユーザー名・メールアドレスが既に使われている。
            IdentityProviderOperationError: IdP の操作に失敗した（AP の DB は変更していない）。
        """
        ctx = require_tenant_context()
        email = _validate_email(email)
        first_name = _validate_name("first_name", first_name)
        last_name = _validate_name("last_name", last_name)
        role_list = _validate_roles(roles)
        login_username = _validate_username(username if username is not None else email)
        display_name = compose_display_name(first_name, last_name)
        realm = tenant_realm_name(ctx.tenant_code)

        if user_repo.find_user_id_by_email(self._session, email) is not None:
            raise UserAlreadyExistsError()
        actor_id = resolve_actor_id(self._session, ctx, self._actor_subject)
        temporary_password = self._password_generator()
        spec = UserSpec(username=login_username, enabled=True, email=email, email_verified=True, first_name=first_name, last_name=last_name, required_actions=("UPDATE_PASSWORD",))

        with self._kc_admin_factory(realm) as admin:
            try:
                idp_subject = kc_users.create_user(admin, realm, spec, password=temporary_password, temporary=True, roles=role_list, allowed_roles=ASSIGNABLE_ROLES)
            except KeycloakAdminError as exc:
                self._session.rollback()
                if exc.status_code == 409:
                    raise UserAlreadyExistsError() from exc
                raise IdentityProviderOperationError("create_user", summarize_idp_error("create_user", exc)) from exc

            try:
                user = TUser(
                    tenant_id=ctx.tenant_id, idp_subject=idp_subject, email=email, display_name=display_name, first_name=first_name, last_name=last_name,
                    roles=_effective_roles(role_list), created_by=actor_id, updated_by=actor_id,
                )
                self._session.add(user)
                record_audit(self._session, ctx, actor_id=actor_id, action=ACTION_USER_CREATE, target_type="user", target_id=user.id,
                             payload={"source": "admin", "username": login_username, "email": email, "display_name": display_name, "roles": role_list})
                self._session.flush()
                view = UserView.from_model(user)
                self._session.commit()
            except Exception as exc:
                self._session.rollback()
                self._compensate_created_user(admin, realm, idp_subject)
                if isinstance(exc, IntegrityError):
                    raise UserAlreadyExistsError() from exc
                raise

        logger.info("ユーザーを作成しました: tenant_id=%s user_id=%s", ctx.tenant_id, view.id)
        return UserCreateResult(user=view, username=login_username, roles=tuple(role_list), temporary_password=temporary_password)

    # ------------------------------------------------------------------ 更新（PF-USR-03）
    def update_user(
        self,
        user_id: uuid.UUID,
        *,
        expected_version: int,
        first_name: Maybe[str] = UNSET,
        last_name: Maybe[str] = UNSET,
        roles: Maybe[Sequence[str]] = UNSET,
        is_active: Maybe[bool] = UNSET,
    ) -> UserView:
        """ユーザーの姓・名（表示名）・ロール・有効/無効を更新してコミットする（送られた項目だけ。03 §1 の PATCH）。

        - 姓・名: 両方を指定する。IdP の姓・名を更新し、表示名を ``"{名} {姓}"`` にする
        - ロール: 直接付与するロールの集合（``tenant_admin`` / ``member`` のみ、1 つ以上）。それ以外のロールには触れない。
          ``member`` はレルムの既定ロールでも付与されるため、``["member"]`` は「``tenant_admin`` を外す」の意味になる
        - 有効/無効: IdP のユーザーも切り替える。無効化時は IdP のセッションを失効させる
        - 自分自身の無効化・``tenant_admin`` の解除は拒否する（テナントの管理者不在を防ぐ）
        - 変更が無ければ何もしない（``version`` も変えない）
        - 写し: 姓・名を IdP に設定したら ``first_name`` / ``last_name`` を、ロールを変えたら ``roles``（直接付与 + 既定ロール）を更新する。
          監査ログの ``changes`` には表示名・ロール（直接付与の前後）・有効/無効と、写しが既知だった場合の姓・名の差分を残す

        Args:
            user_id: ユーザー ID。
            expected_version: ``If-Match`` のバージョン。
            first_name: 名。
            last_name: 姓。
            roles: 直接付与するロール。
            is_active: 有効にするか。

        Returns:
            UserView: 更新後のユーザー。

        Raises:
            UserNotFoundError: 存在しない（他テナントを含む）。
            UserVersionConflictError: バージョンが一致しない。
            UserValidationError: 入力が不正（姓・名の片方だけ、空など）。
            InvalidUserRoleError: 付与できないロール。
            UserSelfModificationError: 自分自身の無効化・``tenant_admin`` の解除。
            IdentityProviderOperationError: IdP の操作に失敗した（AP の DB は変更していない）。
        """
        ctx = require_tenant_context()
        names = _validate_name_pair(first_name, last_name)
        role_list = UNSET if roles is UNSET else _validate_roles(roles)
        if is_active is not UNSET and not isinstance(is_active, bool):
            raise UserValidationError("is_active", "type")

        try:
            user = self._require_user(user_id, for_update=True)
            if user.version != expected_version:
                raise UserVersionConflictError(user.id, expected_version, user.version)
            actor_id = resolve_actor_id(self._session, ctx, self._actor_subject)
            if actor_id == user.id:
                if is_active is False:
                    raise UserSelfModificationError("deactivate")
                if role_list is not UNSET and ROLE_TENANT_ADMIN not in role_list:
                    raise UserSelfModificationError("remove_tenant_admin")

            changes = self._apply_idp_changes(ctx, user, names=names, roles=role_list, is_active=is_active)
            if not changes:
                view = UserView.from_model(user)
                self._session.rollback()
                return view

            if "display_name" in changes:
                user.display_name = changes["display_name"]["after"]
            if names is not None and changes.keys() & {"display_name", "first_name", "last_name"}:
                user.first_name, user.last_name = names  # IdP に設定した姓・名を写しにする
            if "roles" in changes:
                user.roles = _effective_roles(changes["roles"]["after"])
            if "is_active" in changes:
                user.is_active = changes["is_active"]["after"]
            before_version = user.version
            user.version = before_version + 1
            user.updated_by = actor_id
            action = ACTION_USER_UPDATE
            if "is_active" in changes:
                action = ACTION_USER_ACTIVATE if user.is_active else ACTION_USER_DEACTIVATE
            record_audit(self._session, ctx, actor_id=actor_id, action=action, target_type="user", target_id=user.id,
                         payload={"changes": changes, "version": change(before_version, user.version)})
            self._session.flush()
            view = UserView.from_model(user)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        logger.info("ユーザーを更新しました: tenant_id=%s user_id=%s fields=%s", ctx.tenant_id, view.id, sorted(changes))
        return view

    # ------------------------------------------------------------------ 補助
    def _require_user(self, user_id: uuid.UUID, *, for_update: bool = False) -> TUser:
        """ユーザーを取得する。無ければ :class:`UserNotFoundError`。"""
        user = user_repo.get_user(self._session, user_id, for_update=for_update)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    def _apply_idp_changes(self, ctx: TenantContext, user: TUser, *, names: tuple[str, str] | None, roles: Maybe[list[str]], is_active: Maybe[bool]) -> dict[str, dict]:
        """IdP 側の変更（姓・名、ロール、有効/無効とセッション失効）を行い、監査ログに残す差分を返す。

        Returns:
            dict[str, dict]: 項目ごとの ``{"before": ..., "after": ...}``（変更の無い項目は含めない）。

        Raises:
            IdentityProviderOperationError: IdP の操作に失敗した。
        """
        new_display_name = compose_display_name(*names) if names is not None else None
        name_changed = names is not None and (new_display_name != user.display_name or _names_differ(user, names))
        active_changed = is_active is not UNSET and is_active != user.is_active
        if not name_changed and roles is UNSET and not active_changed:
            return {}

        realm = tenant_realm_name(ctx.tenant_code)
        subject = user.idp_subject
        changes: dict[str, dict] = {}
        operation = "update_user"
        try:
            with self._kc_admin_factory(realm) as admin:
                if name_changed and names is not None:
                    operation = "update_user_names"
                    kc_users.update_user_names(admin, realm, subject, first_name=names[0], last_name=names[1])
                    if new_display_name != user.display_name:
                        changes["display_name"] = change(user.display_name, new_display_name)
                    # 写しが既知の場合だけ姓・名の差分も残す（表示名が同じでも姓・名の区切りが変わる場合がある）
                    if user.first_name is not None and user.first_name != names[0]:
                        changes["first_name"] = change(user.first_name, names[0])
                    if user.last_name is not None and user.last_name != names[1]:
                        changes["last_name"] = change(user.last_name, names[1])
                revoke_sessions = False
                if roles is not UNSET:
                    operation = "set_user_roles"
                    role_change = kc_users.set_user_realm_roles(admin, realm, subject, roles, allowed_roles=ASSIGNABLE_ROLES)
                    if role_change.changed:
                        changes["roles"] = change(list(role_change.before), list(role_change.after))
                        revoke_sessions = ROLE_TENANT_ADMIN in role_change.removed
                if active_changed:
                    operation = "set_user_enabled"
                    kc_users.set_user_enabled(admin, realm, subject, bool(is_active))
                    changes["is_active"] = change(user.is_active, is_active)
                    revoke_sessions = revoke_sessions or is_active is False
                if revoke_sessions:
                    operation = "logout_user"
                    kc_users.logout_user(admin, realm, subject)
        except (KeycloakAdminError, ValueError) as exc:
            summary = summarize_idp_error(operation, exc)
            logger.warning("ユーザーの更新で IdP の操作に失敗しました: tenant_id=%s user_id=%s %s", ctx.tenant_id, user.id, summary)
            raise IdentityProviderOperationError(operation, summary) from exc
        return changes

    def _compensate_created_user(self, admin: KeycloakAdminClient, realm: str, idp_subject: str) -> None:
        """AP の行を作れなかった場合に、作成した IdP のユーザーを削除する（失敗はログに残すだけ）。"""
        try:
            kc_users.delete_user_if_exists(admin, realm, idp_subject)
        except KeycloakAdminError as exc:
            logger.error("AP の行を作成できなかった IdP のユーザーを削除できませんでした（手動で削除が必要）: realm=%s %s", realm, summarize_idp_error("delete_user", exc))


# --------------------------------------------------------------------------- 写し


def _names_differ(user: TUser, names: tuple[str, str]) -> bool:
    """姓・名の写しが ``names`` と違うか（写しが未同期 = 両方 NULL の場合は違わないとみなす。表示名で判定する）。"""
    if user.first_name is None and user.last_name is None:
        return False
    return (user.first_name, user.last_name) != names


def _effective_roles(direct_roles: Collection[str]) -> list[str]:
    """直接付与したロールから、写しに入れる実効ロール（レルムの既定ロールを加える）を作る。"""
    return normalize_tenant_roles([*direct_roles, *TENANT_DEFAULT_ROLES])


def _idp_name(value: object) -> str | None:
    """IdP の ``firstName`` / ``lastName`` を写しの値にする（前後の空白を除く。未設定・空は ``None``）。"""
    if not isinstance(value, str):
        return None
    return value.strip() or None


# --------------------------------------------------------------------------- 入力検証


def _validate_email(email: str) -> str:
    """メールアドレスを検証する（前後の空白を除く）。"""
    if not isinstance(email, str) or not email.strip():
        raise UserValidationError("email", "required")
    value = email.strip()
    if len(value) > EMAIL_MAX_LENGTH:
        raise UserValidationError("email", "too_long")
    if not _EMAIL_PATTERN.fullmatch(value):
        raise UserValidationError("email", "format")
    return value


def _validate_name(field: str, value: str) -> str:
    """姓・名を検証する（前後の空白を除く。制御文字は不可）。"""
    if not isinstance(value, str) or not value.strip():
        raise UserValidationError(field, "required")
    stripped = value.strip()
    if len(stripped) > NAME_MAX_LENGTH:
        raise UserValidationError(field, "too_long")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in stripped):
        raise UserValidationError(field, "format")
    return stripped


def _validate_name_pair(first_name: Maybe[str], last_name: Maybe[str]) -> tuple[str, str] | None:
    """更新の姓・名を検証する（両方指定するか、両方省略する）。"""
    if first_name is UNSET and last_name is UNSET:
        return None
    if first_name is UNSET:
        raise UserValidationError("first_name", "required")
    if last_name is UNSET:
        raise UserValidationError("last_name", "required")
    return _validate_name("first_name", first_name), _validate_name("last_name", last_name)


def _validate_username(username: str) -> str:
    """ユーザー名を検証する（Keycloak は小文字に正規化して保存するため、ここで小文字にする）。"""
    if not isinstance(username, str) or not username.strip():
        raise UserValidationError("username", "required")
    value = username.strip().lower()
    if len(value) > USERNAME_MAX_LENGTH:
        raise UserValidationError("username", "too_long")
    if not _USERNAME_PATTERN.fullmatch(value):
        raise UserValidationError("username", "format")
    return value


def _validate_roles(roles: Sequence[str]) -> list[str]:
    """ロールを検証する（``tenant_admin`` / ``member`` のみ、1 つ以上、重複は除く）。"""
    if isinstance(roles, str) or not isinstance(roles, Sequence):
        raise UserValidationError("roles", "type")
    unique = list(dict.fromkeys(roles))
    if not unique:
        raise UserValidationError("roles", "required")
    disallowed = [role for role in unique if role not in ASSIGNABLE_ROLES]
    if disallowed:
        raise InvalidUserRoleError(disallowed)
    return unique


def _validate_ids(ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
    """一覧の ``ids`` を検証し、重複を除いて返す（指定順）。"""
    if isinstance(ids, str) or not isinstance(ids, Sequence):
        raise UserValidationError("ids", "type")
    if not all(isinstance(user_id, uuid.UUID) for user_id in ids):
        raise UserValidationError("ids", "format")
    unique = list(dict.fromkeys(ids))
    if len(unique) > MAX_LIST_USER_IDS:
        raise UserValidationError("ids", "too_many")
    return unique
