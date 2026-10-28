#!/usr/bin/env python
# coding:utf-8
"""CP DB（``cp_runtime``）のテナント台帳・払い出し履歴・CP 監査ログへのアクセス。

トランザクションの境界（コミット・ロールバック）は呼び出し側（サービス層）が決める。
本モジュールの関数はコミットしない。
"""
import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlmodel import Session, col, select

from control_plane_app.models.sql_models import ProvisioningType, RunStatus, TCpAuditLog, TProvisioningHistory, TTenant

# CP 監査ログの target_type（テナント）
AUDIT_TARGET_TENANT = "tenant"


def get_tenant(session: Session, tenant_id: uuid.UUID, *, for_update: bool = False) -> TTenant | None:
    """テナントを ID で取得する。

    Args:
        session: CP DB のセッション。
        tenant_id: テナント ID。
        for_update: ``SELECT ... FOR UPDATE`` で行ロックを取るか。

    Returns:
        TTenant | None: テナント。無ければ ``None``。
    """
    statement = select(TTenant).where(TTenant.id == tenant_id)
    if for_update:
        statement = statement.with_for_update()
    return session.exec(statement).first()


def get_tenant_by_code(session: Session, tenant_code: str, *, for_update: bool = False) -> TTenant | None:
    """テナントをテナントコードで取得する（削除済みを含む）。

    Args:
        session: CP DB のセッション。
        tenant_code: テナントコード。
        for_update: ``SELECT ... FOR UPDATE`` で行ロックを取るか。

    Returns:
        TTenant | None: テナント。無ければ ``None``。
    """
    statement = select(TTenant).where(TTenant.tenant_code == tenant_code)
    if for_update:
        statement = statement.with_for_update()
    return session.exec(statement).first()


def tenant_code_or_realm_exists(session: Session, tenant_code: str, realm_name: str) -> bool:
    """テナントコードまたはレルム名が既に使われているかを返す（削除済みを含む。01 CP-OPS-09）。

    Args:
        session: CP DB のセッション。
        tenant_code: テナントコード。
        realm_name: レルム名。

    Returns:
        bool: 使われていれば ``True``。
    """
    statement = select(TTenant.id).where((TTenant.tenant_code == tenant_code) | (TTenant.realm_name == realm_name))
    return session.exec(statement).first() is not None


def list_tenants_by_status_updated_before(session: Session, status: str, before: dt.datetime) -> list[TTenant]:
    """指定の状態のまま ``updated_at`` が ``before`` より前のテナントを返す（中断した払い出しの回収用）。

    Args:
        session: CP DB のセッション。
        status: 状態。
        before: この日時より前に更新されたもの。

    Returns:
        list[TTenant]: 該当テナント（``updated_at`` の昇順）。
    """
    statement = select(TTenant).where(TTenant.status == status, col(TTenant.updated_at) < before).order_by(col(TTenant.updated_at))
    return list(session.exec(statement).all())


def list_tenants_for_deprovisioning(session: Session, pending_status: str, deprovisioning_status: str, requested_before: dt.datetime) -> list[TTenant]:
    """物理削除の対象（猶予期間を過ぎた削除要求中、または前回失敗した削除中）を返す。

    Args:
        session: CP DB のセッション。
        pending_status: 削除要求中の状態（``PENDING_DELETION``）。
        deprovisioning_status: 削除中の状態（``DEPROVISIONING``）。
        requested_before: 削除要求日時がこれより前のものを対象にする（= 現在 - 猶予期間）。

    Returns:
        list[TTenant]: 対象テナント（削除要求日時の昇順）。
    """
    statement = (
        select(TTenant)
        .where(
            (TTenant.status == deprovisioning_status)
            | ((TTenant.status == pending_status) & (col(TTenant.deletion_requested_at) <= requested_before))
        )
        .order_by(col(TTenant.deletion_requested_at), col(TTenant.id))
    )
    return list(session.exec(statement).all())


