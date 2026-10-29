#!/usr/bin/env python
# coding:utf-8
"""テナントの払い出し・停止・再開・削除要求・物理削除を行うサービス（CP）。

仕様の正: 01 §5（テナント識別）、§6（ライフサイクル CP-ONB-01..10 / CP-OPS-01..10）、03 §5.2（楽観ロック）、
§7（監査ログ）。手順と守ること: ``tenant-provisioning`` スキル §3.1。

FastAPI に依存しない。CP DB の :class:`~sqlmodel.Session`（``cp_runtime``）と Keycloak の管理クライアントを受け取り、
**トランザクションの境界（コミット）はサービスが決める**。API・定期ジョブ・開発用シードから同じコードを使う。

使用例（API のエンドポイントから）::

    from modules.keycloak_admin.templates import create_provisioner_admin_client

    with create_provisioner_admin_client() as admin:
        service = TenantProvisioningService(session, admin)
        result = service.onboard(tenant_code="acme", name="Acme", initial_admin=InitialAdminSpec(email="admin@acme.example"), actor=user["sub"])
    # result.temporary_password はレスポンスで一度だけ返す。ログ等に出さない。

公開メソッド
============

- :meth:`TenantProvisioningService.onboard` — （新規）→ PROVISIONING → ACTIVE / FAILED
    例外: ``TenantValidationError``, ``InvalidTenantCodeError``, ``TenantCodeAlreadyExistsError``,
    ``TenantOperationInProgressError``, ``ProvisioningFailedError``
- :meth:`TenantProvisioningService.retry` — FAILED / PROVISIONING（中断）→ PROVISIONING → ACTIVE / FAILED
    例外: ``TenantValidationError``, ``TenantNotFoundError``, ``InvalidTenantTransitionError``, ``TenantVersionConflictError``,
    ``TenantOperationInProgressError``, ``ProvisioningFailedError``
- :meth:`TenantProvisioningService.suspend` — ACTIVE → SUSPENDED（レルム無効化）
    例外: ``TenantNotFoundError``, ``InvalidTenantTransitionError``, ``TenantVersionConflictError``, ``TenantRealmOperationError``
- :meth:`TenantProvisioningService.resume` — SUSPENDED → ACTIVE（レルム有効化）。例外は suspend と同じ
- :meth:`TenantProvisioningService.request_deletion` — ACTIVE / SUSPENDED / FAILED → PENDING_DELETION（レルム無効化、猶予 30 日）。
    例外は suspend と同じ
- :meth:`TenantProvisioningService.deprovision` — PENDING_DELETION（猶予経過）/ DEPROVISIONING → DEPROVISIONING → DELETED（定期ジョブ用）
    例外: ``TenantNotFoundError``, ``InvalidTenantTransitionError``, ``DeletionGracePeriodNotElapsedError``,
    ``TenantOperationInProgressError``, ``DeprovisioningFailedError``

例外はすべて :mod:`control_plane_app.services.errors` に定義し、HTTP ステータスとの対応も同モジュールに記載する。
中断した払い出しの回収と、猶予経過テナントの抽出は :mod:`control_plane_app.services.tenant_maintenance`。

守ること（実装済み）
====================

- ``PROVISIONING`` の記録（台帳・払い出し履歴・監査ログ）は Keycloak を呼ぶ前にコミットする。各ステップの開始も履歴に都度コミットする（CP-ONB-08）
- 同じテナントの払い出し・再実行・物理削除は、CP DB の advisory lock で同時実行を防ぐ（CP-ONB-07）。テナントコードは一意制約でも守る
- 各ステップは冪等（Keycloak 側は ``ensure_*`` / ``delete_realm_if_exists``）。再実行で同じ状態に収束する（CP-ONB-04）
- 締め切り（30 秒）は管理クライアントの ``deadline_seconds`` に任せる。**1 回の操作ごとに管理クライアントを作る**（CP-ONB-06）
- 一時パスワードは戻り値で一度だけ返し、DB・監査ログ・払い出し履歴・ログに残さない（CP-ONB-10）
- 払い出し履歴の ``error`` と監査ログには、ステップ名・例外の型・HTTP ステータスだけを記録する（``KeycloakAdminError.detail`` を残さない）
- 停止・再開・削除要求は行ロック（``SELECT ... FOR UPDATE``）の下で Keycloak を操作し、成功したら状態を更新する。
  Keycloak が失敗したら状態は変えない。DB のコミットだけが失敗した場合も、同じ操作の再実行で収束する
"""
import datetime as dt
import logging
import secrets
import string
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from control_plane_app.models.sql_models import ProvisioningType, RunStatus, TenantStatus, TProvisioningHistory, TTenant
from control_plane_app.repositories import tenant_repository as repo
from control_plane_app.repositories.app_tenant_data import AppTenantDataRepository
from control_plane_app.repositories.locks import OperationLock, PgAdvisoryLock, tenant_lock_key
from control_plane_app.services.errors import (
    DeletionGracePeriodNotElapsedError,
    DeprovisioningFailedError,
    InvalidTenantCodeError,
    InvalidTenantTransitionError,
    ProvisioningFailedError,
    TenantCodeAlreadyExistsError,
    TenantNotFoundError,
    TenantOperationInProgressError,
    TenantRealmOperationError,
    TenantValidationError,
    TenantVersionConflictError,
)
from control_plane_app.services.tenant_lifecycle import DELETION_GRACE_PERIOD, OPERATION_RULES, TenantOperation, is_operation_allowed
from modules.keycloak_admin import templates as kc
from modules.keycloak_admin.admin_client import KeycloakAdminClient
from modules.keycloak_admin.errors import KeycloakAdminError
from modules.tenancy.tenant_code import InvalidTenantCodeFormatError, validate_tenant_code

