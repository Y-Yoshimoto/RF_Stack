// CP の API エラーの分類 (画面の分岐用)
// 元のエラー (ApiError) と Problem Details の code は失わずに保持し、画面はまず kind で、必要なら code で分岐する。
// 401 はクライアント (useCpApiClient) が認証状態に反映し、ルートガードがログイン画面へ遷移させる。
import { ApiError, PROBLEM_CODE, problemCodeOf, problemOf, type ProblemDetails } from '@/utils/libs/FetchComponents/problem';
import { CP_FIELD_ERROR_CODE, CP_PROBLEM_CODE } from './contract';

/**
 * CP の API エラーの種類。
 * - unauthenticated: 401 (ログイン画面へ遷移する。画面での表示は不要)
 * - forbidden: 403、または saas_viewer が変更操作を呼んだ (API を呼ばずに弾いたものを含む)
 * - not_found: 404
 * - version_conflict: 412 (他の操作で更新済み。最新を再取得してやり直す)
 * - precondition_required: 428 / 400 invalid_if_match、または ETag 未取得 (再取得してやり直す)
 * - conflict: 409 (テナントコードの重複・状態遷移の不正・実行中の操作など。code で分岐する)
 * - invalid_input: 422 (errors に項目ごとの詳細) / 400
 * - external_failure: 502 / 504 (払い出しの失敗など。problem の tenant_id / step を参照できる)
 * - unavailable: 503
 * - busy: 同じフックで別の操作を実行中 (API を呼んでいない)
 * - unknown: 上記以外 (500・ネットワークエラーなど)
 */
export type CpErrorKind =
    | 'unauthenticated'
    | 'forbidden'
    | 'not_found'
    | 'version_conflict'
    | 'precondition_required'
    | 'conflict'
    | 'invalid_input'
    | 'external_failure'
    | 'unavailable'
    | 'busy'
    | 'unknown';

/**
 * 分類したエラー。
 */
export type CpErrorInfo = {
    kind: CpErrorKind;
    /** HTTP ステータス (API を呼んでいない・ネットワークエラーでは null)。 */
    status: number | null;
    /** Problem Details の code (無ければ null)。 */
    code: string | null;
    /** Problem Details (拡張メンバー tenant_id / step / operation / current_status 等を含む)。 */
    problem: ProblemDetails | null;
    /** 画面の表示が古い可能性が高く、最新を再取得してからやり直すべき。 */
    requires_reload: boolean;
    /** 元のエラー (ApiError 等)。 */
    error: unknown;
};

/**
 * フックが API を呼ぶ前に弾いた理由。
 */
export type CpGuardReason = 'write_not_allowed' | 'missing_etag' | 'action_in_progress';

/**
 * フックが API を呼ぶ前に弾いたことを表す例外 (saas_viewer の変更操作・ETag 未取得・二重実行)。
 */
export class CpGuardError extends Error {
    readonly reason: CpGuardReason;

    constructor(reason: CpGuardReason) {
        super(`CP の操作を実行できません: ${reason}`);
        this.name = 'CpGuardError';
        this.reason = reason;
    }
}

const GUARD_KIND: Record<CpGuardReason, CpErrorKind> = {
    write_not_allowed: 'forbidden',
    missing_etag: 'precondition_required',
    action_in_progress: 'busy',
};

const STATUS_KIND: Record<number, CpErrorKind> = {
    400: 'invalid_input',
    401: 'unauthenticated',
    403: 'forbidden',
    404: 'not_found',
    409: 'conflict',
    412: 'version_conflict',
    422: 'invalid_input',
    428: 'precondition_required',
    502: 'external_failure',
    503: 'unavailable',
    504: 'external_failure',
};

/** 再取得してからやり直すべき code (状態が画面の表示と食い違っている) */
const RELOAD_CODES: readonly string[] = [
    CP_PROBLEM_CODE.TENANT_VERSION_CONFLICT,
    CP_PROBLEM_CODE.INVALID_IF_MATCH,
    CP_PROBLEM_CODE.INVALID_TENANT_TRANSITION,
    PROBLEM_CODE.PRECONDITION_FAILED,
    PROBLEM_CODE.PRECONDITION_REQUIRED,
];

/**
 * Problem Details の errors に、指定した項目エラーの code があるかを判定する関数
 * @param {unknown} error catch した値
 * @param {string} field_code 項目エラーの code (CP_FIELD_ERROR_CODE)
 * @returns {boolean} 含まれる場合は true
*/
export const hasFieldErrorCode = (error: unknown, field_code: string): boolean => {
    return (problemOf(error)?.errors ?? []).some((item) => item.code === field_code);
};

/**
 * API のエラーを分類する関数
 * @param {unknown} error catch した値
 * @returns {CpErrorInfo} 分類
*/
export const classifyCpError = (error: unknown): CpErrorInfo => {
    if (error instanceof CpGuardError) {
        return { kind: GUARD_KIND[error.reason], status: null, code: null, problem: null, requires_reload: error.reason === 'missing_etag', error };
    }
    if (!(error instanceof ApiError)) {
        return { kind: 'unknown', status: null, code: null, problem: null, requires_reload: false, error };
    }
    const code = problemCodeOf(error) ?? null;
    const kind: CpErrorKind = code === CP_PROBLEM_CODE.INVALID_IF_MATCH ? 'precondition_required' : (STATUS_KIND[error.status] ?? 'unknown');
    const requires_reload = (code !== null && RELOAD_CODES.includes(code)) || error.status === 412 || error.status === 428 || hasFieldErrorCode(error, CP_FIELD_ERROR_CODE.INVALID_CURSOR);
    return { kind, status: error.status, code, problem: error.problem ?? null, requires_reload, error };
};
