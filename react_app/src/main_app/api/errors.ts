// アプリケーションプレーン (AP) の API エラーの分類 (02 §6.2)
import { ApiError, PROBLEM_CODE, problemCodeOf } from '@/utils/libs/FetchComponents/problem';

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