def add_provisioning_history(session: Session, tenant_id: uuid.UUID, provisioning_type: ProvisioningType, step: str, started_at: dt.datetime) -> TProvisioningHistory:
    """払い出し履歴を ``RUNNING`` で追加する。

    Args:
        session: CP DB のセッション。
        tenant_id: テナント ID。
        provisioning_type: 種別。
        step: 最初のステップ名。
        started_at: 開始日時。

    Returns:
        TProvisioningHistory: 追加した履歴（未コミット）。
    """
    history = TProvisioningHistory(tenant_id=tenant_id, type=provisioning_type.value, status=RunStatus.RUNNING.value, step=step, started_at=started_at)
    session.add(history)
    return history


def list_running_histories(session: Session, tenant_id: uuid.UUID, provisioning_type: ProvisioningType) -> Sequence[TProvisioningHistory]:
    """``RUNNING`` のまま残っている払い出し履歴を返す。

    Args:
        session: CP DB のセッション。
        tenant_id: テナント ID。
        provisioning_type: 種別。

    Returns:
        Sequence[TProvisioningHistory]: 該当する履歴。
    """
    statement = select(TProvisioningHistory).where(
        TProvisioningHistory.tenant_id == tenant_id,
        TProvisioningHistory.type == provisioning_type.value,
        TProvisioningHistory.status == RunStatus.RUNNING.value,
    )
    return session.exec(statement).all()


def close_running_histories(session: Session, tenant_id: uuid.UUID, provisioning_type: ProvisioningType, error: str, finished_at: dt.datetime) -> int:
    """``RUNNING`` のまま残った払い出し履歴（プロセス停止等で中断したもの）を ``FAILED`` にする。

    Args:
        session: CP DB のセッション。
        tenant_id: テナント ID。
        provisioning_type: 種別。
        error: エラー種別（秘匿値を含めない短い語。例: ``interrupted``）。
        finished_at: 終了日時として記録する日時。

    Returns:
        int: 閉じた履歴の件数。
    """
    histories = list_running_histories(session, tenant_id, provisioning_type)
    for history in histories:
        history.status = RunStatus.FAILED.value
        history.finished_at = finished_at
        history.error = f"step={history.step}; error={error}"
    return len(histories)


def list_provisioning_histories(session: Session, tenant_id: uuid.UUID) -> Sequence[TProvisioningHistory]:
    """テナントの払い出し履歴を新しい順に返す（テナント詳細画面用。01 CP-OPS-02）。

    Args:
        session: CP DB のセッション。
        tenant_id: テナント ID。

    Returns:
        Sequence[TProvisioningHistory]: 履歴。
    """
    statement = select(TProvisioningHistory).where(TProvisioningHistory.tenant_id == tenant_id).order_by(col(TProvisioningHistory.started_at).desc(), col(TProvisioningHistory.id).desc())
    return session.exec(statement).all()


def add_cp_audit_log(
    session: Session,
    *,
    actor: str,
    action: str,
    tenant_id: uuid.UUID | None,
    payload: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> TCpAuditLog:
    """CP 監査ログを追加する（03 §7）。業務データの変更と同じトランザクションで呼ぶこと。

    ``payload`` に一時パスワード・シークレット・個人情報を含めないこと。

    Args:
        session: CP DB のセッション。
        actor: 操作者（CP 管理者の IdP subject または ``system``）。
        action: 操作（``resource.verb``。例: ``tenant.suspend``）。
        tenant_id: 対象テナント ID。
        payload: 変更前後の差分など。
        request_id: リクエスト ID。

    Returns:
        TCpAuditLog: 追加したログ（未コミット）。
    """
    log = TCpAuditLog(
        actor=actor,
        action=action,
        target_tenant_id=tenant_id,
        target_type=AUDIT_TARGET_TENANT,
        target_id=str(tenant_id) if tenant_id is not None else None,
        payload=dict(payload) if payload is not None else None,
        request_id=request_id,
    )
    session.add(log)
    return log
