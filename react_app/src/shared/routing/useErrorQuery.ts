/**
 * @description:
 * URL のクエリ `?error=<code>` を読み取るカスタムフック
 * BFF がログイン開始・コールバックの失敗を伝えるために付ける (例: /?error=tenant_unavailable、/cp/login?error=login_rejected)。
*/
import { useSearchParams } from 'react-router-dom';

/** エラーコードを渡すクエリパラメータ名 (FastAPI: modules/auth/redirects.py の ERROR_QUERY_PARAM) */
export const ERROR_QUERY_PARAM = 'error';

/**
 * クエリからエラーコードを取り出す関数
 * @param {URLSearchParams} search_params クエリ
 * @returns {string | null} エラーコード (無い・空なら null)
*/
export const errorCodeOf = (search_params: URLSearchParams): string | null => {
    const code = search_params.get(ERROR_QUERY_PARAM);
    return code ? code : null;
};

/**
 * 現在の URL のエラーコードを返すカスタムフック
 * @returns {string | null} エラーコード (無ければ null)
*/
export const useErrorQuery = (): string | null => {
    const [search_params] = useSearchParams();
    return errorCodeOf(search_params);
};

export default useErrorQuery;
