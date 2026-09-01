/** 
 * @description:
 * Fetch APIを使用してデータを取得するカスタムフック
*/
import { useState, useEffect, useMemo, use } from 'react';
// 共通型定義, 関数読み込み
import { ResourceObj } from './type'
import { takeDataDef, generateRequestObject, generateRequestKey, requestFetch } from './common'

/** 
 * リクエストオブジェクトメモを生成するカスタムフック
 * @param {ResourceObj<T>} resource_obj リクエスト情報
 * @returns {Request} リクエストオブジェクト
*/
const useRequestObjectMemo = <T>(resource_obj: ResourceObj<T>) => {
    // リクエストオブジェクトを生成
    return useMemo(() => generateRequestObject(resource_obj), [generateRequestKey(resource_obj)]);
};
/** 
 * Fetchプロミスメモを生成するカスタムフック
 * @param {ResourceObj<T>} resource_obj リクエスト情報
 * @returns {Promise<T>} Fetchプロミスオブジェクト
*/
export const useFetchPromiseMemo = <T>(resource_obj: ResourceObj<T>) => {
    // リクエストプロミスを生成
    return useMemo(() => requestFetch<T>(resource_obj), [generateRequestKey(resource_obj)]);
};

const useFetch = <T>({ url, method = 'GET', body, headers, takeData = takeDataDef }: ResourceObj<T>) => {
    // Fetch状態ステート
    const [response, setResponse] = useState<T | null>(null);
    const [loading, setLoading] = useState<boolean>(false);
    const [error, setError] = useState<Error | null>(null);
    // リクエストオブジェクトメモを生成
    const request = useRequestObjectMemo({ url, method, body, headers });

    // useEffectでfetchを実行
    useEffect(() => {
        setLoading(true);
        // クリーンアップ時用のAbortControllerを生成
        const controller = new AbortController();
        fetch(request, { signal: controller.signal })
            .then((res) => {
                if (!res.ok) throw new Error(res.statusText);
                return takeData(res);
            })
            .then((data) => {
                setResponse(data);
                setError(null);
            })
            .catch((err) => {
                setError(err)
            })
            .finally(() => {
                setLoading(false);
            });
        return () => {
            // controller.abort();
        }
    }, [url]); // URL
    return { response, loading, error };
};

export default useFetch;