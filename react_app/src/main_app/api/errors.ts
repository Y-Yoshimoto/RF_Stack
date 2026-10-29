// アプリケーションプレーン (AP) の API エラーの分類 (02 §6.2)
// - classifyAppApiError: 認証状態への反映 (画面遷移) 用。AppAuthProvider の reportApiError が使う
// - classifyAppError: 画面の分岐用 (kind / code / requires_reload)。フック (main_app/users・organizations・me・todos) が使う
import { ApiGuardError, classifyApiError, type ApiErrorInfo, type ApiErrorKind, type ApiErrorRules } from '@/shared/api/errors';
import { ApiError, PROBLEM_CODE, problemCodeOf } from '@/utils/libs/FetchComponents/problem';
import { APP_PROBLEM_CODE } from './contract';

/**
 * AP の API エラーのうち、画面遷移が必要なもの。
 */
export type AppApiErrorEffect = 'unauthenticated' | 'tenant_suspended' | 'tenant_unavailable';

/**
 * AP の API エラーを分類する関数
 * @param {unknown} error catch した値
 * @returns {AppApiErrorEffect | null} 画面遷移が必要な場合はその種類、不要なら null (呼び出し元で扱う)
*/
export const classifyAppApiError = (error: unknown): AppApiErrorEffect | null => {
    if (!(error instanceof ApiError)) return null;
    if (error.status === 401) return 'unauthenticated';
    if (error.status !== 403) return null;
    const code = problemCodeOf(error);
    if (code === PROBLEM_CODE.TENANT_INACTIVE) return 'tenant_suspended';
    if (code === PROBLEM_CODE.TENANT_UNAVAILABLE) return 'tenant_unavailable';
    // 権限不足 (forbidden)・CSRF 検証失敗などは操作単位のエラーとして呼び出し元で扱う
    return null;
};

// 画面の分岐用の分類 (CP の classifyCpError と同じ形。本体は shared/api/errors.ts) ///////////////

/**
 * AP の API エラーの種類 (shared/api/errors.ts の ApiErrorKind)。
 * - unauthenticated: 401 (user_deactivated / session_expired を含む。クライアントが認証状態を取り直し、ログイン画面へ遷移する)
 * - forbidden: 403、または member が変更操作を呼んだ (API を呼ばずに弾いたものを含む)
 * - conflict: 409 (重複・自分自身への禁止操作。API を呼ばずに弾いた自分自身への操作も code は user_self_modification_forbidden)
 * - external_failure: 502 identity_provider_operation_failed (AP の DB は変更していない)
 */
export type AppErrorKind = ApiErrorKind;

/**
 * 分類したエラー。
 */
export type AppErrorInfo = ApiErrorInfo;

/**
 * フックが API を呼ぶ前に弾いた理由。
 * - write_not_allowed: tenant_admin でない (forbidden)
 * - missing_etag: If-Match に使う ETag が無い (precondition_required。再取得を促す)
 * - action_in_progress: 同じフックで別の操作を実行中 (busy)
 * - self_deactivate / self_remove_tenant_admin: 自分自身の無効化・自分の tenant_admin の解除 (conflict、code: user_self_modification_forbidden)
 * - empty_changes: 更新する項目が無い (invalid_input)
 * - todo_operation_not_permitted: ToDo の permissions で不可の操作 (forbidden、code: todo_operation_forbidden。操作は TodoGuardError.operation)
 * - todo_organizations_required: 閲覧範囲 organization で公開先組織が無い (invalid_input、code: invalid_todo_input。AP-VIS-07)
 * - todo_too_many_assignees: 担当者が上限 (20 人) を超える (invalid_input。AP-ASN-01)
 */
export type AppGuardReason =
    | 'write_not_allowed'
    | 'missing_etag'
    | 'action_in_progress'
    | 'self_deactivate'
    | 'self_remove_tenant_admin'
    | 'empty_changes'
    | 'todo_operation_not_permitted'
    | 'todo_organizations_required'
    | 'todo_too_many_assignees';

const GUARD_INFO: Record<AppGuardReason, { kind: ApiErrorKind; code?: string; requires_reload?: boolean }> = {
    write_not_allowed: { kind: 'forbidden' },
    missing_etag: { kind: 'precondition_required', requires_reload: true },
    action_in_progress: { kind: 'busy' },
    self_deactivate: { kind: 'conflict', code: APP_PROBLEM_CODE.USER_SELF_MODIFICATION_FORBIDDEN },
    self_remove_tenant_admin: { kind: 'conflict', code: APP_PROBLEM_CODE.USER_SELF_MODIFICATION_FORBIDDEN },
    empty_changes: { kind: 'invalid_input' },
    todo_operation_not_permitted: { kind: 'forbidden', code: APP_PROBLEM_CODE.TODO_OPERATION_FORBIDDEN },
    todo_organizations_required: { kind: 'invalid_input', code: APP_PROBLEM_CODE.INVALID_TODO_INPUT },
    todo_too_many_assignees: { kind: 'invalid_input' },
};

/**
 * フックが API を呼ぶ前に弾いたことを表す例外。
 */
export class AppGuardError extends ApiGuardError {
    declare readonly reason: AppGuardReason;

    constructor(reason: AppGuardReason) {
        super(reason, GUARD_INFO[reason], `AP の操作を実行できません: ${reason}`);
        this.name = 'AppGuardError';
    }
}

/**
 * AP 固有の、再取得してからやり直すべき code。
 * API の 403 todo_operation_forbidden は、保持している permissions が古い (担当から外れた等) ことを表すため取り直させる
 * (API を呼ばずに弾いた場合は保持している permissions どおりなので取り直さない)。
 */
const APP_ERROR_RULES: ApiErrorRules = {
    reload_codes: [
        APP_PROBLEM_CODE.USER_VERSION_CONFLICT,
        APP_PROBLEM_CODE.ORGANIZATION_VERSION_CONFLICT,
        APP_PROBLEM_CODE.TODO_VERSION_CONFLICT,
        APP_PROBLEM_CODE.TODO_OPERATION_FORBIDDEN,
    ],
};

/**
 * AP の API エラーを画面の分岐用に分類する関数
 * @param {unknown} error catch した値
 * @returns {AppErrorInfo} 分類
*/
export const classifyAppError = (error: unknown): AppErrorInfo => classifyApiError(error, APP_ERROR_RULES);
