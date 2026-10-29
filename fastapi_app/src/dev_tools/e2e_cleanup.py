#!/usr/bin/env python
# coding:utf-8
"""Playwright の E2E（``react_app/playwright-test/screens/``）が作る使い捨てデータの後片付け（開発専用）。

**開発専用。** ``APP_ENV=development`` かつ開発用ログインが有効（``AUTH_DEV_LOGIN_ENABLED``。dev-login と同じ条件）な場合だけ動き、
それ以外では :class:`E2ECleanupNotAllowedError` を送出して DB・Keycloak に接続しない。

使い方::

    uv run python -m dev_tools.e2e_cleanup --dry-run   # 件数だけ表示する
    uv run python -m dev_tools.e2e_cleanup             # 削除する

    from dev_tools.e2e_cleanup import cleanup_e2e_data
    result = cleanup_e2e_data(dry_run=True)            # E2ECleanupResult（件数の内訳）

対象（E2E の命名。接尾辞は ``constants.ts`` の ``uniqueSuffix()`` = 小文字英数字 8 桁）:

============================== ============================== ==================================================
データ                         命名                           作るテスト
============================== ============================== ==================================================
CP のテナント                  ``e2e-<suffix>``               ``cp_tenants``（削除要求まで行い PENDING_DELETION で残る）
AP のユーザー                  ``e2e-<suffix>@example.com``   ``app_users``（無効化して AP と Keycloak に残る）
AP の ToDo                     ``E2E ToDo <suffix>``          ``app_todos``（論理削除で残る）
AP の組織                      ``E2E Org <suffix>``           ``app_organizations`` / ``app_todos``（論理削除で残る）
============================== ============================== ==================================================

対象の判定は本モジュールの定数（:data:`E2E_TENANT_CODE_PATTERN` 等）で固定し、引数では受け取らない（任意のデータを消せる API にしないため）。
シードのテナント・ユーザー（:data:`modules.auth.dev_profiles.DEV_TENANTS` / ``DEV_USERS``）とデフォルト組織は、パターンに一致しなくても
明示的に除外する（:func:`is_e2e_tenant_code` / :func:`is_e2e_user` / :func:`is_e2e_organization_name`）。

手順:
    1. CP: 対象テナント（``DELETED`` 以外）を物理削除する。テナントごとに管理クライアントを作り直す
       （:class:`~control_plane_app.services.tenant_provisioning.TenantProvisioningService` を使う。AP のデータとレルムも消える）。

       - ``ACTIVE`` / ``SUSPENDED`` / ``FAILED``: 削除要求 → 猶予 0 で ``deprovision``
       - ``PENDING_DELETION`` / ``DEPROVISIONING``: 猶予 0 で ``deprovision``（失敗した物理削除の再試行を含む）
       - ``PROVISIONING``: 処理中の可能性があるため、最終更新から :data:`STALE_PROVISIONING_THRESHOLD`（10 分）経過し、
         テナントのロックが取れるものだけ ``FAILED`` にしてから削除する。それ以外はスキップ
    2. AP: シードのテナント（:data:`PROTECTED_TENANT_CODES`。alpha / beta）のうち ``ACTIVE`` なものごとに、``app_cp_agent``（SELECT / DELETE のみ、RLS 適用）で
       GUC を切り替えて 1 トランザクションで処理する。

       - 対象の ToDo・組織は論理削除済みを含めて物理削除する。子の行（アクティビティ・担当者・公開先組織・組織メンバー）も消す
       - 対象のユーザーは Keycloak（``tenant-user-admin``）と AP の両方から削除する。組織メンバー・担当者の行も消す。
         削除しない行（シードの ToDo の作成者等）から参照されているユーザーは削除せずスキップする（外部キーを壊さないため）
       - Keycloak だけに残ったユーザー（AP の行が無い）も、メールアドレスがパターンに一致すれば削除する
       - AP 監査ログは **対象（target）が削除したユーザー・組織・ToDo の行だけ** 消す。操作者（actor）が削除したユーザーの行は残す
         （監査ログは actor に外部キーを張らない設計で、E2E 以外のデータへの操作の記録を消さないため。E2E のユーザーはログインしないため実際には生じない）

    CP の台帳（``DELETED`` の行）・払い出し履歴・CP 監査ログは残す（01 CP-OPS-09。通常の物理削除と同じ）。

冪等: 何度実行しても同じ状態に収束する。途中で失敗したテナントは :attr:`E2ECleanupResult.failures` に記録し、他のテナントの処理は続ける。
ログ: テナントコード・ID・件数・例外の型だけを出す。パスワード・トークン・Keycloak のエラー詳細は出さない。
"""
import argparse
import datetime as dt
import json
import logging
import re
import sys
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import Connection, Engine, Table, delete, func, or_, select, union
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, SQLModel, col

