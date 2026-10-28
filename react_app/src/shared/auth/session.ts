// プレーン共通の認証処理 (状態の取得・ログイン開始・ログアウト)
// プレーン固有の値 (エンドポイント・遷移先) は引数で受け取り、ここには持たない。
import { requestFetch } from '@/utils/libs/FetchComponents/common';
import { ApiError } from '@/utils/libs/FetchComponents/problem';
import type { ResourceObj } from '@/utils/libs/FetchComponents/type';
import type { AsyncResult } from '@/shared/hooks/useAsyncValue';
import type { AuthStatusResponse, LogoutResponse, SessionState } from './type';

/**
 * HTTP リクエストを行う関数の型 (requestFetch と同じ形。テストで差し替えられるようにする)。
 */
export type Requester = <T>(resource_obj: ResourceObj<T>) => Promise<T | null>;

/**
 * ブラウザをトップレベル遷移させる関数の型。
 * BFF のログイン開始・ログアウトは Cookie の付与と外部 (認証基盤) へのリダイレクトを伴うため、fetch ではなくトップレベル遷移にする。
 */
export type AssignLocation = (url: string) => void;

/**
 * 既定のトップレベル遷移 (window.location.assign)
 * @param {string} url 遷移先
*/
export const assignLocation: AssignLocation = (url) => {
    window.location.assign(url);
};

/**
 * 認証ステータス API を呼び出す関数
 * 401 (未認証・セッション切れ・別プレーンのセッション) は null を返し、それ以外の失敗は例外のまま送出する。
 * @param {string} url ステータス API のパス
 * @param {Requester} requester HTTP リクエスト関数
 * @returns {Promise<AuthStatusResponse | null>} 認証済みならレスポンス、未認証なら null
*/
export const fetchAuthStatus = async (url: string, requester: Requester = requestFetch): Promise<AuthStatusResponse | null> => {
    let body: AuthStatusResponse | null;
    try {
        body = await requester<AuthStatusResponse>({ url, method: 'GET' });
    } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
    }
    if (!body) throw new Error(`認証ステータスの応答が空です: ${url}`);
    return body;
};

/**
 * ログアウト後の遷移先を決める関数
 * 応答の logout_url (認証基盤のログアウト URL、またはログイン画面の URL) へ遷移する。応答が空の場合だけ fallback。
 * @param {LogoutResponse | null} body ログアウト API のレスポンス
 * @param {string} fallback 応答が空の場合の遷移先 (プレーンのログイン画面)
 * @returns {string} 遷移先
*/
export const resolveLogoutDestination = (body: LogoutResponse | null, fallback: string): string => body?.logout_url || fallback;

/**
 * ログアウト API を呼び出し、遷移先へトップレベル遷移する関数
 * API の失敗 (CSRF 検証失敗・ネットワークエラー等) は例外のまま送出し、遷移しない (セッションが残っている可能性があるため)。
 * @param {object} params
 * @param {string} params.url ログアウト API のパス
 * @param {string} params.fallback 応答に遷移先が無い場合の遷移先
 * @param {Requester} params.requester HTTP リクエスト関数
 * @param {AssignLocation} params.assign トップレベル遷移関数
 * @returns {Promise<string>} 遷移先
*/
export const logoutAndLeave = async ({ url, fallback, requester = requestFetch, assign = assignLocation }: {
    url: string;
    fallback: string;
    requester?: Requester;
    assign?: AssignLocation;
}): Promise<string> => {
    // 変更系のため requestFetch が X-Requested-With: rf-stack を付与する
    const body = await requester<LogoutResponse>({ url, method: 'POST' });
    const destination = resolveLogoutDestination(body, fallback);
    assign(destination);
    return destination;
};

/**
 * セッション読み込みの結果をセッションの状態に変換する関数
 * @param {AsyncResult<S | null>} result 読み込み結果 (null は未認証)
 * @returns {SessionState<S>} セッションの状態
*/
export const toSessionState = <S,>(result: AsyncResult<S | null>): SessionState<S> => {
    if (result.status === 'loading') return { status: 'loading' };
    if (result.status === 'error') return { status: 'error', error: result.error };
    return result.value === null ? { status: 'unauthenticated' } : { status: 'authenticated', session: result.value };
};
