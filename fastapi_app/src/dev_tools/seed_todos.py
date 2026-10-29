#!/usr/bin/env python
# coding:utf-8
"""ToDo の開発用シード（docs/spec/ToDoApp.md §9.4）。何度実行しても同じ状態に収束する（冪等）。

**開発専用。** ``APP_ENV=development`` が明示的に設定されていない場合は何もせず終了する
（:func:`control_plane_app.seed.require_explicit_development` を使い回す）。テナントとユーザーのシードの後に実行する::

    make d-run SERVICE=fastapi_app CMD="uv run python -m control_plane_app.seed"
    make d-run SERVICE=fastapi_app CMD="uv run python -m dev_tools.seed_todos"

CP は AP に書き込まない（05 #31）ため、両プレーンを参照できる ``dev_tools`` に置く。手順（テナントごと）:

1. CP の台帳でテナントを確認する（:data:`modules.auth.dev_profiles.DEV_TENANTS` のうち ``ACTIVE`` なものだけ。それ以外はスキップ）
2. Keycloak のテナントレルムから :data:`~modules.auth.dev_profiles.DEV_TENANT_USERS` の ``sub``・姓・名・実効ロールを引き、
   ログイン時と同じ :func:`~main_app.services.user_sync.sync_user_on_login` で ``t_user`` とデフォルト組織を確保する
   （``last_login_at`` も更新される）
3. ``[Seed]`` で始まる組織を 2 つ確保する（:data:`SEED_ORGANIZATIONS`。1 つは ToDo を作った後に論理削除し、AP-VIS-08 の
   「公開先がすべて削除された ``organization``」を作る）。組織は :class:`~main_app.services.organization_service.OrganizationService` で作る
4. ToDo・チェックリスト・コメントを**サービス経由**で作る（:class:`~main_app.services.todo_service.TodoService` /
   :class:`~main_app.services.todo_checklist_service.TodoChecklistService` / :class:`~main_app.services.todo_comment_service.TodoCommentService`。
   アクティビティと監査ログも通常の操作と同じく残る）。操作者は各 ToDo の作成者・担当者・投稿者

網羅する組み合わせ（:data:`SEED_TODOS`。``alpha`` 20 件、``beta`` 6 件）: 閲覧範囲（``private`` / ``organization``（有効な組織）/
``organization``（公開先がすべて削除済み）/ ``tenant``）× 作成者（admin / member / member2）× 担当者（なし・1 人・2 人）、ステータス 3 種、
期限（期限切れ・今日・数日後・期限なし）、チェックリスト（なし・一部完了・全完了）、コメントの有無。

冪等: タイトル（``[Seed] `` で始まる）が同じ ToDo（論理削除済みを除く）があれば作らない。組織も名前（論理削除済みを含む）で判定する。
途中で失敗した ToDo は作成済みの部分が残る（次回はタイトルで既存とみなす。作り直す場合は画面か SQL で消してから再実行する）。

E2E の後片付け（:mod:`dev_tools.e2e_cleanup`。``E2E ToDo `` / ``E2E Org `` で始まるもの）の対象にならない。シードのユーザーは
後片付けでも明示的に除外されている。

終了コード:
    0: 成功 / 1: 失敗 / 2: APP_ENV が development でない
"""
import argparse
import datetime as dt
import logging
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from control_plane_app.models.sql_models import TenantStatus
from control_plane_app.repositories import tenant_repository as tenant_repo
from control_plane_app.seed import require_explicit_development
from main_app.models import TodoPriority, TodoStatus, TodoVisibility, TOrganization, TTodo
from main_app.services.common import normalize_tenant_roles, utc_now
from main_app.services.errors import AppServiceError
from main_app.services.organization_service import OrganizationService
from main_app.services.todo_checklist_service import TodoChecklistService
from main_app.services.todo_comment_service import TodoCommentService
from main_app.services.todo_service import TodoService
from main_app.services.user_sync import sync_user_on_login
from modules.auth.dev_profiles import DEV_TENANT_USERS, DEV_TENANTS, DevTenant, DevUser
from modules.keycloak_admin import tenant_users as kc_users
from modules.keycloak_admin.errors import KeycloakAdminError
from modules.keycloak_admin.templates import create_provisioner_admin_client
from modules.keycloak_admin.users import find_user
from modules.tenancy.context import TenantContext, tenant_scope

logger = logging.getLogger(__name__)

