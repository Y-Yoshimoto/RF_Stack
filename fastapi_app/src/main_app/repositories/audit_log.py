#!/usr/bin/env python
# coding:utf-8
"""AP 監査ログ（``t_ap_audit_log``。03 §7）の追記。

業務データの変更と**同じトランザクション**で書く（コミットは呼び出し側）。``app_runtime`` は UPDATE / DELETE を
剥奪されており、追記しかできない。``payload`` に秘匿値（パスワード・一時パスワード・トークン等）を含めないこと。
"""
import uuid
from typing import Any

from sqlmodel import Session

from main_app.models import TApAuditLog


def add_ap_audit_log(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str | None,
    target_id: uuid.UUID | str | None,
    payload: dict[str, Any] | None,
    request_id: str | None,
) -> TApAuditLog:
    """AP 監査ログを 1 行追加する（flush はしない）。

    Args:
        session: AP のセッション。
        tenant_id: テナント ID（コンテキストの値）。
        actor_id: 操作者のユーザー ID（システム処理は ``None``）。
        action: 操作（``resource.verb``。例: ``user.create``）。
        target_type: 対象の種別（``user`` / ``organization``）。
        target_id: 対象の ID。
        payload: 変更前後の差分など（秘匿値を含めない）。
        request_id: リクエスト ID。

    Returns:
        TApAuditLog: 追加した行。
    """
    row = TApAuditLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        payload=payload,
        request_id=request_id,
    )
    session.add(row)
    return row