logger = logging.getLogger(__name__)

# 定期ジョブ・システム処理の操作者（t_tenant.created_by / updated_by、t_cp_audit_log.actor）
SYSTEM_ACTOR = "system"

# 中断した（RUNNING のまま残った）払い出し履歴を閉じるときのエラー種別
INTERRUPTED_ERROR = "interrupted"

# 初期管理者に付与するレルムロール（01 §7.5）
TENANT_ADMIN_ROLE = "tenant_admin"

# テナント名の最大文字数（Keycloak のレルム表示名にも使う）
TENANT_NAME_MAX_LENGTH = 100

# 初期管理者の姓・名の既定値（Keycloak の既定のユーザープロフィールで必須のため。02 §3.2）
DEFAULT_INITIAL_ADMIN_FIRST_NAME = "Tenant"
DEFAULT_INITIAL_ADMIN_LAST_NAME = "Administrator"

# 一時パスワードの長さと文字種
TEMPORARY_PASSWORD_LENGTH = 20
_PASSWORD_SYMBOLS = "!@#$%^&*-_=+"
_PASSWORD_ALPHABET = string.ascii_letters + string.digits + _PASSWORD_SYMBOLS


class OnboardStep(StrEnum):
    """払い出し（onboard）のステップ名（払い出し履歴の ``step``）。01 §6.2 の払い出しステップに対応する。"""

    # 1. テナント台帳に登録（PROVISIONING）
    REGISTER_TENANT = "register_tenant"
    # 1'. 再実行の開始（FAILED → PROVISIONING）
    RESTART = "restart"
    # 2-3. レルム・クライアント・サービスアカウント・ロール・マッパー
    ENSURE_TENANT_REALM = "ensure_tenant_realm"
    # 4. 初期管理者（一時パスワード）
    ENSURE_INITIAL_ADMIN = "ensure_initial_admin"
    # 5-6. AP の初期データ（初期管理者のユーザー行・デフォルト組織）とテーマ固有の初期データは CP からは作らない。
    #      CP → AP の依存を集計・物理削除に限るため（01 §4.3、05 #31）、AP がログイン完了時に作る
    #      （main_app.services.user_sync.sync_user_on_login）。そのため払い出しのステップは無い
    # 7. ACTIVE にする
    ACTIVATE = "activate"


class OffboardStep(StrEnum):
    """物理削除（offboard）のステップ名（払い出し履歴の ``step``）。01 CP-OPS-08。"""

    PURGE_APP_DATA = "purge_app_data"
    DELETE_REALM = "delete_realm"
    MARK_DELETED = "mark_deleted"


class AuditAction(StrEnum):
    """CP 監査ログの ``action``（03 §7 の ``resource.verb``）。"""

    CREATE = "tenant.create"
    PROVISION_RETRY = "tenant.provision_retry"
    PROVISION_SUCCEED = "tenant.provision_succeed"
    PROVISION_FAIL = "tenant.provision_fail"
    PROVISION_REAP = "tenant.provision_reap"
    SUSPEND = "tenant.suspend"
    RESUME = "tenant.resume"
    REQUEST_DELETION = "tenant.request_deletion"
    DEPROVISION_START = "tenant.deprovision_start"
    DEPROVISION_FAIL = "tenant.deprovision_fail"
    DELETE = "tenant.delete"


# ---------------------------------------------------------------------------
# 入力・戻り値
# ---------------------------------------------------------------------------
@dataclass(frozen=True, kw_only=True)
class InitialAdminSpec:
    """初期管理者（テナント作成時に入力する。01 CP-ONB-01）。

    Attributes:
        email: メールアドレス（レルム内で一意）。
        username: ユーザー名。省略時はメールアドレス（Keycloak は小文字に正規化する）。
        first_name: 名。省略時は ``Tenant``。
        last_name: 姓。省略時は ``Administrator``。
    """

    email: str
    username: str | None = None
    first_name: str = DEFAULT_INITIAL_ADMIN_FIRST_NAME
    last_name: str = DEFAULT_INITIAL_ADMIN_LAST_NAME

    @property
    def login_username(self) -> str:
        """Keycloak に作成するユーザー名を返す（小文字に正規化）。"""
        return (self.username or self.email).strip().lower()


@dataclass(frozen=True, kw_only=True)
class TenantView:
    """テナント台帳の 1 行のスナップショット（セッションから切り離した値。API のレスポンスに使う）。

    Attributes はすべて ``t_tenant`` の列と同じ。``version`` は ETag に使う（03 §5.2）。
    """

    id: uuid.UUID
    tenant_code: str
    name: str
    status: str
    realm_name: str
    tier: str | None
    version: int
    created_by: str | None
    updated_by: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    deletion_requested_at: dt.datetime | None
    deleted_at: dt.datetime | None

    @classmethod
    def from_model(cls, tenant: TTenant) -> "TenantView":
        """モデルからスナップショットを作る。

        Args:
            tenant: テナント（セッションに属していること）。

        Returns:
            TenantView: スナップショット。
        """
        return cls(
            id=tenant.id,
            tenant_code=tenant.tenant_code,
            name=tenant.name,
            status=tenant.status,
            realm_name=tenant.realm_name,
            tier=tenant.tier,
            version=tenant.version,
            created_by=tenant.created_by,
            updated_by=tenant.updated_by,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
            deletion_requested_at=tenant.deletion_requested_at,
            deleted_at=tenant.deleted_at,
        )