# シードのデータの目印（タイトル・組織名の接頭辞。E2E の後片付けの命名とは重ならない）
SEED_PREFIX = "[Seed] "

# ユーザーの呼び名（DEV_TENANT_USERS のユーザー名の ``<tenant>-`` より後ろ）
ADMIN, MEMBER, MEMBER2 = "admin", "member", "member2"


# ---------------------------------------------------------------------------
# シードの定義
# ---------------------------------------------------------------------------
@dataclass(frozen=True, kw_only=True)
class SeedOrganization:
    """シードの組織。

    Attributes:
        key: ToDo の定義から参照する名前。
        name: 組織名（``[Seed] `` で始める）。
        members: 所属するユーザーの呼び名。
        deleted: ToDo を作った後に論理削除するか（AP-VIS-08 の確認用）。
    """

    key: str
    name: str
    members: tuple[str, ...]
    deleted: bool = False


@dataclass(frozen=True, kw_only=True)
class SeedComment:
    """シードのコメント（投稿者はその ToDo を閲覧できること）。"""

    author: str
    body: str


@dataclass(frozen=True, kw_only=True)
class SeedTodo:
    """シードの ToDo。

    Attributes:
        title: タイトル（``[Seed] `` で始める。冪等の判定に使う）。
        creator: 作成者の呼び名。
        visibility: 閲覧範囲。
        organizations: 公開先の組織の ``key``（``organization`` のとき）。
        assignees: 担当者の呼び名。
        status: ステータス。
        priority: 優先度。
        due_in_days: 期限（実行日からの日数。負なら期限切れ、``None`` は期限なし）。
        description: 説明。
        checklist: チェックリスト項目（項目名, 完了か）。完了にするのは最初の担当者（いなければ作成者）。
        comments: コメント（古い順）。
    """

    title: str
    creator: str
    visibility: TodoVisibility = TodoVisibility.PRIVATE
    organizations: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    status: TodoStatus = TodoStatus.OPEN
    priority: TodoPriority = TodoPriority.MEDIUM
    due_in_days: int | None = None
    description: str | None = None
    checklist: tuple[tuple[str, bool], ...] = ()
    comments: tuple[SeedComment, ...] = ()


PLANNING, LEGACY = "planning", "legacy"

# 組織（各テナント共通の定義。PLANNING は member が所属、LEGACY は member2 が所属し、ToDo を作った後に論理削除する）
SEED_ORGANIZATIONS: tuple[SeedOrganization, ...] = (
    SeedOrganization(key=PLANNING, name=f"{SEED_PREFIX}企画部", members=(MEMBER,)),
    SeedOrganization(key=LEGACY, name=f"{SEED_PREFIX}旧プロジェクト", members=(MEMBER2,), deleted=True),
)

_P, _O, _T = TodoVisibility.PRIVATE, TodoVisibility.ORGANIZATION, TodoVisibility.TENANT
_OPEN, _WIP, _DONE = TodoStatus.OPEN, TodoStatus.IN_PROGRESS, TodoStatus.DONE
_LOW, _MID, _HIGH = TodoPriority.LOW, TodoPriority.MEDIUM, TodoPriority.HIGH


def _todo(title: str, creator: str, visibility: TodoVisibility, **kwargs: Any) -> SeedTodo:
    """``[Seed] `` を付けた ToDo の定義を作る。"""
    return SeedTodo(title=f"{SEED_PREFIX}{title}", creator=creator, visibility=visibility, **kwargs)


def _c(author: str, body: str) -> SeedComment:
    """コメントの定義を作る。"""
    return SeedComment(author=author, body=body)