from control_plane_app.models.sql_models import ProvisioningType, TenantStatus, TTenant
from control_plane_app.repositories import tenant_repository as repo
from control_plane_app.repositories.locks import OperationLock, PgAdvisoryLock, tenant_lock_key
from control_plane_app.services.errors import TenantOperationInProgressError, TenantServiceError
from control_plane_app.services.tenant_lifecycle import STALE_PROVISIONING_THRESHOLD
from control_plane_app.services.tenant_maintenance import REAPED_ERROR
from control_plane_app.services.tenant_provisioning import AuditAction, TenantProvisioningService, bump_version, engine_of, status_change_payload, utcnow
from main_app.models import TApAuditLog, TOrganization, TOrganizationMember, TTodo, TTodoActivity, TTodoAssignee, TTodoOrganization, TUser
from main_app.services.user_sync import DEFAULT_ORGANIZATION_NAME
from modules.auth.dev_profiles import DEV_TENANTS, DEV_USERS
from modules.auth.environment import KeyCloakEnvironmentVariables
from modules.keycloak_admin import tenant_users as kc_users
from modules.keycloak_admin.admin_client import KeycloakAdminClient
from modules.keycloak_admin.errors import KeycloakAdminError
from modules.keycloak_admin.templates import create_provisioner_admin_client, create_tenant_user_admin_client
from modules.tenancy.db import tenant_guc_scope

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 対象の定数（E2E の命名。react_app/playwright-test/constants.ts の uniqueSuffix と各テスト）
# ---------------------------------------------------------------------------
# uniqueSuffix(): Math.random().toString(36).slice(2, 10).padEnd(8, '0') = 小文字英数字 8 桁
E2E_SUFFIX = r"[a-z0-9]{8}"

# CP のテナントコード（cp_tenants.test.ts: `e2e-${uniqueSuffix()}`）
E2E_TENANT_CODE_PREFIX = "e2e-"
E2E_TENANT_CODE_PATTERN = re.compile(rf"e2e-{E2E_SUFFIX}")

# AP のユーザーのメールアドレス（app_users.test.ts: `e2e-${suffix}@example.com`。ユーザー名も同じ値）
E2E_USER_EMAIL_PREFIX = "e2e-"
E2E_USER_EMAIL_PATTERN = re.compile(rf"e2e-{E2E_SUFFIX}@example\.com")

# AP の ToDo のタイトル（app_todos.test.ts: `E2E ToDo ${suffix}`）
E2E_TODO_TITLE_PREFIX = "E2E ToDo "
E2E_TODO_TITLE_PATTERN = re.compile(rf"E2E ToDo {E2E_SUFFIX}")

# AP の組織名（app_organizations.test.ts / app_todos.test.ts: `E2E Org ${suffix}`）
E2E_ORGANIZATION_NAME_PREFIX = "E2E Org "
E2E_ORGANIZATION_NAME_PATTERN = re.compile(rf"E2E Org {E2E_SUFFIX}")

# 絶対に触れないもの（パターンに一致しなくても明示的に除外する）
PROTECTED_TENANT_CODES: frozenset[str] = frozenset(tenant.tenant_code for tenant in DEV_TENANTS)
PROTECTED_USER_EMAILS: frozenset[str] = frozenset(user.email.lower() for user in DEV_USERS)
PROTECTED_USERNAMES: frozenset[str] = frozenset(user.username.lower() for user in DEV_USERS)
PROTECTED_ORGANIZATION_NAMES: frozenset[str] = frozenset({DEFAULT_ORGANIZATION_NAME})

# CP の台帳・監査ログに記録する操作者
CLEANUP_ACTOR = "dev:e2e_cleanup"

# 後片付け全体の排他ロックのキー（API とティアダウンの同時実行を防ぐ）
CLEANUP_LOCK_KEY = "dev:e2e_cleanup"

# 物理削除の猶予期間（後片付けでは待たない）
NO_GRACE_PERIOD = dt.timedelta(0)

# Keycloak のユーザー検索の 1 ページの件数
_KEYCLOAK_PAGE_SIZE = 100

# AP 監査ログの target_type（main_app のサービスが記録する値）
_AUDIT_TARGET_USER = "user"
_AUDIT_TARGET_ORGANIZATION = "organization"
_AUDIT_TARGET_TODO = "todo"


# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------
class E2ECleanupError(RuntimeError):
    """E2E データの後片付けの例外の基底。"""


class E2ECleanupNotAllowedError(E2ECleanupError):
    """開発環境でない（``APP_ENV=development`` かつ開発用ログインが有効でない）ため実行できない。"""


class E2ECleanupInProgressError(E2ECleanupError):
    """別の後片付けが実行中（排他ロックを取得できなかった）。"""


# ---------------------------------------------------------------------------
# 判定（DB・Keycloak に依存しない）
# ---------------------------------------------------------------------------
def is_e2e_cleanup_allowed() -> bool:
    """後片付けを実行できる環境かを返す（dev-login と同じ条件: ``APP_ENV=development`` かつ ``AUTH_DEV_LOGIN_ENABLED`` が真）。"""
    return KeyCloakEnvironmentVariables().is_dev_login_enabled()


