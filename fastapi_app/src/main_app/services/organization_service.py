#!/usr/bin/env python
# coding:utf-8
"""テナント内の組織管理（01 §8 PF-ORG-01..03、§7.5。``/api/v1/organizations`` から使う）。

FastAPI に依存しない。AP のセッション（テナントコンテキスト下、``app_runtime``）を受け取り、**コミットはサービスが行う**。
認可（``tenant_admin`` のみ変更可）はルーターで行う。テナントはコンテキストから得る（引数に取らない）。

使用例（ルーターから）::

    service = OrganizationService(session)                                   # session: AppSessionDep
    view = service.create_organization(name="開発部")
    view = service.set_members(view.id, expected_version=view.version, user_ids=[...])

公開メソッドと例外（HTTP ステータスは :mod:`main_app.services.errors`）:

| メソッド | 例外 |
| --- | --- |
| :meth:`OrganizationService.list_organizations` | ``OrganizationValidationError``（並び替えキー） |
| :meth:`OrganizationService.get_organization` / :meth:`OrganizationService.list_member_ids` | ``OrganizationNotFoundError`` |
| :meth:`OrganizationService.list_user_organizations` | （なし） |
| :meth:`OrganizationService.create_organization` | ``OrganizationValidationError``, ``OrganizationNameConflictError`` |
| :meth:`OrganizationService.update_organization` | ``OrganizationNotFoundError``, ``OrganizationVersionConflictError``, ``OrganizationValidationError``, ``OrganizationNameConflictError`` |
| :meth:`OrganizationService.delete_organization` | ``OrganizationNotFoundError``, ``OrganizationVersionConflictError`` |
| :meth:`OrganizationService.set_members` | ``OrganizationNotFoundError``, ``OrganizationVersionConflictError``, ``OrganizationValidationError``, ``InvalidOrganizationMembersError`` |

- 論理削除（``deleted_at``）した組織は、以降のすべての操作で 404 とする（論理削除したデータを返す API は作らない。03 §5.1）。
  所属の行は残す（閲覧範囲の判定で削除済みの組織を除外する。PF-ORG-03）
- 更新・削除・メンバーの全置換は行ロック（``SELECT ... FOR UPDATE``）の下で ``version`` を確認し、+1 する（03 §5.2）
- メンバーには、テナント内に存在するユーザーだけを指定できる（事前チェック。他テナントのユーザーは RLS で見えないため
  「存在しない」と同じになる）。DB の複合外部キーでも拒否される。無効化されたユーザーも指定できる
"""
import logging
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from main_app.models import TOrganization
from main_app.repositories import organizations as org_repo
from main_app.repositories import users as user_repo
from main_app.repositories.keyset import ListSort, Page, normalize_limit
from main_app.services.common import OrganizationView, change, record_audit, resolve_actor_id, utc_now
from main_app.services.errors import (
    InvalidOrganizationMembersError,
    OrganizationNameConflictError,
    OrganizationNotFoundError,
    OrganizationValidationError,
    OrganizationVersionConflictError,
)
from modules.tenancy.context import require_tenant_context

logger = logging.getLogger(__name__)

# 入力の上限
ORGANIZATION_NAME_MAX_LENGTH = 100
MAX_ORGANIZATION_MEMBERS = 1000

# 一覧の並び替えキー
ORGANIZATION_SORT_KEYS: tuple[str, ...] = tuple(org_repo.ORGANIZATION_SORT_COLUMNS)

# 監査ログの操作（03 §7）
ACTION_ORGANIZATION_CREATE = "organization.create"
ACTION_ORGANIZATION_UPDATE = "organization.update"
ACTION_ORGANIZATION_DELETE = "organization.delete"
ACTION_ORGANIZATION_SET_MEMBERS = "organization.set_members"