ALPHA_TODOS: tuple[SeedTodo, ...] = (
    _todo("四半期の売上レポートを作成", ADMIN, _T, assignees=(MEMBER,), status=_WIP, priority=_HIGH, due_in_days=-2,
          description="前四半期との比較と、来期の見通しを 1 枚にまとめる。",
          checklist=(("売上データの抽出", True), ("グラフの作成", False), ("所見の記入", False)),
          comments=(_c(ADMIN, "数字は経理の締め後のものを使ってください。"), _c(MEMBER, "了解しました。締めは明日の予定です。"))),
    _todo("新人研修の資料を更新", ADMIN, _O, organizations=(PLANNING,), assignees=(MEMBER, MEMBER2), priority=_MID, due_in_days=3,
          comments=(_c(MEMBER, "前年の資料をベースに直します。"),)),
    _todo("社内ポータルのリンク切れを修正", ADMIN, _P, status=_DONE, priority=_LOW, due_in_days=-10,
          checklist=(("リンク切れの洗い出し", True), ("修正の反映", True))),
    _todo("来期の採用計画のメモ", ADMIN, _P, assignees=(MEMBER2,), due_in_days=0,
          checklist=(("職種ごとの人数を確認", True), ("予算の確認", False)),
          comments=(_c(MEMBER2, "職種ごとの人数をまとめておきます。"),)),
    _todo("旧プロジェクトの資料整理", ADMIN, _O, organizations=(LEGACY,), priority=_LOW),
    _todo("顧客アンケートの集計", MEMBER, _T, assignees=(MEMBER2,), status=_WIP, priority=_HIGH, due_in_days=1,
          checklist=(("回答の取り込み", True), ("自由記述の分類", True), ("集計表の作成", False), ("報告資料の作成", False)),
          comments=(_c(ADMIN, "今週中に速報だけでも共有してください。"), _c(MEMBER2, "自由記述の分類は終わりました。"), _c(MEMBER, "ありがとうございます。集計に入ります。"))),
    _todo("週次定例のアジェンダ作成", MEMBER, _O, organizations=(PLANNING,), due_in_days=5),
    _todo("出張の経費精算", MEMBER, _P, priority=_HIGH, due_in_days=-1,
          checklist=(("領収書の整理", True), ("精算システムへの入力", False))),
    _todo("備品の発注", MEMBER, _P, assignees=(ADMIN,), status=_DONE, priority=_LOW,
          checklist=(("見積もりの取得", True), ("発注", True)),
          comments=(_c(ADMIN, "発注しました。来週届きます。"),)),
    _todo("新機能の仕様レビュー", MEMBER, _O, organizations=(PLANNING,), assignees=(ADMIN, MEMBER2), status=_WIP, priority=_HIGH, due_in_days=0,
          description="レビュー観点: 権限、エラー時の挙動、画面の文言。",
          checklist=(("権限の確認", True), ("エラー時の挙動の確認", False), ("文言の確認", False)),
          comments=(_c(MEMBER2, "エラー時の挙動で 1 点気になる箇所があります。"), _c(ADMIN, "明日の定例で確認しましょう。"))),
    _todo("部署の引き継ぎ資料", MEMBER, _O, organizations=(LEGACY,), assignees=(MEMBER2,), due_in_days=10),
    _todo("勉強会の会場予約", MEMBER2, _T, priority=_LOW, due_in_days=7,
          comments=(_c(MEMBER, "第 2 会議室が空いていました。"),)),
    _todo("個人の目標設定", MEMBER2, _P, status=_WIP,
          checklist=(("上期の振り返り", True), ("下期の目標の記入", False))),
    _todo("取引先との打ち合わせ準備", MEMBER2, _P, assignees=(MEMBER,), priority=_HIGH, due_in_days=2,
          comments=(_c(MEMBER, "資料の印刷は私がやります。"),)),
    _todo("旧システムのデータ移行確認", MEMBER2, _O, organizations=(LEGACY,), status=_DONE, due_in_days=-5,
          checklist=(("件数の照合", True), ("差分の確認", True))),
    _todo("セキュリティ研修の受講", ADMIN, _T, assignees=(MEMBER, MEMBER2), due_in_days=14,
          comments=(_c(ADMIN, "期限までに全員受講をお願いします。"),)),
    _todo("年末の大掃除の段取り", ADMIN, _T, status=_DONE, priority=_LOW, due_in_days=-20),
    _todo("問い合わせ対応フローの見直し", MEMBER2, _O, organizations=(PLANNING,), assignees=(ADMIN,), status=_WIP, due_in_days=-3,
          checklist=(("現状のフローの図示", True), ("課題の洗い出し", False), ("改善案の作成", False)),
          comments=(_c(ADMIN, "課題の洗い出しは来週の定例で一緒にやりましょう。"),)),
    _todo("社内報の原稿依頼", ADMIN, _O, organizations=(PLANNING,), assignees=(MEMBER2,), priority=_LOW),
    _todo("ウェブサイトの文言修正", MEMBER, _T, assignees=(MEMBER2, ADMIN), status=_WIP, due_in_days=4,
          checklist=(("修正箇所の一覧化", True), ("修正", True), ("公開前の確認", True)),
          comments=(_c(MEMBER, "すべて修正しました。最終確認をお願いします。"),)),
)

