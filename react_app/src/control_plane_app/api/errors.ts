// CP の API エラーの分類 (画面の分岐用)
// 分類の本体はプレーン共通の shared/api/errors.ts。ここでは CP 固有の code (再取得を促すもの) と、
// フックが API を呼ぶ前に弾く理由 (CpGuardError) を決める。
// 401 はクライアント (useCpApiClient) が認証状態に反映し、ルートガードがログイン画面へ遷移させる。
import { ApiGuardError, classifyApiError, type ApiErrorInfo, type ApiErrorKind, type ApiErrorRules } from '@/shared/api/errors';
import { CP_PROBLEM_CODE } from './contract';

export { hasFieldErrorCode } from '@/shared/api/errors';

/**
 * CP の API エラーの種類 (shared/api/errors.ts の ApiErrorKind)。
 * - forbidden は saas_viewer が変更操作を呼んだ場合 (API を呼ばずに弾いたもの) を含む
 * - external_failure は払い出しの失敗など (problem の tenant_id / step を参照できる)
 */
export type CpErrorKind = ApiErrorKind;

/**
 * 分類したエラー (problem は拡張メンバー tenant_id / step / operation / current_status 等を含む)。
 */
export type CpErrorInfo = ApiErrorInfo;

/**
 * フックが API を呼ぶ前に弾いた理由。
 */
export type CpGuardReason = 'write_not_allowed' | 'missing_etag' | 'action_in_progress';

const GUARD_KIND: Record<CpGuardReason, CpErrorKind> = {
    write_not_allowed: 'forbidden',
    missing_etag: 'precondition_required',
    action_in_progress: 'busy',
};

/**
 * フックが API を呼ぶ前に弾いたことを表す例外 (saas_viewer の変更操作・ETag 未取得・二重実行)。
 */
export class CpGuardError extends ApiGuardError {
    declare readonly reason: CpGuardReason;

    constructor(reason: CpGuardReason) {
        super(reason, { kind: GUARD_KIND[reason], requires_reload: reason === 'missing_etag' }, `CP の操作を実行できません: ${reason}`);
        this.name = 'CpGuardError';
    }
}

/** CP 固有の、再取得してからやり直すべき code (状態が画面の表示と食い違っている) */
const CP_ERROR_RULES: ApiErrorRules = {
    reload_codes: [CP_PROBLEM_CODE.TENANT_VERSION_CONFLICT, CP_PROBLEM_CODE.INVALID_TENANT_TRANSITION],
};

/**
 * API のエラーを分類する関数
 * @param {unknown} error catch した値
 * @returns {CpErrorInfo} 分類
*/
export const classifyCpError = (error: unknown): CpErrorInfo => classifyApiError(error, CP_ERROR_RULES);
