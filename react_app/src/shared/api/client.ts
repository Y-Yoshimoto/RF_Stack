// プレーン別 API クライアントの共通部分
// 各プレーンはこれを使い、エラー時の処理 (401 でログイン画面へ、403 でエラー画面へ) を自プレーンの認証状態に結び付ける。
import { requestFetch } from '@/utils/libs/FetchComponents/common';
import type { ResourceObj } from '@/utils/libs/FetchComponents/type';
import type { Requester } from '@/shared/auth/session';

/**
 * API クライアント。
 */
export type ApiClient = {
    /**
     * リクエストを送る。変更系メソッドには CSRF 対策ヘッダーが付与される (requestFetch)。
     * 2xx 以外は ApiError を送出する (送出前に onError に通知する)。
     */
    request: <T>(resource_obj: ResourceObj<T>) => Promise<T | null>;
};

/**
 * API クライアントを生成する関数
 * @param {(error: unknown) => void} onError 失敗時の通知先 (プレーンの認証状態への反映など)。例外は呼び出し元にもそのまま送出する
 * @param {Requester} requester HTTP リクエスト関数
 * @returns {ApiClient} API クライアント
*/
export const createApiClient = (onError: (error: unknown) => void, requester: Requester = requestFetch): ApiClient => ({
    request: async <T,>(resource_obj: ResourceObj<T>) => {
        try {
            return await requester<T>(resource_obj);
        } catch (error) {
            onError(error);
            throw error;
        }
    },
});