BETA_TODOS: tuple[SeedTodo, ...] = (
    _todo("予算案の作成", ADMIN, _T, assignees=(MEMBER,), status=_WIP, priority=_HIGH, due_in_days=-1,
          checklist=(("前年実績の確認", True), ("部門ごとの要望の集約", False)),
          comments=(_c(ADMIN, "部門ごとの要望は金曜までに集めてください。"), _c(MEMBER, "承知しました。"))),
    _todo("チーム会議の議事録", MEMBER, _P, due_in_days=0),
    _todo("製品カタログの更新", MEMBER, _O, organizations=(PLANNING,), assignees=(MEMBER2,), priority=_LOW, due_in_days=3,
          checklist=(("掲載製品の確認", True), ("写真の差し替え", False)),
          comments=(_c(MEMBER2, "写真は来週撮影します。"),)),
    _todo("取引先リストの整理", MEMBER2, _P, assignees=(ADMIN,), status=_DONE,
          checklist=(("重複の削除", True), ("連絡先の更新", True))),
    _todo("旧拠点の契約確認", ADMIN, _O, organizations=(LEGACY,), due_in_days=10),
    _todo("採用面接の日程調整", MEMBER2, _T, assignees=(MEMBER, MEMBER2), status=_WIP, priority=_HIGH, due_in_days=2,
          comments=(_c(ADMIN, "候補日を 3 つ出してください。"),)),
)

# テナントコード → ToDo の定義
SEED_TODOS: Mapping[str, tuple[SeedTodo, ...]] = {"alpha": ALPHA_TODOS, "beta": BETA_TODOS}


# ---------------------------------------------------------------------------
# 結果
# ---------------------------------------------------------------------------
@dataclass(kw_only=True)
class SeedTodosResult:
    """1 テナントのシードの結果（表示用）。

    Attributes:
        tenant_code: テナントコード。
        action: ``seed``（実施した）/ ``skip``（台帳に無い・``ACTIVE`` でない）。
        users: 確保したユーザー数。
        organizations_created: 作成した組織の名前。
        organizations_deleted: 論理削除した組織の名前。
        todos_created: 作成した ToDo のタイトル。
        todos_existing: 既にあったため作らなかった ToDo の数。
        todos_skipped: 作れなかった ToDo のタイトル（公開先の組織が既に削除済みのもの）。
    """

    tenant_code: str
    action: str = "seed"
    users: int = 0
    organizations_created: list[str] = field(default_factory=list)
    organizations_deleted: list[str] = field(default_factory=list)
    todos_created: list[str] = field(default_factory=list)
    todos_existing: int = 0
    todos_skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """1 行の要約。"""
        if self.action != "seed":
            return f"{self.tenant_code}: action={self.action}"
        return (
            f"{self.tenant_code}: users={self.users} organizations_created={len(self.organizations_created)} organizations_deleted={len(self.organizations_deleted)}"
            f" todos_created={len(self.todos_created)} todos_existing={self.todos_existing} todos_skipped={len(self.todos_skipped)}"
        )


# ---------------------------------------------------------------------------
# 処理
# ---------------------------------------------------------------------------
@dataclass(frozen=True, kw_only=True)
class _SeedUser:
    """シードのユーザー（AP のユーザー ID とロール）。"""

    user_id: uuid.UUID
    idp_subject: str
    roles: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class _IdpUser:
    """Keycloak から引いたユーザーの値（ログイン時のトークンの代わり）。"""

    subject: str
    email: str | None
    first_name: str | None
    last_name: str | None
    roles: tuple[str, ...]


def user_key(tenant: DevTenant, user: DevUser) -> str:
    """ユーザーの呼び名（``alpha-member2`` → ``member2``）。"""
    prefix = f"{tenant.tenant_code}-"
    return user.username[len(prefix):] if user.username.startswith(prefix) else user.username


def _active_tenant_id(cp_session: Session, tenant: DevTenant) -> uuid.UUID | None:
    """台帳のテナント ID（``ACTIVE`` でなければ ``None``）。"""
    row = tenant_repo.get_tenant_by_code(cp_session, tenant.tenant_code)
    tenant_id, status = (row.id, row.status) if row is not None else (None, None)
    cp_session.rollback()
    if status != TenantStatus.ACTIVE:
        logger.warning("テナント %s は %s のため、ToDo のシードを省略します", tenant.tenant_code, status or "未登録")
        return None
    return tenant_id


