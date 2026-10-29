#!/usr/bin/env python
# coding:utf-8
"""AP のユーザー・組織管理・ToDo の例外を Problem Details に変換する。

``main_app.services.errors`` の例外と ``code``・HTTP ステータスの対応(03 §2)をここで文言にする。
サービス層は FastAPI に依存しないため、変換は API 層のここに置く。``app.py`` から
:func:`register_ap_exception_handlers` を 1 回呼んで登録する(CP は ``control_plane_app/problems.py``)。

| 例外 | ステータス | ``code`` |
| --- | --- | --- |
| ``UserValidationError`` / ``InvalidUserRoleError`` | 422 | ``invalid_user_input`` / ``invalid_user_role``(``errors`` に項目) |
| ``OrganizationValidationError`` / ``InvalidOrganizationMembersError`` | 422 | ``invalid_organization_input`` / ``invalid_organization_members``(``errors`` に項目。後者は拡張メンバー ``user_ids``) |
| ``UserNotFoundError`` / ``OrganizationNotFoundError`` | 404 | ``user_not_found`` / ``organization_not_found``(他テナント・存在しない・削除済みを区別しない) |
| ``UserAlreadyExistsError`` / ``OrganizationNameConflictError`` | 409 | ``user_already_exists`` / ``organization_name_already_exists`` |
| ``UserSelfModificationError`` | 409 | ``user_self_modification_forbidden``(拡張メンバー ``operation``) |
| ``UserVersionConflictError`` / ``OrganizationVersionConflictError`` | 412 | ``user_version_conflict`` / ``organization_version_conflict`` |
| ``TodoValidationError`` | 422 | ``invalid_todo_input``(``errors`` に項目) |
| ``InvalidTodoAssigneesError`` | 422 | ``invalid_todo_assignees``(``errors`` の ``code`` は ``not_found`` / ``inactive``。拡張メンバー ``user_ids``) |
| ``InvalidTodoOrganizationsError`` | 422 | ``invalid_todo_organizations``(拡張メンバー ``organization_ids``) |
| ``TodoNotFoundError`` | 404 | ``todo_not_found``(他テナント・存在しない・削除済み・閲覧範囲外を区別しない) |
| ``TodoCommentNotFoundError`` / ``TodoChecklistItemNotFoundError`` | 404 | ``todo_comment_not_found`` / ``todo_checklist_item_not_found``(別の ToDo のもの・削除済みを区別しない。ToDo を閲覧できなければ先に ``todo_not_found``) |
| ``TodoPermissionDeniedError`` | 403 | ``todo_operation_forbidden``(拡張メンバー ``operation``。コメント・チェックリストは ``edit_comment`` / ``delete_comment`` / ``edit_checklist`` / ``check_checklist_item``) |
| ``TodoVersionConflictError`` / ``TodoCommentVersionConflictError`` | 412 | ``todo_version_conflict`` / ``todo_comment_version_conflict`` |
| ``TodoChecklistVersionConflictError`` | 412 | ``todo_checklist_version_conflict``(拡張メンバー ``target``: ``item`` = 項目の版 / ``checklist`` = チェックリスト全体の版) |
| ``IdentityProviderOperationError`` | 502 | ``identity_provider_operation_failed`` |
| ``UserDeactivatedError`` / ``UserNotSyncedError`` | 401 | ``user_deactivated`` / ``user_not_synced``(セッションの破棄は ``route/v1/deps.py``) |

メッセージ・拡張メンバーに、一時パスワード・トークン・Keycloak の応答本文は含めない(サービスの例外が持たない。
``IdentityProviderOperationError.error_summary`` もレスポンスには含めずログにだけ残す)。
"""
from typing import Any

from fastapi import FastAPI

