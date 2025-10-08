/** 
 * @description:
 * Fetch APIを使用してデータを取得するカスタムフック
*/
import { useState, useEffect, useMemo, use } from 'react';
// 共通型定義, 関数読み込み
import { ResourceObj, takeDataDef, generateRequestObjectAndKey, requestFetch } from './common'

// リクエストオブジェクトメモを生成するカスタムフック
const useRequestObject = <T>({ url, method = 'GET', body, headers }: ResourceObj<T>) => {
    // リクエストオブジェクトを生成
    return useMemo(() => {
        return generateRequestObjectAndKey({ url, method, body, headers });
    }, [url, method, body, headers]);
};

const useFetch = <T>({ url, method = 'GET', body, headers, takeData = takeDataDef }: ResourceObj<T>) => {
    // Fetch状態ステート
    const [response, setResponse] = useState<T | null>(null);
    const [loading, setLoading] = useState<boolean>(false);
    const [error, setError] = useState<Error | null>(null);
    // リクエストオブジェクトメモを生成
    const { request, requestKey } = useRequestObject({ url, method, body, headers });

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
                // console.error('Fetch error:', err);
                setError(err)
            })
            .finally(() => setLoading(false));
        return () => {
            controller.abort();
        }
    }, [requestKey]); // URL, bodyが変わったら再実行
    return { response, loading, error };
};

export default useFetch;