def _fetch_idp_users(tenant: DevTenant) -> dict[str, _IdpUser]:
    """Keycloak のテナントレルムから、シードのユーザーの ``sub``・メール・姓・名・実効ロールを引く。

    Raises:
        RuntimeError: ユーザーが Keycloak に無い（``control_plane_app.seed`` が未実行）。
    """
    result: dict[str, _IdpUser] = {}
    with create_provisioner_admin_client() as admin:
        for user in DEV_TENANT_USERS[tenant.tenant_code]:
            found = find_user(admin, tenant.realm_name, user.username)
            if not found or not found.get("id"):
                raise RuntimeError(f"Keycloak にユーザー {user.username} がありません。先に python -m control_plane_app.seed を実行してください")
            roles = tuple(kc_users.get_user_effective_realm_roles(admin, tenant.realm_name, found["id"]))
            result[user_key(tenant, user)] = _IdpUser(subject=found["id"], email=found.get("email"), first_name=found.get("firstName"), last_name=found.get("lastName"), roles=roles)
    return result


def _sync_users(session: Session, tenant_id: uuid.UUID, idp_users: Mapping[str, _IdpUser]) -> dict[str, _SeedUser]:
    """ログイン時と同じ処理で ``t_user`` とデフォルト組織を確保する。"""
    users: dict[str, _SeedUser] = {}
    for key, idp in idp_users.items():
        display_name = " ".join(part for part in (idp.first_name, idp.last_name) if part) or None
        synced = sync_user_on_login(
            session, tenant_id=tenant_id, idp_subject=idp.subject, email=idp.email, display_name=display_name, first_name=idp.first_name, last_name=idp.last_name, roles=idp.roles
        )
        users[key] = _SeedUser(user_id=synced.user_id, idp_subject=idp.subject, roles=tuple(normalize_tenant_roles(idp.roles)))
    return users


def _ensure_organizations(session: Session, users: Mapping[str, _SeedUser], result: SeedTodosResult) -> dict[str, TOrganization]:
    """シードの組織を名前（論理削除済みを含む）で探し、無ければ作ってメンバーを設定する（削除は ToDo を作った後）。"""
    admin_subject = users[ADMIN].idp_subject
    organizations: dict[str, TOrganization] = {}
    for spec in SEED_ORGANIZATIONS:
        existing = session.exec(select(TOrganization).where(col(TOrganization.name) == spec.name).order_by(col(TOrganization.created_at))).first()
        if existing is None:
            service = OrganizationService(session, actor_subject=admin_subject)
            created = service.create_organization(name=spec.name)
            service.set_members(created.id, expected_version=created.version, user_ids=[users[key].user_id for key in spec.members])
            result.organizations_created.append(spec.name)
            existing = session.exec(select(TOrganization).where(col(TOrganization.id) == created.id)).one()
        organizations[spec.key] = existing
    session.rollback()
    return organizations


def _create_todo(session: Session, spec: SeedTodo, users: Mapping[str, _SeedUser], organizations: Mapping[str, TOrganization], today: dt.date) -> None:
    """ToDo・チェックリスト・コメントをサービス経由で作る（操作者は作成者・担当者・投稿者）。"""
    creator = users[spec.creator]
    view = TodoService(session, actor_user_id=creator.user_id, actor_roles=creator.roles).create_todo(
        title=spec.title,
        description=spec.description,
        due_date=None if spec.due_in_days is None else today + dt.timedelta(days=spec.due_in_days),
        priority=spec.priority,
        status=spec.status,
        visibility=spec.visibility,
        organization_ids=[organizations[key].id for key in spec.organizations],
        assignee_ids=[users[key].user_id for key in spec.assignees],
    )
    checklist_service = TodoChecklistService(session, actor_user_id=creator.user_id, actor_roles=creator.roles)
    checker = users[spec.assignees[0]] if spec.assignees else creator
    check_service = TodoChecklistService(session, actor_user_id=checker.user_id, actor_roles=checker.roles)
    for title, done in spec.checklist:
        item = checklist_service.add_item(view.id, title=title).items[-1]
        if done:
            check_service.update_item(view.id, item.id, expected_version=item.version, is_done=True)
    for comment in spec.comments:
        author = users[comment.author]
        TodoCommentService(session, actor_user_id=author.user_id, actor_roles=author.roles).create_comment(view.id, body=comment.body)