from main_app.services.errors import (
    AppServiceError,
    AppValidationError,
    IdentityProviderOperationError,
    InvalidOrganizationMembersError,
    InvalidTodoAssigneesError,
    InvalidTodoOrganizationsError,
    OrganizationNameConflictError,
    OrganizationNotFoundError,
    OrganizationVersionConflictError,
    TodoChecklistItemNotFoundError,
    TodoChecklistVersionConflictError,
    TodoCommentNotFoundError,
    TodoCommentVersionConflictError,
    TodoNotFoundError,
    TodoPermissionDeniedError,
    TodoVersionConflictError,
    UserAlreadyExistsError,
    UserDeactivatedError,
    UserNotFoundError,
    UserNotSyncedError,
    UserSelfModificationError,
    UserVersionConflictError,
)
from modules.errors.catalog import ProblemText, text_for_code
from modules.errors.handlers import problem_exception_handler, problem_from_text
from modules.errors.problem import FieldError, ProblemError

# エラーコード → 文言(title / detail)。ステータスはサービス例外の種類で決める。
_TEXTS: dict[str, ProblemText] = {
    "invalid_user_input": ProblemText("ユーザーの入力内容が不正です", "入力内容を確認してください"),
    "invalid_user_role": ProblemText("付与できないロールです", "付与できるロールは tenant_admin と member です"),
    "invalid_organization_input": ProblemText("組織の入力内容が不正です", "入力内容を確認してください"),
    "invalid_organization_members": ProblemText("メンバーに指定できないユーザーが含まれています", "テナント内に存在しないユーザーは指定できません"),
    "user_not_found": ProblemText("ユーザーが見つかりません", "指定されたユーザーは存在しないか、閲覧権限がありません"),
    "organization_not_found": ProblemText("組織が見つかりません", "指定された組織は存在しないか、閲覧権限がありません"),
    "user_already_exists": ProblemText("ユーザーが既に存在します", "同じユーザー名またはメールアドレスのユーザーが既にいます"),
    "organization_name_already_exists": ProblemText("組織名が既に使われています", "同じ名前の組織が既にあります。別の名前を指定してください"),
    "user_self_modification_forbidden": ProblemText("自分自身には行えない操作です", "自分自身の無効化と、自分の管理者ロールの解除はできません。ほかの管理者に依頼してください"),
    "user_version_conflict": ProblemText("ユーザーが他の操作により更新されています", "最新の状態を取得して、やり直してください"),
    "organization_version_conflict": ProblemText("組織が他の操作により更新されています", "最新の状態を取得して、やり直してください"),
    "invalid_todo_input": ProblemText("ToDo の入力内容が不正です", "入力内容を確認してください"),
    "invalid_todo_assignees": ProblemText("担当者に指定できないユーザーが含まれています", "テナント内に存在しないユーザー、無効化されたユーザーは新たに担当者にできません"),
    "invalid_todo_organizations": ProblemText("公開先に指定できない組織が含まれています", "テナント内に存在しない組織、削除された組織は新たに公開先にできません"),
    "todo_not_found": ProblemText("ToDo が見つかりません", "指定された ToDo は存在しないか、閲覧権限がありません"),
    "todo_comment_not_found": ProblemText("コメントが見つかりません", "指定されたコメントは存在しないか、削除されています"),
    "todo_checklist_item_not_found": ProblemText("チェックリストの項目が見つかりません", "指定された項目は存在しないか、削除されています"),
    "todo_operation_forbidden": ProblemText("この操作は許可されていません", "この ToDo に対する操作の権限がありません。作成者または管理者に依頼してください"),
    "todo_version_conflict": ProblemText("ToDo が他の操作により更新されています", "最新の状態を取得して、やり直してください"),
    "todo_comment_version_conflict": ProblemText("コメントが他の操作により更新されています", "最新の状態を取得して、やり直してください"),
    "todo_checklist_version_conflict": ProblemText("チェックリストが他の操作により更新されています", "最新の状態を取得して、やり直してください"),
    "identity_provider_operation_failed": ProblemText("認証サーバーでの処理に失敗しました", "認証サーバーでの処理に失敗したため、変更していません。時間をおいて、もう一度お試しください"),
    "user_deactivated": ProblemText("このユーザーは無効化されています", "ユーザーが無効化されたため、ログアウトしました。管理者にお問い合わせください"),
    "user_not_synced": ProblemText("もう一度ログインしてください", "ユーザー情報を確認できませんでした。もう一度ログインしてください"),
    "app_service_error": ProblemText("サーバーでエラーが発生しました", "時間をおいて、もう一度お試しください。解消しない場合は管理者にお問い合わせください"),
}

