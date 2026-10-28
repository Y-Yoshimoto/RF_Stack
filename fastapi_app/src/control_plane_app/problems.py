#!/usr/bin/env python
# coding:utf-8
"""テナントのライフサイクル操作の例外を Problem Details に変換する（CP）。

``control_plane_app.services.errors`` の例外と ``code``・HTTP ステータスの対応（03 §2）をここで文言にする。
サービス層は FastAPI に依存しないため、変換は API 層のここに置く。``app.py`` から
:func:`register_cp_exception_handlers` を 1 回呼んで登録する。

| 例外 | ステータス | ``code`` |
| --- | --- | --- |
| ``TenantValidationError`` / ``InvalidTenantCodeError`` | 422 | ``invalid_tenant_input`` / ``invalid_tenant_code``（``errors`` に項目） |
| ``TenantNotFoundError`` | 404 | ``tenant_not_found`` |
| ``TenantCodeAlreadyExistsError`` | 409 | ``tenant_code_already_exists`` |
| ``InvalidTenantTransitionError`` | 409 | ``invalid_tenant_transition``（拡張メンバー ``operation`` / ``current_status``） |
| ``TenantOperationInProgressError`` | 409 | ``tenant_operation_in_progress`` |
| ``TenantVersionConflictError`` | 412 | ``tenant_version_conflict`` |
| ``TenantExternalOperationError`` | 502 | ``tenant_provisioning_failed`` 等（拡張メンバー ``tenant_id`` / ``step``） |

メッセージ・拡張メンバーに、一時パスワード・シークレット・Keycloak の応答本文は含めない
（サービスの例外が持たないため含まれない）。
"""
from fastapi import FastAPI

from control_plane_app.services.errors import (
    DeletionGracePeriodNotElapsedError,
    InvalidTenantTransitionError,
    TenantCodeAlreadyExistsError,
    TenantExternalOperationError,
    TenantNotFoundError,
    TenantOperationInProgressError,
    TenantServiceError,
    TenantValidationError,
    TenantVersionConflictError,
)
from modules.errors.catalog import ProblemText, text_for_code
from modules.errors.handlers import problem_exception_handler, problem_from_text
from modules.errors.problem import FieldError, ProblemError

# エラーコード → 文言（title / detail）。ステータスはサービス例外の種類で決める。
_TEXTS: dict[str, ProblemText] = {
    "invalid_tenant_input": ProblemText("入力内容が不正です", "入力内容を確認してください"),
    "invalid_tenant_code": ProblemText("テナントコードが不正です", "テナントコードは英小文字・数字・ハイフンの 3〜32 文字で、予約語は使用できません"),
    "tenant_not_found": ProblemText("テナントが見つかりません", "指定されたテナントは存在しません"),
    "tenant_code_already_exists": ProblemText("テナントコードが既に使われています", "このテナントコードは使用済みです。削除済みのテナントのコードも再利用できません"),
    "invalid_tenant_transition": ProblemText("現在の状態ではこの操作を行えません", "テナントの状態を確認してください"),
    "deletion_grace_period_not_elapsed": ProblemText("削除の猶予期間が経過していません", "猶予期間の経過後に物理削除されます"),
    "tenant_operation_in_progress": ProblemText("別の操作が実行中です", "同じテナントに対する別の操作が実行中です。完了してからやり直してください"),
    "tenant_version_conflict": ProblemText("テナントが他の操作により更新されています", "最新の状態を取得して、やり直してください"),
    "tenant_provisioning_failed": ProblemText("テナントの払い出しに失敗しました", "払い出しの途中で失敗しました。テナントは失敗状態として記録されています。再実行してください"),
    "tenant_realm_operation_failed": ProblemText("認証領域の操作に失敗しました", "認証サーバーでの処理に失敗したため、テナントの状態は変更していません。時間をおいてやり直してください"),
    "tenant_deprovisioning_failed": ProblemText("テナントの削除処理に失敗しました", "削除処理に失敗しました。次回の定期ジョブで再試行されます"),
    "tenant_external_operation_failed": ProblemText("外部サービスの操作に失敗しました", "外部サービスの操作に失敗しました。時間をおいてやり直してください"),
    "tenant_service_error": ProblemText("サーバーでエラーが発生しました", "時間をおいて、もう一度お試しください。解消しない場合は管理者にお問い合わせください"),
}


def tenant_service_error_to_problem(exc: TenantServiceError) -> ProblemError:
    """テナントのライフサイクル操作の例外を :class:`ProblemError` に変換する。

    Args:
        exc: ``control_plane_app.services.errors`` の例外。

    Returns:
        ProblemError: Problem Details の元になるエラー。
    """
    code = exc.code
    text = _TEXTS.get(code) or text_for_code("internal_error", 500)

    if isinstance(exc, TenantValidationError):
        error = FieldError(field=exc.field, code=exc.reason, message=_validation_message(exc.reason))
        return problem_from_text(422, code, text, errors=[error])
    if isinstance(exc, TenantNotFoundError):
        return problem_from_text(404, code, text)
    if isinstance(exc, TenantCodeAlreadyExistsError):
        return problem_from_text(409, code, text, errors=[FieldError(field="tenant_code", code="already_exists", message="このテナントコードは使用できません")])
    if isinstance(exc, InvalidTenantTransitionError):
        extensions: dict[str, object] = {"operation": exc.operation, "current_status": exc.current_status}
        if isinstance(exc, DeletionGracePeriodNotElapsedError):
            extensions["deletable_at"] = exc.deletable_at.isoformat() if hasattr(exc.deletable_at, "isoformat") else None
        return problem_from_text(409, code, text, extensions=extensions)
    if isinstance(exc, TenantOperationInProgressError):
        return problem_from_text(409, code, text)
    if isinstance(exc, TenantVersionConflictError):
        return problem_from_text(412, code, text)
    if isinstance(exc, TenantExternalOperationError):
        return problem_from_text(502, code, text, extensions={"tenant_id": str(exc.tenant_id), "step": exc.step})
    return problem_from_text(500, "internal_error", text_for_code("internal_error", 500))


def _validation_message(reason: str) -> str:
    """入力検証の理由（``required`` / ``too_long`` / ``format`` / ``reserved`` 等）を日本語のメッセージにする。"""
    messages = {
        "required": "必須項目です",
        "too_long": "長すぎます",
        "too_short": "短すぎます",
        "format": "形式が正しくありません",
        "reserved": "予約語のため使用できません",
    }
    return messages.get(reason, "値が正しくありません")


def register_cp_exception_handlers(app: FastAPI) -> None:
    """CP の例外ハンドラを登録する。

    Args:
        app: FastAPI アプリ。
    """
    app.add_exception_handler(TenantServiceError, problem_exception_handler(tenant_service_error_to_problem))
