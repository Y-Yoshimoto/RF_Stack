/** 
 * @description:
 * Fetch APIを使用してデータを取得するカスタムフック
*/
import { useState, useEffect, useMemo } from 'react';

// リクエスト情報の型定義
type ResourceObj<T> = {
    url: string;
    method?: "GET" | "POST" | "PUT" | "DELETE";
    body?: object | undefined;
    headers?: HeadersInit;
    takeData?: (response: Response) => Promise<T>;
};

// リクエストオブジェクトメモを生成するカスタムフック
const useRequestObject = <T>({ url, method = 'GET', body, headers }: ResourceObj<T>) => {
    // リクエストオブジェクトを生成
    return useMemo(() => {
        const bodyString = JSON.stringify(body);
        const requestKey = `${url}-${method}-${bodyString}-${JSON.stringify(headers)}`;
        const request = new Request(url, {
            method: method,
            headers: { 'Content-Type': 'application/json', ...headers },
            body: body ? bodyString : undefined,
        });
        return { request, requestKey };
    }, [url, method, body, headers]);
};

const useFetch = <T>({ url = './api/sample', method = 'GET', body, headers, takeData = (r) => r.json() }: ResourceObj<T>) => {
    // Fetch状態ステート
    const [response, setResponse] = useState<T | null>(null);
    const [loading, setLoading] = useState<boolean>(false);
    const [error, setError] = useState<Error | null>(null);
    // リクエストオブジェクトメモを生成
    const { request, requestKey } = useRequestObject({ url, method, body, headers });

    // useEffectでfetchを実行
    useEffect(() => {
        // クリーンアップ時用のAbortControllerを生成
        const controller = new AbortController();
        setLoading(true);
        fetch(request, { signal: controller.signal })
            .then((res) => {
                if (!res.ok) throw new Error(res.statusText);
                return takeData(res);
            })
            .then((stream) => {
                setResponse(stream);
                setError(null);
            })
            .catch((err) => setError(err))
            .finally(() => setLoading(false));
        return () => {
            controller.abort();
        }
    }, [requestKey]); // URL, bodyが変わったら再実行
    return { response, loading, error };
}

export default useFetch;