def _delete_organizations(session: Session, users: Mapping[str, _SeedUser], organizations: Mapping[str, TOrganization], result: SeedTodosResult) -> None:
    """``deleted`` の組織を論理削除する（既に削除済みなら何もしない）。"""
    for spec in SEED_ORGANIZATIONS:
        organization = organizations[spec.key]
        if not spec.deleted or organization.deleted_at is not None:
            continue
        current = session.exec(select(TOrganization).where(col(TOrganization.id) == organization.id)).one()
        OrganizationService(session, actor_subject=users[ADMIN].idp_subject).delete_organization(current.id, expected_version=current.version)
        result.organizations_deleted.append(spec.name)


def seed_tenant_todos(session: Session, tenant: DevTenant, tenant_id: uuid.UUID, idp_users: Mapping[str, _IdpUser], *, today: dt.date | None = None) -> SeedTodosResult:
    """1 テナントのユーザー・組織・ToDo を確保する（テナントコンテキスト下の AP セッションで呼ぶ）。

    Args:
        session: AP のセッション（``app_runtime``。テナントコンテキスト下）。
        tenant: 開発用テナント。
        tenant_id: テナント ID（台帳の値）。
        idp_users: Keycloak から引いたユーザー（呼び名 → 値）。
        today: 期限の基準日（省略時は UTC の今日）。

    Returns:
        SeedTodosResult: 結果。
    """
    today = today or utc_now().date()
    result = SeedTodosResult(tenant_code=tenant.tenant_code)
    users = _sync_users(session, tenant_id, idp_users)
    result.users = len(users)
    organizations = _ensure_organizations(session, users, result)
    existing = set(session.exec(select(TTodo.title).where(col(TTodo.title).startswith(SEED_PREFIX), col(TTodo.deleted_at).is_(None))).all())
    session.rollback()
    for spec in SEED_TODOS.get(tenant.tenant_code, ()):
        if spec.title in existing:
            result.todos_existing += 1
            continue
        if any(organizations[key].deleted_at is not None for key in spec.organizations):
            # 公開先が既に削除済みの組織は新たに指定できない（作成済みの ToDo を消した場合）
            logger.warning("公開先の組織が削除済みのため ToDo を作りません: tenant_code=%s title=%s", tenant.tenant_code, spec.title)
            result.todos_skipped.append(spec.title)
            continue
        _create_todo(session, spec, users, organizations, today)
        result.todos_created.append(spec.title)
    _delete_organizations(session, users, organizations, result)
    return result


def run_seed_todos(cp_session: Session, *, today: dt.date | None = None) -> list[SeedTodosResult]:
    """シード全体を実行する（``DEV_TENANTS`` のうち ``ACTIVE`` なテナント）。

    Args:
        cp_session: CP DB（``cp_runtime``）のセッション（台帳の確認用）。
        today: 期限の基準日（省略時は UTC の今日）。

    Returns:
        list[SeedTodosResult]: テナントごとの結果。

    Raises:
        RuntimeError: ``APP_ENV=development`` でない、Keycloak にシードのユーザーが無い。
    """
    require_explicit_development()
    from modules.tenancy.providers import open_app_session

    results: list[SeedTodosResult] = []
    for tenant in DEV_TENANTS:
        tenant_id = _active_tenant_id(cp_session, tenant)
        if tenant_id is None:
            result = SeedTodosResult(tenant_code=tenant.tenant_code, action="skip")
        else:
            idp_users = _fetch_idp_users(tenant)
            with tenant_scope(TenantContext(tenant_id=tenant_id, tenant_code=tenant.tenant_code, plane="app")), open_app_session() as session:
                result = seed_tenant_todos(session, tenant, tenant_id, idp_users, today=today)
        print(result.summary())
        results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    """CLI のエントリポイント。

    Args:
        argv: コマンドライン引数（``None`` なら ``sys.argv[1:]``）。

    Returns:
        int: 終了コード。
    """
    parser = argparse.ArgumentParser(prog="python -m dev_tools.seed_todos", description="開発用の ToDo・チェックリスト・コメントを冪等に作成する（APP_ENV=development のみ）。")
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ (INFO) を標準エラーに出力する")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)

    try:
        require_explicit_development()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    from modules.tenancy.providers import dispose_providers, get_cp_sessionmaker

    try:
        with get_cp_sessionmaker()() as cp_session:
            run_seed_todos(cp_session)
    except (AppServiceError, KeycloakAdminError, SQLAlchemyError, ValueError, RuntimeError) as exc:
        # 例外メッセージには秘匿値を含めない設計（services/errors.py、keycloak_admin/errors.py）
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        dispose_providers()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
