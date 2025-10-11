/** 
 * @description:
 * CacheとFetch APIを使用してデータを取得するカスタムフック
*/import { useState, useEffect, useMemo } from 'react';

// キャッシュ名定義
const CACHE_NAME = 'cache-hook';

// リクエスト情報の型定義
type ResourceObj<T> = {
    url: string;
    method?: "GET";
    body?: object | undefined;
    headers?: HeadersInit;
    takeData?: (response: Response) => Promise<T>;
    cachelife?: number; // キャッシュの寿命(ミリ秒)
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

const useFetch = <T>({ url = './api/sample', method = 'GET', body, headers, takeData = (p) => p.json(), cachelife = 3000 }: ResourceObj<T>) => {
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
        const propmise = promiseWrap({ request, takeData });
        propmise.then((stream) => {
            setResponse(stream);
            setError(null);
        })
            .catch((err) => setError(err))
            .finally(() => setLoading(false));
        return () => {
            controller.abort();
        }
    }, [requestKey]); // URL, bodyが変わったら再実行

    // キャッシュの寿命を設定(unmount時も実行される)
    useEffect(() => {
        const _ = setTimeout(() => {
            caches.open(CACHE_NAME).then((cache) => cache.delete(request))
        }, cachelife); // 指定された時間後にキャッシュを削除
        return () => { };
    }, [requestKey]); // URL, bodyが変わったら再実行
    return { response, loading, error };
};

// キャッシュを経由してfetchを実行する関数の型定義
type promiseWrapType<T> = {
    request: Request;
    takeData?: (response: Response) => Promise<T>;
};

// キャッシュを経由してfetchを実行する関数
const promiseWrap = <T>({ request, takeData = (p) => p.json() }: promiseWrapType<T>) => {
    // キャッシュからデータを取得
    return caches.match(request).then((cachedResponse) => {
        if (cachedResponse) {
            // console.log('Cache hit:', cachedResponse);
            return takeData(cachedResponse);
        }
        // キャッシュにデータがない場合はfetchを実行
        return fetch(request).then((response) => {
            if (!response.ok) throw new Error(response.statusText);
            // レスポンスをキャッシュに保存
            return caches.open(CACHE_NAME).then((cache) => {
                // console.log('Cache miss:', response);
                cache.put(request, response.clone());
                return takeData(response);
            });
        });
    });
};

export default useFetch;