def require_e2e_cleanup_allowed() -> None:
    """後片付けを実行できる環境かを確認する。

    Raises:
        E2ECleanupNotAllowedError: 開発環境でない、または開発用ログインが無効。
    """
    if not is_e2e_cleanup_allowed():
        raise E2ECleanupNotAllowedError("E2E データの後片付けは APP_ENV=development かつ AUTH_DEV_LOGIN_ENABLED=true の場合だけ実行できます。")


def is_e2e_tenant_code(tenant_code: str | None) -> bool:
    """E2E が作るテナントのコードかを返す（シードのテナントは常に ``False``）。"""
    if not tenant_code or tenant_code in PROTECTED_TENANT_CODES:
        return False
    return E2E_TENANT_CODE_PATTERN.fullmatch(tenant_code) is not None


def is_e2e_user(email: str | None, username: str | None = None) -> bool:
    """E2E が作るユーザーかを返す（シードのユーザーは常に ``False``）。

    Args:
        email: メールアドレス（大文字小文字は区別しない）。
        username: Keycloak のユーザー名（分かる場合。シードのユーザー名なら ``False``）。
    """
    if not email:
        return False
    normalized = email.strip().lower()
    if normalized in PROTECTED_USER_EMAILS or (username is not None and username.strip().lower() in PROTECTED_USERNAMES):
        return False
    return E2E_USER_EMAIL_PATTERN.fullmatch(normalized) is not None


def is_e2e_todo_title(title: str | None) -> bool:
    """E2E が作る ToDo のタイトルかを返す。"""
    return bool(title) and E2E_TODO_TITLE_PATTERN.fullmatch(title) is not None


def is_e2e_organization_name(name: str | None) -> bool:
    """E2E が作る組織の名前かを返す（デフォルト組織は常に ``False``）。"""
    if not name or name in PROTECTED_ORGANIZATION_NAMES:
        return False
    return E2E_ORGANIZATION_NAME_PATTERN.fullmatch(name) is not None


class TenantCleanupAction(StrEnum):
    """CP の対象テナントに対する処理。"""

    # 削除要求 → 物理削除
    REQUEST_AND_DEPROVISION = "request_and_deprovision"
    # 物理削除（削除要求済み・前回の物理削除が失敗）
    DEPROVISION = "deprovision"
    # 中断した払い出しを FAILED にしてから削除要求 → 物理削除
    REAP_AND_DEPROVISION = "reap_and_deprovision"
    # 処理しない（払い出しが実行中の可能性がある・削除済み）
    SKIP = "skip"


def plan_tenant_action(status: str, updated_at: dt.datetime, now: dt.datetime, *, stale_threshold: dt.timedelta = STALE_PROVISIONING_THRESHOLD) -> TenantCleanupAction:
    """テナントの状態から処理を決める。

    Args:
        status: テナントの状態。
        updated_at: 台帳の最終更新日時（UTC）。
        now: 現在時刻（UTC）。
        stale_threshold: ``PROVISIONING`` を中断とみなすまでの時間。

    Returns:
        TenantCleanupAction: 処理。
    """
    match status:
        case TenantStatus.ACTIVE | TenantStatus.SUSPENDED | TenantStatus.FAILED:
            return TenantCleanupAction.REQUEST_AND_DEPROVISION
        case TenantStatus.PENDING_DELETION | TenantStatus.DEPROVISIONING:
            return TenantCleanupAction.DEPROVISION
        case TenantStatus.PROVISIONING if updated_at <= now - stale_threshold:
            return TenantCleanupAction.REAP_AND_DEPROVISION
        case _:
            return TenantCleanupAction.SKIP


# ---------------------------------------------------------------------------
# 結果
# ---------------------------------------------------------------------------
@dataclass(slots=True, kw_only=True)
class TenantCleanupCounts:
    """CP のテナントの件数（``dry_run`` では処理する予定の件数）。

    Attributes:
        deprovisioned: 物理削除した（``DELETED`` にした）テナント。
        reaped: 中断した払い出しを ``FAILED`` にしたテナント（``deprovisioned`` にも含まれる）。
        skipped: 払い出しが実行中の可能性があるため処理しなかったテナント。
        failed: 失敗したテナント（内容は :attr:`E2ECleanupResult.failures`）。
    """

    deprovisioned: int = 0
    reaped: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(slots=True, kw_only=True)
class AppTenantCleanupCounts:
    """AP の 1 テナントで削除した行・Keycloak のユーザーの件数（``dry_run`` では削除する予定の件数）。

    Attributes:
        tenant_code: テナントコード。
        users: AP のユーザー（``t_user``）。
        keycloak_users: Keycloak のユーザー（AP の行が無いものを含む）。
        skipped_users: 削除しない行から参照されているため削除しなかったユーザー。
        organizations: 組織（論理削除済みを含む）。
        organization_members: 組織メンバー（対象の組織・ユーザーのもの）。
        todos: ToDo（論理削除済みを含む）。
        todo_activities: ToDo アクティビティ。
        todo_assignees: ToDo の担当者（対象の ToDo・ユーザーのもの）。
        todo_organizations: ToDo の公開先組織（対象の ToDo・組織のもの）。
        audit_logs: AP 監査ログ（対象が削除したユーザー・組織・ToDo のもの）。
    """

    tenant_code: str
    users: int = 0
    keycloak_users: int = 0
    skipped_users: int = 0
    organizations: int = 0
    organization_members: int = 0
    todos: int = 0
    todo_activities: int = 0
    todo_assignees: int = 0
    todo_organizations: int = 0
    audit_logs: int = 0