@dataclass(frozen=True, kw_only=True)
class OnboardResult:
    """払い出し（onboard / retry）の結果。

    Attributes:
        tenant: 払い出し後のテナント（``ACTIVE``）。
        history_id: 払い出し履歴の ID。
        initial_admin_username: 初期管理者のユーザー名。
        temporary_password: 初期管理者の一時パスワード。**レスポンスで一度だけ返し、どこにも保存しない**。``repr`` に出さない。
    """

    tenant: TenantView
    history_id: uuid.UUID
    initial_admin_username: str
    temporary_password: str = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class DeprovisionResult:
    """物理削除の結果。

    Attributes:
        tenant: 削除後のテナント（``DELETED``。台帳の行は残す）。
        history_id: 払い出し履歴（offboard）の ID。
        purged_rows: AP DB のステップ（テーブル）ごとの削除件数。
        realm_deleted: 今回レルムを削除したか（既に無ければ ``False``）。
    """

    tenant: TenantView
    history_id: uuid.UUID
    purged_rows: dict[str, int]
    realm_deleted: bool


# ---------------------------------------------------------------------------
# 補助
# ---------------------------------------------------------------------------
def utcnow() -> dt.datetime:
    """現在時刻（UTC、タイムゾーン付き）を返す。"""
    return dt.datetime.now(dt.UTC)


def generate_temporary_password(length: int = TEMPORARY_PASSWORD_LENGTH) -> str:
    """初期管理者の一時パスワードを生成する（英大文字・小文字・数字・記号をそれぞれ 1 文字以上含む）。

    Args:
        length: 長さ（8 以上）。

    Returns:
        str: 一時パスワード。ログ等に出さないこと。
    """
    if length < 8:
        raise ValueError("length must be >= 8")
    while True:
        password = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if (any(c.islower() for c in password) and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password) and any(c in _PASSWORD_SYMBOLS for c in password)):
            return password


def summarize_error(step: str, exc: BaseException) -> str:
    """払い出し履歴・監査ログに残すエラーの要約を作る（秘匿値・外部のエラーメッセージを含めない）。

    ``KeycloakAdminError`` の ``detail`` / ``operation``（ユーザー名を含みうる）は残さず、HTTP ステータスだけを残す。

    Args:
        step: 失敗したステップ名。
        exc: 例外。

    Returns:
        str: 例: ``step=ensure_tenant_realm; error=KeycloakAdminTimeoutError``、
            ``step=ensure_initial_admin; error=KeycloakAdminError; http_status=409``。
    """
    parts = [f"step={step}", f"error={type(exc).__name__}"]
    if isinstance(exc, KeycloakAdminError) and exc.status_code is not None:
        parts.append(f"http_status={exc.status_code}")
    return "; ".join(parts)


def bump_version(tenant: TTenant, actor: str) -> None:
    """台帳の更新者とバージョン（+1）を設定する（03 §5.2）。``updated_at`` はモデルの ``onupdate`` で更新される。

    Args:
        tenant: テナント。
        actor: 操作者。
    """
    tenant.version += 1
    tenant.updated_by = actor


def engine_of(session: Session) -> Engine:
    """セッションの接続先エンジンを返す（advisory lock 用の別接続を取るため）。

    Args:
        session: CP DB のセッション。

    Returns:
        Engine: エンジン。
    """
    bind = session.get_bind()
    return bind if isinstance(bind, Engine) else bind.engine


def status_change_payload(before: str | None, after: str, version_before: int | None, version_after: int) -> dict[str, Any]:
    """監査ログの payload（状態とバージョンの変更前後）を作る。

    Args:
        before: 変更前の状態（新規作成なら ``None``）。
        after: 変更後の状態。
        version_before: 変更前のバージョン（新規作成なら ``None``）。
        version_after: 変更後のバージョン。

    Returns:
        dict[str, Any]: ``{"status": {"before", "after"}, "version": {"before", "after"}}``。
    """
    return {"status": {"before": before, "after": after}, "version": {"before": version_before, "after": version_after}}


def _validate_actor(actor: str) -> str:
    """操作者を検証する。"""
    if not isinstance(actor, str) or not actor.strip():
        raise TenantValidationError("actor", "required")
    return actor.strip()


def _validate_name(name: str) -> str:
    """テナント名を検証し、前後の空白を除いて返す。"""
    if not isinstance(name, str) or not name.strip():
        raise TenantValidationError("name", "required")
    value = name.strip()
    if len(value) > TENANT_NAME_MAX_LENGTH:
        raise TenantValidationError("name", "too_long")
    return value


def _validate_initial_admin(spec: InitialAdminSpec) -> InitialAdminSpec:
    """初期管理者を検証し、前後の空白を除いたものを返す。メールの形式は最小限（``@`` の前後が空でない）だけ確認する。"""
    email = (spec.email or "").strip()
    local, _, domain = email.partition("@")
    if not email or not local or not domain or "@" in domain or any(c.isspace() for c in email) or len(email) > 254:
        raise TenantValidationError("initial_admin.email", "format")
    first_name = (spec.first_name or "").strip()
    last_name = (spec.last_name or "").strip()
    if not first_name:
        raise TenantValidationError("initial_admin.first_name", "required")
    if not last_name:
        raise TenantValidationError("initial_admin.last_name", "required")
    username = spec.username.strip() if spec.username else None
    if spec.username is not None and not username:
        raise TenantValidationError("initial_admin.username", "required")
    return InitialAdminSpec(email=email, username=username, first_name=first_name, last_name=last_name)