class OrganizationService:
    """テナント内の組織管理（1 リクエストごとにインスタンスを作る）。

    Args:
        session: AP のセッション（テナントコンテキスト下）。
        actor_subject: 操作者の IdP の利用者 ID。省略時はテナントコンテキストの ``user_id``（セッションの ``sub``）。
    """

    def __init__(self, session: Session, *, actor_subject: str | None = None) -> None:
        """依存を保持する。"""
        self._session = session
        self._actor_subject = actor_subject

    # ------------------------------------------------------------------ 参照
    def list_organizations(self, *, limit: int = 50, sort: str = org_repo.DEFAULT_ORGANIZATION_SORT, after: tuple[Any, uuid.UUID] | None = None) -> Page[OrganizationView]:
        """有効な組織の一覧（論理削除済みを除く）。

        Args:
            limit: 件数（1〜200 に補正）。
            sort: 並び替え（``name`` / ``created_at``、先頭の ``-`` で降順）。
            after: 起点（前のページの ``next_after``）。

        Returns:
            Page[OrganizationView]: ページ。

        Raises:
            OrganizationValidationError: 並び替えキーが不正（``field="sort"``）。
        """
        require_tenant_context()
        try:
            list_sort = ListSort.parse(sort, ORGANIZATION_SORT_KEYS)
        except ValueError:
            raise OrganizationValidationError("sort", "unsupported") from None
        page = org_repo.list_organizations(self._session, sort=list_sort, after=after, limit=normalize_limit(limit))
        return Page(items=[OrganizationView.from_model(org) for org in page.items], next_after=page.next_after)

    def get_organization(self, organization_id: uuid.UUID) -> OrganizationView:
        """組織を取得する。

        Raises:
            OrganizationNotFoundError: 存在しない（他テナント・論理削除済みを含む）。
        """
        require_tenant_context()
        return OrganizationView.from_model(self._require_organization(organization_id))

    def list_member_ids(self, organization_id: uuid.UUID) -> list[uuid.UUID]:
        """組織のメンバーのユーザー ID を返す（ID 順）。

        Raises:
            OrganizationNotFoundError: 存在しない（他テナント・論理削除済みを含む）。
        """
        require_tenant_context()
        self._require_organization(organization_id)
        return org_repo.list_member_ids(self._session, organization_id)

    def list_user_organizations(self, user_id: uuid.UUID) -> list[OrganizationView]:
        """ユーザーが所属する有効な組織を返す（論理削除済みを除く。組織名順。``/api/v1/me`` のプロフィール表示用）。

        1 回のクエリで取得する（組織ごとの詳細の取得は不要）。ページングはしない（所属数は少ない前提。
        組織のメンバー数の上限 :data:`MAX_ORGANIZATION_MEMBERS` はあるが、ユーザーあたりの所属数の上限は無い）。

        Args:
            user_id: ユーザー ID（``t_user.id``。IdP の ``sub`` ではない）。

        Returns:
            list[OrganizationView]: 組織。所属が無い・存在しない・他テナントのユーザーは空（404 にしない）。
        """
        require_tenant_context()
        return [OrganizationView.from_model(org) for org in org_repo.list_active_organizations_of_user(self._session, user_id)]

    # ------------------------------------------------------------------ 変更
    def create_organization(self, *, name: str) -> OrganizationView:
        """組織を作成してコミットする（PF-ORG-01）。

        Raises:
            OrganizationValidationError: 名前が不正。
            OrganizationNameConflictError: 有効な組織に同じ名前がある（大文字小文字を区別しない）。
        """
        ctx = require_tenant_context()
        name = _validate_name(name)
        try:
            if org_repo.find_active_organization_id_by_name(self._session, name) is not None:
                raise OrganizationNameConflictError(name)
            actor_id = resolve_actor_id(self._session, ctx, self._actor_subject)
            organization = TOrganization(tenant_id=ctx.tenant_id, name=name, created_by=actor_id, updated_by=actor_id)
            self._session.add(organization)
            record_audit(self._session, ctx, actor_id=actor_id, action=ACTION_ORGANIZATION_CREATE, target_type="organization", target_id=organization.id,
                         payload={"name": name, "source": "admin"})
            view = self._flush_and_commit(organization, name)
        except Exception:
            self._session.rollback()
            raise
        logger.info("組織を作成しました: tenant_id=%s organization_id=%s", ctx.tenant_id, view.id)
        return view

    def update_organization(self, organization_id: uuid.UUID, *, expected_version: int, name: str) -> OrganizationView:
        """組織名を変更してコミットする（PF-ORG-01）。同じ名前なら何もしない（``version`` も変えない）。

        Raises:
            OrganizationNotFoundError: 存在しない（他テナント・論理削除済みを含む）。
            OrganizationVersionConflictError: バージョンが一致しない。
            OrganizationValidationError: 名前が不正。
            OrganizationNameConflictError: 有効な別の組織に同じ名前がある。
        """
        ctx = require_tenant_context()
        name = _validate_name(name)
        try:
            organization = self._lock_organization(organization_id, expected_version)
            if organization.name == name:
                view = OrganizationView.from_model(organization)
                self._session.rollback()
                return view
            if org_repo.find_active_organization_id_by_name(self._session, name, exclude_id=organization.id) is not None:
                raise OrganizationNameConflictError(name)
            actor_id = resolve_actor_id(self._session, ctx, self._actor_subject)
            before_name, before_version = organization.name, organization.version
            organization.name = name
            organization.version = before_version + 1
            organization.updated_by = actor_id
            record_audit(self._session, ctx, actor_id=actor_id, action=ACTION_ORGANIZATION_UPDATE, target_type="organization", target_id=organization.id,
                         payload={"changes": {"name": change(before_name, name)}, "version": change(before_version, organization.version)})
            view = self._flush_and_commit(organization, name)
        except Exception:
            self._session.rollback()
            raise
        logger.info("組織を更新しました: tenant_id=%s organization_id=%s", ctx.tenant_id, view.id)
        return view

    def delete_organization(self, organization_id: uuid.UUID, *, expected_version: int) -> None:
        """組織を論理削除してコミットする（PF-ORG-03）。所属の行は残す。

        Raises:
            OrganizationNotFoundError: 存在しない（他テナント・論理削除済みを含む）。
            OrganizationVersionConflictError: バージョンが一致しない。
        """
        ctx = require_tenant_context()
        try:
            organization = self._lock_organization(organization_id, expected_version)
            actor_id = resolve_actor_id(self._session, ctx, self._actor_subject)
            before_version = organization.version
            organization.deleted_at = utc_now()
            organization.version = before_version + 1
            organization.updated_by = actor_id
            record_audit(self._session, ctx, actor_id=actor_id, action=ACTION_ORGANIZATION_DELETE, target_type="organization", target_id=organization.id,
                         payload={"name": organization.name, "version": change(before_version, organization.version)})
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("組織を削除しました（論理削除）: tenant_id=%s organization_id=%s", ctx.tenant_id, organization_id)

    def set_members(self, organization_id: uuid.UUID, *, expected_version: int, user_ids: Sequence[uuid.UUID]) -> OrganizationView:
        """組織のメンバーを ``user_ids`` に置き換えてコミットする（PF-ORG-02、03 §1 の全置換）。

        変更が無ければ何もしない（``version`` も変えない）。変更があれば組織の ``version`` を +1 し、
        監査ログに追加・削除したユーザー ID を残す。

        Args:
            organization_id: 組織 ID。
            expected_version: ``If-Match`` のバージョン。
            user_ids: メンバーにするユーザー ID（重複は除く。最大 :data:`MAX_ORGANIZATION_MEMBERS`）。

        Returns:
            OrganizationView: 更新後の組織。

        Raises:
            OrganizationNotFoundError: 存在しない（他テナント・論理削除済みを含む）。
            OrganizationVersionConflictError: バージョンが一致しない。
            OrganizationValidationError: 件数が上限を超える、ID の形式が不正。
            InvalidOrganizationMembersError: テナント内に存在しないユーザー（他テナントのユーザーを含む）。
        """
        ctx = require_tenant_context()
        members = _validate_member_ids(user_ids)
        try:
            organization = self._lock_organization(organization_id, expected_version)
            existing = org_repo.list_member_ids(self._session, organization.id)
            found = user_repo.find_existing_user_ids(self._session, members)
            unknown = [user_id for user_id in members if user_id not in found]
            if unknown:
                raise InvalidOrganizationMembersError(unknown)

            current, desired = set(existing), set(members)
            added = [user_id for user_id in members if user_id not in current]
            removed = [user_id for user_id in existing if user_id not in desired]
            if not added and not removed:
                view = OrganizationView.from_model(organization)
                self._session.rollback()
                return view

            actor_id = resolve_actor_id(self._session, ctx, self._actor_subject)
            org_repo.remove_members(self._session, organization.id, removed)
            org_repo.add_members(self._session, ctx.tenant_id, organization.id, added)
            before_version = organization.version
            organization.version = before_version + 1
            organization.updated_by = actor_id
            record_audit(self._session, ctx, actor_id=actor_id, action=ACTION_ORGANIZATION_SET_MEMBERS, target_type="organization", target_id=organization.id,
                         payload={"added": [str(u) for u in added], "removed": [str(u) for u in removed], "version": change(before_version, organization.version)})
            try:
                self._session.flush()
            except IntegrityError as exc:
                # 事前チェックの後に別トランザクションでユーザーが消えることは無い（ユーザーは削除しない）が、多重防御として扱う
                raise InvalidOrganizationMembersError(added) from exc
            view = OrganizationView.from_model(organization)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        logger.info("組織のメンバーを置き換えました: tenant_id=%s organization_id=%s added=%d removed=%d", ctx.tenant_id, view.id, len(added), len(removed))
        return view

    # ------------------------------------------------------------------ 補助
    def _require_organization(self, organization_id: uuid.UUID, *, for_update: bool = False) -> TOrganization:
        """有効な組織を取得する。無ければ :class:`OrganizationNotFoundError`。"""
        organization = org_repo.get_organization(self._session, organization_id, for_update=for_update)
        if organization is None:
            raise OrganizationNotFoundError(organization_id)
        return organization

    def _lock_organization(self, organization_id: uuid.UUID, expected_version: int) -> TOrganization:
        """組織を行ロックして取得し、バージョンを確認する。"""
        organization = self._require_organization(organization_id, for_update=True)
        if organization.version != expected_version:
            raise OrganizationVersionConflictError(organization.id, expected_version, organization.version)
        return organization

    def _flush_and_commit(self, organization: TOrganization, name: str) -> OrganizationView:
        """flush（名前の一意制約違反は 409 に変換）してビューを作り、コミットする。"""
        try:
            self._session.flush()
        except IntegrityError as exc:
            # 事前チェックと同時に、別のリクエストが同じ名前で作成・変更した
            raise OrganizationNameConflictError(name) from exc
        view = OrganizationView.from_model(organization)
        self._session.commit()
        return view


# --------------------------------------------------------------------------- 入力検証


def _validate_name(name: str) -> str:
    """組織名を検証する（前後の空白を除く。制御文字は不可）。"""
    if not isinstance(name, str) or not name.strip():
        raise OrganizationValidationError("name", "required")
    value = name.strip()
    if len(value) > ORGANIZATION_NAME_MAX_LENGTH:
        raise OrganizationValidationError("name", "too_long")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise OrganizationValidationError("name", "format")
    return value


def _validate_member_ids(user_ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
    """メンバーの ID を検証し、重複を除いて返す（指定順）。"""
    if isinstance(user_ids, str) or not isinstance(user_ids, Sequence):
        raise OrganizationValidationError("user_ids", "type")
    if not all(isinstance(user_id, uuid.UUID) for user_id in user_ids):
        raise OrganizationValidationError("user_ids", "format")
    unique = list(dict.fromkeys(user_ids))
    if len(unique) > MAX_ORGANIZATION_MEMBERS:
        raise OrganizationValidationError("user_ids", "too_many")
    return unique