@dataclass(slots=True, kw_only=True)
class CleanupFailure:
    """失敗した処理（秘匿値・Keycloak のエラー詳細を含めない）。

    Attributes:
        scope: ``cp``（テナントの物理削除）または ``app``（AP のデータ・ユーザー）。
        tenant_code: テナントコード。
        error: 例外の種別（``TenantServiceError`` の ``code``、または例外の型名と HTTP ステータス）。
    """

    scope: str
    tenant_code: str
    error: str


@dataclass(slots=True, kw_only=True)
class E2ECleanupResult:
    """:func:`cleanup_e2e_data` の結果（件数の内訳）。

    Attributes:
        dry_run: 件数の確認だけを行ったか。
        tenants: CP のテナントの件数。
        app_tenants: AP のテナントごとの件数。
        failures: 失敗した処理。
    """

    dry_run: bool
    tenants: TenantCleanupCounts = field(default_factory=TenantCleanupCounts)
    app_tenants: list[AppTenantCleanupCounts] = field(default_factory=list)
    failures: list[CleanupFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """失敗が無ければ ``True``。"""
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        """JSON にできる辞書を返す。"""
        return {**asdict(self), "ok": self.ok}


# ---------------------------------------------------------------------------
# AP の対象
# ---------------------------------------------------------------------------
@dataclass(slots=True, kw_only=True)
class _AppTargets:
    """AP の 1 テナントで削除する対象。"""

    user_ids: set[uuid.UUID] = field(default_factory=set)
    user_subjects: dict[uuid.UUID, str] = field(default_factory=dict)
    skipped_user_ids: set[uuid.UUID] = field(default_factory=set)
    organization_ids: set[uuid.UUID] = field(default_factory=set)
    todo_ids: set[uuid.UUID] = field(default_factory=set)

    @property
    def subjects(self) -> set[str]:
        """削除するユーザーの IdP の利用者 ID。"""
        return {self.user_subjects[user_id] for user_id in self.user_ids}


def _table(model: type[SQLModel]) -> Table:
    """モデルのテーブルを返す（ORM の全列を読まないよう、Core の式で扱う。t_user の列追加の影響を受けない）。"""
    return cast(Table, model.__table__)


def _find_app_targets(conn: Connection, tenant_id: uuid.UUID) -> _AppTargets:
    """命名のパターンで対象のユーザー・組織・ToDo を探し、削除できないユーザーを除く。"""
    user, organization, todo = _table(TUser), _table(TOrganization), _table(TTodo)
    targets = _AppTargets()

    user_rows = conn.execute(select(user.c.id, user.c.idp_subject, user.c.email).where(user.c.tenant_id == tenant_id, func.lower(user.c.email).startswith(E2E_USER_EMAIL_PREFIX))).all()
    for row in user_rows:
        if is_e2e_user(row.email):
            targets.user_ids.add(row.id)
            targets.user_subjects[row.id] = row.idp_subject

    organization_rows = conn.execute(select(organization.c.id, organization.c.name).where(organization.c.tenant_id == tenant_id, organization.c.name.startswith(E2E_ORGANIZATION_NAME_PREFIX))).all()
    targets.organization_ids = {row.id for row in organization_rows if is_e2e_organization_name(row.name)}

    todo_rows = conn.execute(select(todo.c.id, todo.c.title).where(todo.c.tenant_id == tenant_id, todo.c.title.startswith(E2E_TODO_TITLE_PREFIX))).all()
    targets.todo_ids = {row.id for row in todo_rows if is_e2e_todo_title(row.title)}

    # 削除しない行から参照されているユーザーを除く（除いたことで新たに参照が残るユーザーが出るため、変わらなくなるまで繰り返す）
    while blocked := _blocked_user_ids(conn, tenant_id, targets):
        targets.user_ids -= blocked
        targets.skipped_user_ids |= blocked
    return targets


def _blocked_user_ids(conn: Connection, tenant_id: uuid.UUID, targets: _AppTargets) -> set[uuid.UUID]:
    """対象のユーザーのうち、削除しない行から外部キーで参照されているものを返す。

    組織メンバー・担当者（``user_id``）の行は削除するため含めない。対象の ToDo・組織・ユーザーの行からの参照も含めない。
    """
    users, organizations, todos = list(targets.user_ids), list(targets.organization_ids), list(targets.todo_ids)
    if not users:
        return set()
    user, organization, todo = _table(TUser), _table(TOrganization), _table(TTodo)
    assignee, activity = _table(TTodoAssignee), _table(TTodoActivity)
    queries = [
        select(user.c.created_by.label("user_id")).where(user.c.tenant_id == tenant_id, user.c.created_by.in_(users), user.c.id.not_in(users)),
        select(user.c.updated_by).where(user.c.tenant_id == tenant_id, user.c.updated_by.in_(users), user.c.id.not_in(users)),
        select(organization.c.created_by).where(organization.c.tenant_id == tenant_id, organization.c.created_by.in_(users), organization.c.id.not_in(organizations)),
        select(organization.c.updated_by).where(organization.c.tenant_id == tenant_id, organization.c.updated_by.in_(users), organization.c.id.not_in(organizations)),
        select(todo.c.created_by).where(todo.c.tenant_id == tenant_id, todo.c.created_by.in_(users), todo.c.id.not_in(todos)),
        select(todo.c.updated_by).where(todo.c.tenant_id == tenant_id, todo.c.updated_by.in_(users), todo.c.id.not_in(todos)),
        select(assignee.c.assigned_by).where(assignee.c.tenant_id == tenant_id, assignee.c.assigned_by.in_(users), assignee.c.todo_id.not_in(todos), assignee.c.user_id.not_in(users)),
        select(activity.c.actor_id).where(activity.c.tenant_id == tenant_id, activity.c.actor_id.in_(users), activity.c.todo_id.not_in(todos)),
    ]
    return set(conn.execute(union(*queries)).scalars())


@dataclass(frozen=True, slots=True)
class _PurgeSpec:
    """削除する行（結果のキー・テーブル・条件）。"""

    key: str
    table: Table
    condition: ColumnElement[bool]


def _purge_specs(tenant_id: uuid.UUID, targets: _AppTargets) -> list[_PurgeSpec]:
    """削除する行を、外部キーで参照する子テーブルから順に返す。"""
    users, organizations, todos = list(targets.user_ids), list(targets.organization_ids), list(targets.todo_ids)
    activity, assignee, todo_organization = _table(TTodoActivity), _table(TTodoAssignee), _table(TTodoOrganization)
    todo, member, organization = _table(TTodo), _table(TOrganizationMember), _table(TOrganization)
    audit_log, user = _table(TApAuditLog), _table(TUser)
    audit_targets = [
        (_AUDIT_TARGET_TODO, todos),
        (_AUDIT_TARGET_ORGANIZATION, organizations),
        (_AUDIT_TARGET_USER, users),
    ]
    specs = [
        _PurgeSpec("todo_activities", activity, activity.c.todo_id.in_(todos)),
        _PurgeSpec("todo_assignees", assignee, or_(assignee.c.todo_id.in_(todos), assignee.c.user_id.in_(users))),
        _PurgeSpec("todo_organizations", todo_organization, or_(todo_organization.c.todo_id.in_(todos), todo_organization.c.organization_id.in_(organizations))),
        _PurgeSpec("todos", todo, todo.c.id.in_(todos)),
        _PurgeSpec("organization_members", member, or_(member.c.organization_id.in_(organizations), member.c.user_id.in_(users))),
        _PurgeSpec("organizations", organization, organization.c.id.in_(organizations)),
        # 監査ログは対象（target）が削除する行のものだけ。操作者（actor）では消さない（モジュールの docstring）
        _PurgeSpec("audit_logs", audit_log, or_(*((audit_log.c.target_type == target_type) & audit_log.c.target_id.in_([str(target_id) for target_id in ids]) for target_type, ids in audit_targets))),
        _PurgeSpec("users", user, user.c.id.in_(users)),
    ]
    # 多重防御として tenant_id の条件も付ける（RLS により GUC のテナントの行しか見えない）
    return [_PurgeSpec(spec.key, spec.table, (spec.table.c.tenant_id == tenant_id) & spec.condition) for spec in specs]


def _apply_purge_specs(conn: Connection, specs: Sequence[_PurgeSpec], *, dry_run: bool) -> dict[str, int]:
    """行を削除して件数を返す（``dry_run`` では数えるだけ）。"""
    counts: dict[str, int] = {}
    for spec in specs:
        if dry_run:
            counts[spec.key] = int(conn.execute(select(func.count()).select_from(spec.table).where(spec.condition)).scalar_one())
        else:
            counts[spec.key] = int(conn.execute(delete(spec.table).where(spec.condition)).rowcount or 0)
    return counts


def _search_keycloak_e2e_users(admin: KeycloakAdminClient, realm: str) -> dict[str, dict[str, Any]]:
    """レルムから E2E のユーザー（メールアドレスがパターンに一致し、シードのユーザーでないもの）を探す。

    Returns:
        dict[str, dict]: ユーザーの内部 ID -> UserRepresentation（brief）。
    """
    found: dict[str, dict[str, Any]] = {}
    first = 0
    while True:
        # search は username / email / 姓 / 名の前方一致
        page = admin.get_json(admin.realm_url(realm, "users"), operation=f"search users in realm {realm}",
                              params={"search": E2E_USER_EMAIL_PREFIX, "first": str(first), "max": str(_KEYCLOAK_PAGE_SIZE), "briefRepresentation": "true"}) or []
        for user in page:
            if user.get("id") and is_e2e_user(user.get("email"), user.get("username") or ""):
                found[user["id"]] = user
        if len(page) < _KEYCLOAK_PAGE_SIZE:
            return found
        first += _KEYCLOAK_PAGE_SIZE


def _is_deletable_keycloak_user(user: dict[str, Any] | None) -> bool:
    """Keycloak のユーザーを削除してよいか（存在し、シードのユーザーでない）。"""
    if user is None:
        return False
    username = (user.get("username") or "").lower()
    email = (user.get("email") or "").lower()
    return username not in PROTECTED_USERNAMES and email not in PROTECTED_USER_EMAILS


def _summarize_error(exc: BaseException) -> str:
    """失敗の記録・ログ用の要約（秘匿値・Keycloak のエラー詳細を含めない）。"""
    if isinstance(exc, TenantServiceError):
        return exc.code
    if isinstance(exc, KeycloakAdminError) and exc.status_code is not None:
        return f"{type(exc).__name__}; http_status={exc.status_code}"
    return type(exc).__name__


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _TenantRow:
    """CP の台帳の行（必要な列だけ）。"""

    id: uuid.UUID
    tenant_code: str
    status: str
    realm_name: str
    updated_at: dt.datetime


class E2EDataCleaner:
    """E2E データの後片付け（依存を差し替えられるようにしたもの。通常は :func:`cleanup_e2e_data` を使う）。

    Args:
        cp_session_factory: CP DB（``cp_runtime``）のセッションを作る関数。省略時は :func:`modules.tenancy.providers.get_cp_sessionmaker`。
        app_engine_factory: AP DB（``app_cp_agent``）のエンジンを返す関数。省略時は :func:`modules.tenancy.providers.get_app_cp_agent_engine`。
        provisioner_admin_factory: 払い出し用の Keycloak の管理クライアントを作る関数（CP のテナントごとに呼ぶ）。
        tenant_user_admin_factory: テナントレルム名から ``tenant-user-admin`` の管理クライアントを作る関数（AP のテナントごとに呼ぶ）。
        lock: 排他ロック（後片付け全体とテナント単位。省略時は CP DB の advisory lock）。
        clock: 現在時刻（UTC）を返す関数。
        stale_provisioning_threshold: ``PROVISIONING`` を中断とみなすまでの時間。
    """

    def __init__(
        self,
        *,
        cp_session_factory: Callable[[], Session] | None = None,
        app_engine_factory: Callable[[], Engine] | None = None,
        provisioner_admin_factory: Callable[[], KeycloakAdminClient] = create_provisioner_admin_client,
        tenant_user_admin_factory: Callable[[str], KeycloakAdminClient] = create_tenant_user_admin_client,
        lock: OperationLock | None = None,
        clock: Callable[[], dt.datetime] = utcnow,
        stale_provisioning_threshold: dt.timedelta = STALE_PROVISIONING_THRESHOLD,
    ) -> None:
        """依存を保持する（ここでは DB・Keycloak に接続しない）。"""
        self._cp_session_factory = cp_session_factory
        self._app_engine_factory = app_engine_factory
        self._provisioner_admin_factory = provisioner_admin_factory
        self._tenant_user_admin_factory = tenant_user_admin_factory
        self._lock = lock
        self._clock = clock
        self._stale_threshold = stale_provisioning_threshold

    def run(self, *, dry_run: bool = False) -> E2ECleanupResult:
        """後片付けを実行する（モジュールの docstring の手順）。

        Args:
            dry_run: ``True`` なら何も変更せず、処理する予定の件数だけ返す。

        Returns:
            E2ECleanupResult: 件数の内訳と失敗。

        Raises:
            E2ECleanupNotAllowedError: 開発環境でない（DB・Keycloak に接続しない）。
            E2ECleanupInProgressError: 別の後片付けが実行中。
        """
        require_e2e_cleanup_allowed()
        result = E2ECleanupResult(dry_run=dry_run)
        with self._open_cp_session() as session:
            lock = self._lock or PgAdvisoryLock(engine_of(session))
            with lock.try_acquire(CLEANUP_LOCK_KEY) as acquired:
                if not acquired:
                    raise E2ECleanupInProgressError("別の E2E データの後片付けが実行中です。")
                logger.info("E2E データの後片付けを開始します: dry_run=%s", dry_run)
                tenants = self._list_tenants(session)
                self._cleanup_cp_tenants(session, lock, [tenant for tenant in tenants if is_e2e_tenant_code(tenant.tenant_code)], result)
                # E2E がユーザー・組織・ToDo を作るのはシードのテナントだけ。それ以外（pytest の使い捨てテナント等、レルムが無いことがある）は走査しない
                app_tenants = [tenant for tenant in tenants if tenant.status == TenantStatus.ACTIVE and tenant.tenant_code in PROTECTED_TENANT_CODES]
                for tenant in app_tenants:
                    self._cleanup_app_tenant(tenant, result)
        logger.info("E2E データの後片付けを終了しました: dry_run=%s tenants=%s failures=%d", dry_run, result.tenants, len(result.failures))
        return result

    # ------------------------------------------------------------------ 接続
    def _open_cp_session(self) -> Session:
        """CP DB のセッションを作る。"""
        if self._cp_session_factory is not None:
            return self._cp_session_factory()
        from modules.tenancy.providers import get_cp_sessionmaker

        return get_cp_sessionmaker()()

    def _app_engine(self) -> Engine:
        """AP DB（``app_cp_agent``）のエンジンを返す。"""
        if self._app_engine_factory is not None:
            return self._app_engine_factory()
        from modules.tenancy.providers import get_app_cp_agent_engine

        return get_app_cp_agent_engine()

    def _list_tenants(self, session: Session) -> list[_TenantRow]:
        """``DELETED`` 以外のテナントを返す（読み取りのトランザクションは閉じる）。"""
        statement = select(TTenant.id, TTenant.tenant_code, TTenant.status, TTenant.realm_name, TTenant.updated_at).where(TTenant.status != TenantStatus.DELETED.value).order_by(col(TTenant.created_at))
        rows = [_TenantRow(*row) for row in session.connection().execute(statement).all()]
        session.rollback()
        return rows

    # ------------------------------------------------------------------ CP
    def _cleanup_cp_tenants(self, session: Session, lock: OperationLock, tenants: Iterable[_TenantRow], result: E2ECleanupResult) -> None:
        """E2E のテナントを物理削除する（1 テナントの失敗で他を止めない）。"""
        counts = result.tenants
        for tenant in tenants:
            action = plan_tenant_action(tenant.status, tenant.updated_at, self._clock(), stale_threshold=self._stale_threshold)
            if action == TenantCleanupAction.SKIP:
                counts.skipped += 1
                logger.info("払い出しが実行中の可能性があるためスキップします: tenant_code=%s status=%s", tenant.tenant_code, tenant.status)
                continue
            if result.dry_run:
                counts.deprovisioned += 1
                if action == TenantCleanupAction.REAP_AND_DEPROVISION:
                    counts.reaped += 1
                continue
            try:
                if action == TenantCleanupAction.REAP_AND_DEPROVISION:
                    if not self._reap_stale_provisioning(session, lock, tenant):
                        counts.skipped += 1
                        continue
                    counts.reaped += 1
                with self._provisioner_admin_factory() as admin:
                    service = TenantProvisioningService(session, admin, lock=lock, clock=self._clock)
                    if action != TenantCleanupAction.DEPROVISION:
                        service.request_deletion(tenant.id, actor=CLEANUP_ACTOR)
                    service.deprovision(tenant.id, actor=CLEANUP_ACTOR, grace_period=NO_GRACE_PERIOD)
                counts.deprovisioned += 1
                logger.info("E2E のテナントを物理削除しました: tenant_code=%s", tenant.tenant_code)
            except TenantOperationInProgressError:
                counts.skipped += 1
                logger.info("テナントの処理が実行中のためスキップします: tenant_code=%s", tenant.tenant_code)
            except Exception as exc:
                session.rollback()
                counts.failed += 1
                result.failures.append(CleanupFailure(scope="cp", tenant_code=tenant.tenant_code, error=_summarize_error(exc)))
                logger.warning("E2E のテナントを削除できませんでした: tenant_code=%s error=%s", tenant.tenant_code, _summarize_error(exc))

    def _reap_stale_provisioning(self, session: Session, lock: OperationLock, tenant: _TenantRow) -> bool:
        """中断した（``PROVISIONING`` のまま閾値を過ぎた）1 テナントの払い出しを ``FAILED`` にする。

        :func:`control_plane_app.services.tenant_maintenance.reap_stale_provisioning` と同じ処理を対象のテナントに限って行う
        （同関数は全テナントが対象のため、E2E 以外のテナントに触れないよう使わない）。

        Returns:
            bool: ``FAILED`` にしたら ``True``。ロックが取れない・状態が変わっていた場合は ``False``。
        """
        now = self._clock()
        cutoff = now - self._stale_threshold
        with lock.try_acquire(tenant_lock_key(tenant.tenant_code)) as acquired:
            if not acquired:
                return False
            row = repo.get_tenant(session, tenant.id, for_update=True)
            if row is None or row.status != TenantStatus.PROVISIONING or row.updated_at > cutoff:
                session.rollback()
                return False
            before_version = row.version
            row.status = TenantStatus.FAILED.value
            bump_version(row, CLEANUP_ACTOR)
            closed = repo.close_running_histories(session, tenant.id, ProvisioningType.ONBOARD, REAPED_ERROR, now)
            repo.add_cp_audit_log(session, actor=CLEANUP_ACTOR, action=AuditAction.PROVISION_REAP, tenant_id=tenant.id,
                                  payload={**status_change_payload(TenantStatus.PROVISIONING.value, row.status, before_version, row.version), "closed_histories": closed})
            session.commit()
        logger.info("E2E のテナントの中断した払い出しを FAILED にしました: tenant_code=%s", tenant.tenant_code)
        return True

    # ------------------------------------------------------------------ AP
    def _cleanup_app_tenant(self, tenant: _TenantRow, result: E2ECleanupResult) -> None:
        """AP の 1 テナントの E2E のデータと Keycloak のユーザーを削除する（失敗したら記録して戻る）。"""
        try:
            counts = self._purge_app_tenant(tenant, dry_run=result.dry_run)
        except Exception as exc:
            result.failures.append(CleanupFailure(scope="app", tenant_code=tenant.tenant_code, error=_summarize_error(exc)))
            logger.warning("AP の E2E のデータを削除できませんでした: tenant_code=%s error=%s", tenant.tenant_code, _summarize_error(exc))
            return
        result.app_tenants.append(counts)
        logger.info("AP の E2E のデータを%s: %s", "数えました" if result.dry_run else "削除しました", counts)

    def _purge_app_tenant(self, tenant: _TenantRow, *, dry_run: bool) -> AppTenantCleanupCounts:
        """1 トランザクションで対象を探し、Keycloak のユーザーを削除してから AP の行を削除してコミットする。

        Keycloak の削除が失敗したら AP の行は変更しない（ロールバック）。AP のコミットだけが失敗した場合も、
        次回の実行で Keycloak 側は「既に無い」として AP の行を削除し、同じ状態に収束する。
        """
        # 例外で抜けた場合は Session を閉じる際にロールバックされる
        with Session(self._app_engine()) as session:
            with tenant_guc_scope(session, tenant.id):
                conn = session.connection()
                targets = _find_app_targets(conn, tenant.id)
                for user_id in targets.skipped_user_ids:
                    logger.warning("削除しない行から参照されているためユーザーを削除しません: tenant_code=%s user_id=%s", tenant.tenant_code, user_id)
                keycloak_users = self._purge_keycloak_users(conn, tenant, targets, dry_run=dry_run)
                rows = _apply_purge_specs(conn, _purge_specs(tenant.id, targets), dry_run=dry_run)
            if dry_run:
                session.rollback()
            else:
                session.commit()
        return AppTenantCleanupCounts(tenant_code=tenant.tenant_code, keycloak_users=keycloak_users, skipped_users=len(targets.skipped_user_ids), **rows)

    def _purge_keycloak_users(self, conn: Connection, tenant: _TenantRow, targets: _AppTargets, *, dry_run: bool) -> int:
        """対象のユーザーと、AP の行が無い E2E のユーザーを Keycloak から削除する（``dry_run`` では数えるだけ）。"""
        realm = tenant.realm_name
        with self._tenant_user_admin_factory(realm) as admin:
            searched = _search_keycloak_e2e_users(admin, realm)
            # AP の行が無い（作成の補償に失敗した等の）Keycloak のユーザー。スキップしたユーザーは AP の行があるため含まれない
            user = _table(TUser)
            linked = set(conn.execute(select(user.c.idp_subject).where(user.c.tenant_id == tenant.id, user.c.idp_subject.in_(list(searched)))).scalars()) if searched else set()
            candidates = targets.subjects | (set(searched) - linked)
            deleted = 0
            for subject in sorted(candidates):
                if not _is_deletable_keycloak_user(searched.get(subject) or kc_users.get_user(admin, realm, subject)):
                    continue
                if dry_run or kc_users.delete_user_if_exists(admin, realm, subject):
                    deleted += 1
        return deleted


def cleanup_e2e_data(*, dry_run: bool = False) -> E2ECleanupResult:
    """Playwright の E2E が作る使い捨てデータを後片付けする（開発専用。対象と手順はモジュールの docstring）。

    Args:
        dry_run: ``True`` なら何も変更せず、処理する予定の件数だけ返す。

    Returns:
        E2ECleanupResult: 件数の内訳と失敗（1 件でも失敗があれば ``ok`` が ``False``）。

    Raises:
        E2ECleanupNotAllowedError: ``APP_ENV=development`` かつ開発用ログインが有効でない（何もしない）。
        E2ECleanupInProgressError: 別の後片付けが実行中。
    """
    return E2EDataCleaner().run(dry_run=dry_run)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """CLI のエントリポイント（``python -m dev_tools.e2e_cleanup [--dry-run]``）。結果を JSON で標準出力に表示する。

    Returns:
        int: 終了コード（0: 成功、1: 失敗したテナントがある、2: 実行できない環境・実行中）。
    """
    parser = argparse.ArgumentParser(prog="python -m dev_tools.e2e_cleanup", description="Playwright の E2E が作る使い捨てデータを後片付けする（開発専用）。")
    parser.add_argument("--dry-run", action="store_true", help="何も変更せず、処理する予定の件数だけ表示する")
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ (INFO) を標準エラーに出力する")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    from modules.tenancy.providers import dispose_providers

    try:
        result = cleanup_e2e_data(dry_run=args.dry_run)
    except E2ECleanupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        dispose_providers()
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