# 入力検証の理由(``AppValidationError.reason``)→ メッセージ
_VALIDATION_MESSAGES: dict[str, str] = {
    "required": "必須項目です",
    "too_long": "長すぎます",
    "too_short": "短すぎます",
    "too_many": "件数が多すぎます",
    "mismatch": "現在の項目と一致しません。最新の状態を取得して、やり直してください",
    "out_of_range": "指定できる範囲を超えています",
    "format": "形式が正しくありません",
    "type": "型が正しくありません",
    "unsupported": "指定できない値です",
    "not_allowed": "指定できない値が含まれています",
    "not_found": "存在しないユーザーが含まれています",
    "inactive": "無効化されたユーザーは新たに割り当てられません",
}
# 理由が同じでも対象で文言が変わるもの(例外の型 → 理由 → メッセージ)。ここに無ければ ``_VALIDATION_MESSAGES``
_VALIDATION_MESSAGES_BY_TYPE: dict[type[AppValidationError], dict[str, str]] = {
    InvalidTodoOrganizationsError: {"not_found": "存在しない、または削除された組織が含まれています"},
}


def _validation_message(exc: AppValidationError) -> str:
    """入力検証の理由をメッセージにする(対象で文言が変わる例外は型ごとの表を優先する)。"""
    for exc_type, messages in _VALIDATION_MESSAGES_BY_TYPE.items():
        if isinstance(exc, exc_type) and exc.reason in messages:
            return messages[exc.reason]
    return _VALIDATION_MESSAGES.get(exc.reason, "値が正しくありません")


def app_service_error_to_problem(exc: AppServiceError) -> ProblemError:
    """AP のユーザー・組織管理の例外を :class:`ProblemError` に変換する。

    Args:
        exc: ``main_app.services.errors`` の例外。

    Returns:
        ProblemError: Problem Details の元になるエラー。
    """
    code = exc.code
    text = _TEXTS.get(code) or text_for_code("internal_error", 500)

    if isinstance(exc, AppValidationError):
        error = FieldError(field=exc.field, code=exc.reason, message=_validation_message(exc))
        extensions: dict[str, Any] | None = None
        if isinstance(exc, InvalidOrganizationMembersError | InvalidTodoAssigneesError):
            extensions = {"user_ids": [str(user_id) for user_id in exc.user_ids]}
        elif isinstance(exc, InvalidTodoOrganizationsError):
            extensions = {"organization_ids": [str(organization_id) for organization_id in exc.organization_ids]}
        return problem_from_text(422, code, text, errors=[error], extensions=extensions)
    if isinstance(exc, UserNotFoundError | OrganizationNotFoundError | TodoNotFoundError | TodoCommentNotFoundError | TodoChecklistItemNotFoundError):
        return problem_from_text(404, code, text)
    if isinstance(exc, TodoPermissionDeniedError):
        return problem_from_text(403, code, text, extensions={"operation": exc.operation})
    if isinstance(exc, UserAlreadyExistsError | OrganizationNameConflictError):
        return problem_from_text(409, code, text)
    if isinstance(exc, UserSelfModificationError):
        return problem_from_text(409, code, text, extensions={"operation": exc.operation})
    if isinstance(exc, TodoChecklistVersionConflictError):
        return problem_from_text(412, code, text, extensions={"target": exc.target})
    if isinstance(exc, UserVersionConflictError | TodoCommentVersionConflictError | OrganizationVersionConflictError | TodoVersionConflictError):
        return problem_from_text(412, code, text)
    if isinstance(exc, IdentityProviderOperationError):
        return problem_from_text(502, code, text)
    if isinstance(exc, UserDeactivatedError | UserNotSyncedError):
        return problem_from_text(401, code, text)
    return problem_from_text(500, "internal_error", text_for_code("internal_error", 500))


def register_ap_exception_handlers(app: FastAPI) -> None:
    """AP の例外ハンドラを登録する。

    Args:
        app: FastAPI アプリ。
    """
    app.add_exception_handler(AppServiceError, problem_exception_handler(app_service_error_to_problem))