def validate_new_tenant_code(tenant_code: object) -> str:
    """テナント作成時のテナントコードを検証する（01 §5.1 の形式と §5.2 の予約語。CP-ONB-02）。

    Args:
        tenant_code: 検証対象（外部入力）。

    Returns:
        str: 検証済みのテナントコード。

    Raises:
        InvalidTenantCodeError: 形式違反（``reason=format``）または予約語（``reason=reserved``）。
    """
    try:
        return validate_tenant_code(tenant_code)
    except InvalidTenantCodeFormatError as exc:
        raise InvalidTenantCodeError(exc.violation.value) from None


# ---------------------------------------------------------------------------
# サービス
# ---------------------------------------------------------------------------
class TenantProvisioningService:
    """テナントのライフサイクル操作（払い出し・再実行・停止・再開・削除要求・物理削除）。

    1 回の操作（API の 1 リクエスト、物理削除の 1 テナント）ごとにインスタンスを作る。
    管理クライアントの締め切り（既定 30 秒）は生成時点から数えるため、管理クライアントも操作ごとに作ること。

    Args:
        session: CP DB（``cp_runtime``）のセッション。サービスがコミット・ロールバックする。
            呼び出し前に未コミットの変更を持たないこと。
        admin: Keycloak の管理クライアント（:func:`modules.keycloak_admin.templates.create_provisioner_admin_client`）。
        app_data: AP DB のテナントデータの物理削除（省略時は ``app_cp_agent`` で接続する既定の実装）。
        lock: テナント単位の排他ロック（省略時は CP DB の advisory lock）。
        clock: 現在時刻（UTC）を返す関数。
        password_generator: 一時パスワードを生成する関数。
    """

    def __init__(
        self,
        session: Session,
        admin: KeycloakAdminClient,
        *,
        app_data: AppTenantDataRepository | None = None,
        lock: OperationLock | None = None,
        clock: Callable[[], dt.datetime] = utcnow,
        password_generator: Callable[[], str] = generate_temporary_password,
    ) -> None:
        """依存を保持する（ここでは DB・Keycloak に接続しない）。"""
        self._session = session
        self._admin = admin
        self._app_data = app_data
        self._lock = lock
        self._clock = clock
        self._password_generator = password_generator

    # ------------------------------------------------------------------ 公開メソッド
    def onboard(self, *, tenant_code: str, name: str, initial_admin: InitialAdminSpec, actor: str, request_id: str | None = None, tenant_id: uuid.UUID | None = None) -> OnboardResult:
        """テナントを作成し、払い出しを同期実行する（01 §6.2）。

        手順:
            1. 入力の検証（テナントコードの形式・予約語、テナント名、初期管理者）
            2. テナント単位のロックを取得（取れなければ ``TenantOperationInProgressError``）
            3. 台帳に ``PROVISIONING``・払い出し履歴 ``RUNNING``・監査ログ ``tenant.create`` を **コミット**
            4. レルムのテンプレートを適用（:func:`~modules.keycloak_admin.templates.ensure_tenant_realm`）
            5. 初期管理者を作成（``tenant_admin``、一時パスワード、``UPDATE_PASSWORD``）
            6. ``ACTIVE`` にして履歴 ``SUCCEEDED``・監査ログ ``tenant.provision_succeed`` をコミット

            4〜6 が失敗したら ``FAILED`` と履歴 ``FAILED``・監査ログ ``tenant.provision_fail`` をコミットし、
            ``ProvisioningFailedError`` を送出する（:meth:`retry` で再実行できる）。

        Args:
            tenant_code: テナントコード（01 §5.1 の形式、§5.2 の予約語は不可）。
            name: テナント名（レルムの表示名にも使う）。
            initial_admin: 初期管理者。
            actor: 操作者（CP 管理者の IdP subject。シード・ジョブは ``system``）。
            request_id: リクエスト ID（監査ログ用）。
            tenant_id: テナント ID を指定する場合（テスト・シード用）。省略時は UUIDv7 を採番する。

        Returns:
            OnboardResult: 結果（一時パスワードを含む）。

        Raises:
            InvalidTenantCodeError: テナントコードが形式違反・予約語。
            TenantValidationError: テナント名・初期管理者・操作者が不正。
            TenantCodeAlreadyExistsError: テナントコード（レルム名）が使用済み（削除済みを含む）。
            TenantOperationInProgressError: 同じテナントコードの払い出しが実行中。
            ProvisioningFailedError: Keycloak 等の外部操作に失敗し、``FAILED`` にした。
        """
        tenant_code = validate_new_tenant_code(tenant_code)
        name = _validate_name(name)
        initial_admin = _validate_initial_admin(initial_admin)
        actor = _validate_actor(actor)
        realm_name = kc.tenant_realm_name(tenant_code)

        with self._tenant_lock(tenant_code):
            if repo.tenant_code_or_realm_exists(self._session, tenant_code, realm_name):
                self._session.rollback()
                raise TenantCodeAlreadyExistsError(tenant_code)

            now = self._clock()
            tenant = TTenant(
                id=tenant_id or uuid.uuid7(),
                tenant_code=tenant_code,
                name=name,
                status=TenantStatus.PROVISIONING.value,
                realm_name=realm_name,
                version=1,
                created_by=actor,
                updated_by=actor,
            )
            new_tenant_id = tenant.id
            try:
                self._session.add(tenant)
                self._session.flush()
                history = repo.add_provisioning_history(self._session, new_tenant_id, ProvisioningType.ONBOARD, OnboardStep.REGISTER_TENANT, now)
                history_id = history.id
                repo.add_cp_audit_log(
                    self._session, actor=actor, action=AuditAction.CREATE, tenant_id=new_tenant_id, request_id=request_id,
                    payload={"tenant_code": tenant_code, "name": name, **status_change_payload(None, TenantStatus.PROVISIONING.value, None, 1)},
                )
                # CP-ONB-08: 外部呼び出しの前に PROVISIONING をコミットする
                self._session.commit()
            except IntegrityError:
                self._session.rollback()
                raise TenantCodeAlreadyExistsError(tenant_code) from None
            logger.info("テナントを登録しました（PROVISIONING）: tenant_id=%s tenant_code=%s", new_tenant_id, tenant_code)

            return self._run_onboard_steps(new_tenant_id, history_id, initial_admin, actor, request_id)

    def retry(self, tenant_id: uuid.UUID, *, initial_admin: InitialAdminSpec, actor: str, expected_version: int | None = None, request_id: str | None = None) -> OnboardResult:
        """失敗（``FAILED``）または中断（``PROVISIONING`` のまま実行中でない）した払い出しを再実行する（01 CP-ONB-04）。

        各ステップは冪等なので、途中まで作成済みのレルム・ユーザーはそのまま使う。初期管理者のパスワードは
        新しい一時パスワードに設定し直す（前回の一時パスワードは無効になる）。

        Args:
            tenant_id: テナント ID。
            initial_admin: 初期管理者（台帳に保存していないため、再実行時にも指定する）。
            actor: 操作者。
            expected_version: 楽観ロックのバージョン（``If-Match``）。``None`` なら確認しない。
            request_id: リクエスト ID。

        Returns:
            OnboardResult: 結果（新しい一時パスワードを含む）。

        Raises:
            TenantValidationError: 初期管理者・操作者が不正。
            TenantNotFoundError: テナントが存在しない。
            InvalidTenantTransitionError: ``FAILED`` / ``PROVISIONING`` 以外。
            TenantVersionConflictError: バージョン不一致。
            TenantOperationInProgressError: 払い出しが実行中。
            ProvisioningFailedError: 再実行が失敗し、``FAILED`` にした。
        """
        initial_admin = _validate_initial_admin(initial_admin)
        actor = _validate_actor(actor)
        tenant_code = self._require_tenant(tenant_id).tenant_code
        self._session.rollback()

        with self._tenant_lock(tenant_code):
            tenant = self._require_tenant(tenant_id, for_update=True)
            self._check_operation(tenant, TenantOperation.RETRY)
            self._check_version(tenant, expected_version)

            now = self._clock()
            before_status, before_version = tenant.status, tenant.version
            repo.close_running_histories(self._session, tenant_id, ProvisioningType.ONBOARD, INTERRUPTED_ERROR, now)
            tenant.status = TenantStatus.PROVISIONING.value
            bump_version(tenant, actor)
            history = repo.add_provisioning_history(self._session, tenant_id, ProvisioningType.ONBOARD, OnboardStep.RESTART, now)
            history_id = history.id
            repo.add_cp_audit_log(self._session, actor=actor, action=AuditAction.PROVISION_RETRY, tenant_id=tenant_id, request_id=request_id,
                                  payload=status_change_payload(before_status, tenant.status, before_version, tenant.version))
            self._session.commit()
            logger.info("払い出しを再実行します: tenant_id=%s status_before=%s", tenant_id, before_status)

            return self._run_onboard_steps(tenant_id, history_id, initial_admin, actor, request_id)

    def suspend(self, tenant_id: uuid.UUID, *, actor: str, expected_version: int | None = None, request_id: str | None = None) -> TenantView:
        """テナントを停止する（ACTIVE → SUSPENDED、レルムを無効化。01 CP-OPS-03）。

        AP API の 403 は、テナントレジストリのキャッシュ期間（30 秒）以内に反映される（CP-OPS-10）。

        Args:
            tenant_id: テナント ID。
            actor: 操作者。
            expected_version: 楽観ロックのバージョン（``If-Match``）。``None`` なら確認しない。
            request_id: リクエスト ID。

        Returns:
            TenantView: 停止後のテナント。

        Raises:
            TenantNotFoundError / InvalidTenantTransitionError / TenantVersionConflictError: 状態・バージョンの不一致。
            TenantRealmOperationError: レルムの無効化に失敗した（状態は変更しない）。
        """
        return self._switch_realm_and_status(tenant_id, TenantOperation.SUSPEND, AuditAction.SUSPEND, realm_enabled=False,
                                             actor=actor, expected_version=expected_version, request_id=request_id)

    def resume(self, tenant_id: uuid.UUID, *, actor: str, expected_version: int | None = None, request_id: str | None = None) -> TenantView:
        """停止中のテナントを再開する（SUSPENDED → ACTIVE、レルムを有効化。01 CP-OPS-04）。

        Args:
            tenant_id: テナント ID。
            actor: 操作者。
            expected_version: 楽観ロックのバージョン（``If-Match``）。``None`` なら確認しない。
            request_id: リクエスト ID。

        Returns:
            TenantView: 再開後のテナント。

        Raises:
            TenantNotFoundError / InvalidTenantTransitionError / TenantVersionConflictError: 状態・バージョンの不一致。
            TenantRealmOperationError: レルムの有効化に失敗した（レルムが無い場合を含む。状態は変更しない）。
        """
        return self._switch_realm_and_status(tenant_id, TenantOperation.RESUME, AuditAction.RESUME, realm_enabled=True,
                                             actor=actor, expected_version=expected_version, request_id=request_id)

    def request_deletion(self, tenant_id: uuid.UUID, *, actor: str, expected_version: int | None = None, request_id: str | None = None) -> TenantView:
        """テナントの削除を要求する（ACTIVE / SUSPENDED / FAILED → PENDING_DELETION。01 CP-OPS-05, 06）。

        レルムを無効化し、``deletion_requested_at`` を記録する。物理削除は猶予期間（30 日）の経過後に
        定期ジョブが :meth:`deprovision` で行う。``FAILED`` でレルムが未作成の場合、無効化は省略する。

        Args:
            tenant_id: テナント ID。
            actor: 操作者。
            expected_version: 楽観ロックのバージョン（``If-Match``）。``None`` なら確認しない。
            request_id: リクエスト ID。

        Returns:
            TenantView: 削除要求後のテナント。

        Raises:
            TenantNotFoundError / InvalidTenantTransitionError / TenantVersionConflictError: 状態・バージョンの不一致。
            TenantRealmOperationError: レルムの無効化に失敗した（状態は変更しない）。
        """
        return self._switch_realm_and_status(tenant_id, TenantOperation.REQUEST_DELETION, AuditAction.REQUEST_DELETION, realm_enabled=False,
                                             actor=actor, expected_version=expected_version, request_id=request_id)

    def deprovision(self, tenant_id: uuid.UUID, *, actor: str = SYSTEM_ACTOR, request_id: str | None = None, grace_period: dt.timedelta = DELETION_GRACE_PERIOD) -> DeprovisionResult:
        """猶予期間を過ぎたテナントを物理削除する（PENDING_DELETION / DEPROVISIONING → DELETED。01 CP-OPS-08）。

        定期ジョブ（``tenant_purge``）から呼ぶ。API からは呼ばない。

        手順:
            1. ``PENDING_DELETION`` なら猶予期間の経過を確認して ``DEPROVISIONING`` にし、履歴 ``RUNNING`` とともにコミット
               （``DEPROVISIONING`` なら前回の失敗の再試行として新しい履歴を作る）
            2. AP DB のテナントデータを削除（``app_cp_agent`` + :func:`~modules.tenancy.db.run_per_tenant`。対象は
               :data:`control_plane_app.repositories.app_tenant_data.TENANT_DATA_PURGE_TABLES`）
            3. レルムを削除（既に無ければスキップ）
            4. ``DELETED``・``deleted_at`` をコミット（台帳の行は残す。CP-OPS-09）

            2〜4 が失敗したら ``DEPROVISIONING`` のまま履歴 ``FAILED`` をコミットし、``DeprovisioningFailedError`` を送出する。

        Args:
            tenant_id: テナント ID。
            actor: 操作者（既定 ``system``）。
            request_id: リクエスト ID。
            grace_period: 猶予期間（既定 30 日）。

        Returns:
            DeprovisionResult: 結果。

        Raises:
            TenantNotFoundError: テナントが存在しない。
            InvalidTenantTransitionError: ``PENDING_DELETION`` / ``DEPROVISIONING`` 以外。
            DeletionGracePeriodNotElapsedError: 猶予期間が経過していない。
            TenantOperationInProgressError: 同じテナントの処理が実行中。
            DeprovisioningFailedError: 削除のいずれかのステップが失敗した。
        """
        actor = _validate_actor(actor)
        tenant_code = self._require_tenant(tenant_id).tenant_code
        self._session.rollback()

        with self._tenant_lock(tenant_code):
            tenant = self._require_tenant(tenant_id, for_update=True)
            self._check_operation(tenant, TenantOperation.DEPROVISION)
            now = self._clock()
            if tenant.status == TenantStatus.PENDING_DELETION:
                deletable_at = (tenant.deletion_requested_at or now) + grace_period
                if now < deletable_at:
                    self._session.rollback()
                    raise DeletionGracePeriodNotElapsedError(tenant_id, TenantStatus.PENDING_DELETION.value, deletable_at)
                before_status, before_version = tenant.status, tenant.version
                tenant.status = TenantStatus.DEPROVISIONING.value
                bump_version(tenant, actor)
                repo.add_cp_audit_log(self._session, actor=actor, action=AuditAction.DEPROVISION_START, tenant_id=tenant_id, request_id=request_id,
                                      payload=status_change_payload(before_status, tenant.status, before_version, tenant.version))
            repo.close_running_histories(self._session, tenant_id, ProvisioningType.OFFBOARD, INTERRUPTED_ERROR, now)
            history = repo.add_provisioning_history(self._session, tenant_id, ProvisioningType.OFFBOARD, OffboardStep.PURGE_APP_DATA, now)
            history_id = history.id
            realm_name = tenant.realm_name
            self._session.commit()
            logger.info("テナントの物理削除を開始します: tenant_id=%s", tenant_id)

            step: str = OffboardStep.PURGE_APP_DATA
            try:
                purged_rows = self._app_data_repository().purge_tenant_data(tenant_id)
                step = OffboardStep.DELETE_REALM
                self._set_history_step(history_id, step)
                realm_deleted = kc.delete_realm_if_exists(self._admin, realm_name)
                step = OffboardStep.MARK_DELETED
                tenant = self._require_tenant(tenant_id, for_update=True)
                before_status, before_version = tenant.status, tenant.version
                finished_at = self._clock()
                tenant.status = TenantStatus.DELETED.value
                tenant.deleted_at = finished_at
                bump_version(tenant, actor)
                self._finish_history(history_id, RunStatus.SUCCEEDED, step, finished_at)
                repo.add_cp_audit_log(self._session, actor=actor, action=AuditAction.DELETE, tenant_id=tenant_id, request_id=request_id,
                                      payload={**status_change_payload(before_status, tenant.status, before_version, tenant.version),
                                               "purged_rows": purged_rows, "realm_deleted": realm_deleted})
                self._session.commit()
                view = TenantView.from_model(tenant)
            except Exception as exc:
                self._session.rollback()
                summary = summarize_error(step, exc)
                logger.warning("テナントの物理削除に失敗しました（次回の定期ジョブで再試行します）: tenant_id=%s %s", tenant_id, summary)
                self._record_failure(tenant_id, history_id, step, summary, actor, request_id, AuditAction.DEPROVISION_FAIL, failed_status=None)
                raise DeprovisioningFailedError(tenant_id, step, summary) from exc

            logger.info("テナントを物理削除しました: tenant_id=%s realm_deleted=%s", tenant_id, realm_deleted)
            return DeprovisionResult(tenant=view, history_id=history_id, purged_rows=purged_rows, realm_deleted=realm_deleted)

    # ------------------------------------------------------------------ 払い出しのステップ
    def _run_onboard_steps(self, tenant_id: uuid.UUID, history_id: uuid.UUID, initial_admin: InitialAdminSpec, actor: str, request_id: str | None) -> OnboardResult:
        """PROVISIONING をコミットした後の払い出しステップ（レルム → 初期管理者 → ACTIVE）を実行する。

        Args:
            tenant_id: テナント ID。
            history_id: 払い出し履歴の ID。
            initial_admin: 初期管理者（検証済み）。
            actor: 操作者。
            request_id: リクエスト ID。

        Returns:
            OnboardResult: 結果。

        Raises:
            ProvisioningFailedError: いずれかのステップが失敗した（``FAILED`` をコミット済み）。
        """
        step: str = OnboardStep.ENSURE_TENANT_REALM
        username = initial_admin.login_username
        try:
            tenant = self._require_tenant(tenant_id)
            tenant_code, display_name = tenant.tenant_code, tenant.name
            self._set_history_step(history_id, step)
            realm = kc.ensure_tenant_realm(self._admin, tenant_code=tenant_code, tenant_id=tenant_id, display_name=display_name, enabled=True)

            step = OnboardStep.ENSURE_INITIAL_ADMIN
            self._set_history_step(history_id, step)
            temporary_password = self._password_generator()
            kc.ensure_tenant_user(
                self._admin,
                realm_name=realm.realm_name,
                username=username,
                email=initial_admin.email,
                first_name=initial_admin.first_name,
                last_name=initial_admin.last_name,
                roles=[TENANT_ADMIN_ROLE],
                password=temporary_password,
                temporary=True,
            )

            step = OnboardStep.ACTIVATE
            tenant = self._require_tenant(tenant_id, for_update=True)
            if tenant.status != TenantStatus.PROVISIONING:
                # ロックを保持しているため通常は起きない（回収ジョブ等と競合した場合）
                raise InvalidTenantTransitionError(tenant_id, "activate", tenant.status)
            before_version = tenant.version
            tenant.status = TenantStatus.ACTIVE.value
            bump_version(tenant, actor)
            self._finish_history(history_id, RunStatus.SUCCEEDED, step, self._clock())
            repo.add_cp_audit_log(self._session, actor=actor, action=AuditAction.PROVISION_SUCCEED, tenant_id=tenant_id, request_id=request_id,
                                  payload={**status_change_payload(TenantStatus.PROVISIONING.value, tenant.status, before_version, tenant.version), "realm_created": realm.created})
            self._session.commit()
            view = TenantView.from_model(tenant)
        except Exception as exc:
            self._session.rollback()
            summary = summarize_error(step, exc)
            logger.warning("テナントの払い出しに失敗しました: tenant_id=%s %s", tenant_id, summary)
            self._record_failure(tenant_id, history_id, step, summary, actor, request_id, AuditAction.PROVISION_FAIL, failed_status=TenantStatus.FAILED)
            raise ProvisioningFailedError(tenant_id, step, summary) from exc

        logger.info("テナントを払い出しました（ACTIVE）: tenant_id=%s tenant_code=%s", tenant_id, view.tenant_code)
        return OnboardResult(tenant=view, history_id=history_id, initial_admin_username=username, temporary_password=temporary_password)

    def _record_failure(
        self,
        tenant_id: uuid.UUID,
        history_id: uuid.UUID,
        step: str,
        summary: str,
        actor: str,
        request_id: str | None,
        action: AuditAction,
        *,
        failed_status: TenantStatus | None,
    ) -> None:
        """失敗を払い出し履歴・監査ログ（と必要なら台帳の状態）にコミットする。

        記録自体が失敗した場合（DB 障害等）はログに残して握りつぶす（呼び出し側は元の失敗を送出する）。
        払い出しの場合、台帳は ``PROVISIONING`` のまま残り、定期ジョブ（``provisioning_reaper``）が ``FAILED`` にする。

        Args:
            tenant_id: テナント ID。
            history_id: 払い出し履歴の ID。
            step: 失敗したステップ名。
            summary: エラーの要約（:func:`summarize_error`）。
            actor: 操作者。
            request_id: リクエスト ID。
            action: 監査ログの操作。
            failed_status: 台帳を遷移させる状態（``None`` なら状態を変えない）。
        """
        try:
            payload: dict[str, Any] = {"step": step, "error": summary}
            if failed_status is not None:
                tenant = self._require_tenant(tenant_id, for_update=True)
                if tenant.status == TenantStatus.PROVISIONING:
                    before_version = tenant.version
                    tenant.status = failed_status.value
                    bump_version(tenant, actor)
                    payload.update(status_change_payload(TenantStatus.PROVISIONING.value, tenant.status, before_version, tenant.version))
            self._finish_history(history_id, RunStatus.FAILED, step, self._clock(), error=summary)
            repo.add_cp_audit_log(self._session, actor=actor, action=action, tenant_id=tenant_id, request_id=request_id, payload=payload)
            self._session.commit()
        except Exception:
            self._session.rollback()
            logger.exception("失敗の記録に失敗しました: tenant_id=%s", tenant_id)

    # ------------------------------------------------------------------ 停止・再開・削除要求
    def _switch_realm_and_status(
        self,
        tenant_id: uuid.UUID,
        operation: TenantOperation,
        action: AuditAction,
        *,
        realm_enabled: bool,
        actor: str,
        expected_version: int | None,
        request_id: str | None,
    ) -> TenantView:
        """行ロックの下でレルムの有効/無効を切り替え、成功したら状態を更新してコミットする。

        Args:
            tenant_id: テナント ID。
            operation: 操作（遷移元・遷移先は :data:`~control_plane_app.services.tenant_lifecycle.OPERATION_RULES`）。
            action: 監査ログの操作。
            realm_enabled: レルムを有効にするか。
            actor: 操作者。
            expected_version: 楽観ロックのバージョン。
            request_id: リクエスト ID。

        Returns:
            TenantView: 更新後のテナント。
        """
        actor = _validate_actor(actor)
        try:
            tenant = self._require_tenant(tenant_id, for_update=True)
            self._check_operation(tenant, operation)
            self._check_version(tenant, expected_version)
        except Exception:
            self._session.rollback()
            raise

        step = "enable_realm" if realm_enabled else "disable_realm"
        realm_skipped = False
        try:
            kc.set_realm_enabled(self._admin, tenant.realm_name, realm_enabled)
        except KeycloakAdminError as exc:
            if exc.status_code == 404 and not realm_enabled:
                # 無効化の対象が無い（FAILED でレルム作成前に失敗した等）。無効化と同じ結果なので続行する
                realm_skipped = True
                logger.info("レルムが存在しないため無効化を省略します: tenant_id=%s", tenant_id)
            else:
                self._session.rollback()
                summary = summarize_error(step, exc)
                logger.warning("レルムの切り替えに失敗しました（状態は変更しません）: tenant_id=%s operation=%s %s", tenant_id, operation, summary)
                raise TenantRealmOperationError(tenant_id, step, summary) from exc
        except Exception:
            self._session.rollback()
            raise

        before_status, before_version = tenant.status, tenant.version
        tenant.status = OPERATION_RULES[operation].target.value
        bump_version(tenant, actor)
        payload = status_change_payload(before_status, tenant.status, before_version, tenant.version)
        if operation == TenantOperation.REQUEST_DELETION:
            requested_at = self._clock()
            tenant.deletion_requested_at = requested_at
            payload["deletion_requested_at"] = requested_at.isoformat()
            payload["deletable_at"] = (requested_at + DELETION_GRACE_PERIOD).isoformat()
        if realm_skipped:
            payload["realm"] = "not_found"
        repo.add_cp_audit_log(self._session, actor=actor, action=action, tenant_id=tenant_id, request_id=request_id, payload=payload)
        self._session.commit()
        logger.info("テナントの状態を変更しました: tenant_id=%s %s -> %s", tenant_id, before_status, tenant.status)
        return TenantView.from_model(tenant)

    # ------------------------------------------------------------------ 共通の補助
    @contextmanager
    def _tenant_lock(self, tenant_code: str) -> Iterator[None]:
        """テナント単位のロックを取得し、ブロックの間保持する。

        Raises:
            TenantOperationInProgressError: 取得できなかった。
        """
        lock = self._lock or PgAdvisoryLock(engine_of(self._session))
        with lock.try_acquire(tenant_lock_key(tenant_code)) as acquired:
            if not acquired:
                self._session.rollback()
                raise TenantOperationInProgressError(tenant_code)
            yield

    def _app_data_repository(self) -> AppTenantDataRepository:
        """AP DB のテナントデータのリポジトリを返す（未指定なら既定の実装を作る）。"""
        if self._app_data is None:
            self._app_data = AppTenantDataRepository()
        return self._app_data

    def _require_tenant(self, tenant_id: uuid.UUID, *, for_update: bool = False) -> TTenant:
        """テナントを取得する。無ければ ``TenantNotFoundError``。"""
        tenant = repo.get_tenant(self._session, tenant_id, for_update=for_update)
        if tenant is None:
            self._session.rollback()
            raise TenantNotFoundError(tenant_id)
        return tenant

    def _check_operation(self, tenant: TTenant, operation: TenantOperation) -> None:
        """現在の状態で操作できるかを確認する。"""
        if not is_operation_allowed(operation, tenant.status):
            status = tenant.status
            self._session.rollback()
            raise InvalidTenantTransitionError(tenant.id, operation.value, status)

    def _check_version(self, tenant: TTenant, expected_version: int | None) -> None:
        """楽観ロックのバージョンを確認する（``None`` なら確認しない）。"""
        if expected_version is not None and tenant.version != expected_version:
            actual = tenant.version
            self._session.rollback()
            raise TenantVersionConflictError(tenant.id, expected_version, actual)

    def _set_history_step(self, history_id: uuid.UUID, step: str) -> None:
        """払い出し履歴の実行中ステップを更新してコミットする（CP-ONB-08: 各ステップの結果を都度コミット）。"""
        history = self._session.get(TProvisioningHistory, history_id)
        if history is not None:
            history.step = step
            self._session.commit()

    def _finish_history(self, history_id: uuid.UUID, status: RunStatus, step: str, finished_at: dt.datetime, *, error: str | None = None) -> None:
        """払い出し履歴を終了状態にする（コミットは呼び出し側）。"""
        history = self._session.get(TProvisioningHistory, history_id)
        if history is None:
            return
        history.status = status.value
        history.step = step
        history.finished_at = finished_at
        history.error = error


