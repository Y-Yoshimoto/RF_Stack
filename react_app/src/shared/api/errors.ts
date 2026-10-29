// API エラーの分類 (画面の分岐用。プレーン共通の部分)
// 元のエラー (ApiError) と Problem Details の code は失わずに保持し、画面はまず kind で、必要なら code で分岐する。
// プレーン固有の code (再取得を促すもの等) は各プレーンの api/errors.ts が ApiErrorRules で渡す。
// 401 は各プレーンの API クライアントが認証状態に反映し、ルートガードがログイン画面へ遷移させる。
import { ApiError, FIELD_ERROR_CODE, PROBLEM_CODE, problemCodeOf, problemOf, type ProblemDetails } from '@/utils/libs/FetchComponents/problem';

/**
 * API エラーの種類。
 * - unauthenticated: 401 (ログイン画面へ遷移する。画面での表示は不要)
 * - forbidden: 403、または権限の無いユーザーが変更操作を呼んだ (API を呼ばずに弾いたものを含む)
 * - not_found: 404
 * - version_conflict: 412 (他の操作で更新済み。最新を再取得してやり直す)
 * - precondition_required: 428 / 400 invalid_if_match、または ETag 未取得 (再取得してやり直す)
 * - conflict: 409 (一意制約違反・状態遷移の不正など。code で分岐する)
 * - invalid_input: 422 (errors に項目ごとの詳細) / 400
 * - external_failure: 502 / 504 (IdP の操作・払い出しの失敗など)
 * - unavailable: 503
 * - busy: 同じフックで別の操作を実行中 (API を呼んでいない)
 * - unknown: 上記以外 (500・ネットワークエラーなど)
 */
export type ApiErrorKind =
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
export type ApiErrorInfo = {
    kind: ApiErrorKind;
    /** HTTP ステータス (API を呼んでいない・ネットワークエラーでは null)。 */
    status: number | null;
    /** Problem Details の code (無ければ null。API を呼ばずに弾いた場合はフックが決めた code)。 */
    code: string | null;
    /** Problem Details (拡張メンバーを含む)。 */
    problem: ProblemDetails | null;
    /** 画面の表示が古い可能性が高く、最新を再取得してからやり直すべき。 */
    requires_reload: boolean;
    /** 元のエラー (ApiError・ApiGuardError 等)。 */
    error: unknown;
};

/**
 * フックが API を呼ぶ前に弾いたことを表す例外の基底クラス (権限なし・ETag 未取得・二重実行など)。
 * 各プレーンは理由 (reason) ごとに kind / code を決めたサブクラスを作る。
 */
export class ApiGuardError extends Error {
    /** 弾いた理由 (プレーンごとに定義)。 */
    readonly reason: string;
    readonly kind: ApiErrorKind;
    /** 分類結果の code (API の code に合わせる場合に指定する)。 */
    readonly code: string | null;
    readonly requires_reload: boolean;

    constructor(reason: string, info: { kind: ApiErrorKind; code?: string | null; requires_reload?: boolean }, message: string) {
        super(message);
        this.name = 'ApiGuardError';
        this.reason = reason;
        this.kind = info.kind;
        this.code = info.code ?? null;
        this.requires_reload = info.requires_reload ?? false;
    }
}

/**
 * プレーン固有の分類規則。
 */
export type ApiErrorRules = {
    /** 再取得してからやり直すべき code (共通のものに追加する)。 */
    reload_codes?: readonly string[];
};

const STATUS_KIND: Record<number, ApiErrorKind> = {
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

/** 再取得してからやり直すべき code (プレーン共通。modules/api_common/etag.py) */
const COMMON_RELOAD_CODES: readonly string[] = [PROBLEM_CODE.INVALID_IF_MATCH, PROBLEM_CODE.PRECONDITION_FAILED, PROBLEM_CODE.PRECONDITION_REQUIRED];

/**
 * Problem Details の errors に、指定した項目エラーの code があるかを判定する関数
 * @param {unknown} error catch した値
 * @param {string} field_code 項目エラーの code (例: FIELD_ERROR_CODE.INVALID_CURSOR)
 * @returns {boolean} 含まれる場合は true
*/
export const hasFieldErrorCode = (error: unknown, field_code: string): boolean => {
    return (problemOf(error)?.errors ?? []).some((item) => item.code === field_code);
};

/**
 * API のエラーを分類する関数
 * @param {unknown} error catch した値
 * @param {ApiErrorRules} rules プレーン固有の分類規則
 * @returns {ApiErrorInfo} 分類
*/
export const classifyApiError = (error: unknown, rules: ApiErrorRules = {}): ApiErrorInfo => {
    if (error instanceof ApiGuardError) {
        return { kind: error.kind, status: null, code: error.code, problem: null, requires_reload: error.requires_reload, error };
    }
    if (!(error instanceof ApiError)) {
        return { kind: 'unknown', status: null, code: null, problem: null, requires_reload: false, error };
    }
    const code = problemCodeOf(error) ?? null;
    const kind: ApiErrorKind = code === PROBLEM_CODE.INVALID_IF_MATCH ? 'precondition_required' : (STATUS_KIND[error.status] ?? 'unknown');
    const is_reload_code = code !== null && (COMMON_RELOAD_CODES.includes(code) || (rules.reload_codes ?? []).includes(code));
    const requires_reload = is_reload_code || error.status === 412 || error.status === 428 || hasFieldErrorCode(error, FIELD_ERROR_CODE.INVALID_CURSOR);
    return { kind, status: error.status, code, problem: error.problem ?? null, requires_reload, error };
};
