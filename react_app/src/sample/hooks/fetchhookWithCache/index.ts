/** 
 * @description:
 * CacheとFetch APIを使用してデータを取得するカスタムフック
*/
import { useState, useEffect, useMemo } from 'react';

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
const useRequestObjectMemo = <T>({ url, method = 'GET', body, headers }: ResourceObj<T>) => {
    // リクエストオブジェクトを生成
    return useMemo(() => {
        const body_string = JSON.stringify(body);
        const request_key = `${url}-${method}-${body_string}-${JSON.stringify(headers)}`;
        const request = new Request(url, {
            method: method,
            headers: { 'Content-Type': 'application/json', ...headers },
            body: body ? body_string : undefined,
        });
        return { request, request_key };
    }, [url, method, body, headers]);
};

// Fetchの結果 (どのリクエストの結果かを保持する)
type FetchState<T> = {
    response: T | null;
    error: Error | null;
    // 結果が確定したリクエストキー (未確定なら null)。現在のキーと異なる間は読み込み中とみなす。
    settled_key: string | null;
};

const useFetch = <T>({ url = './api/sample', method = 'GET', body, headers, takeData = (p) => p.json(), cachelife = 3000 }: ResourceObj<T>) => {
    // Fetch状態ステート
    const [state, setState] = useState<FetchState<T>>({ response: null, error: null, settled_key: null });
    // リクエストオブジェクトメモを生成
    const { request, request_key } = useRequestObjectMemo({ url, method, body, headers });

    // useEffectでfetchを実行
    useEffect(() => {
        // クリーンアップ時用のAbortControllerを生成
        const controller = new AbortController();
        const propmise = promiseWrap({ request, takeData });
        propmise.then((stream) => {
            setState({ response: stream, error: null, settled_key: request_key });
        })
            // エラー時は直前のレスポンスを保持したままエラーを設定する
            .catch((err) => setState((prev) => ({ ...prev, error: err, settled_key: request_key })));
        return () => {
            controller.abort();
        }
    }, [request_key]); // URL, bodyが変わったら再実行

    // キャッシュの寿命を設定(unmount時も実行される)
    useEffect(() => {
        // タイマーはクリアしない (アンマウント後も指定時間後にキャッシュを削除する)
        setTimeout(() => {
            caches.open(CACHE_NAME).then((cache) => cache.delete(request))
        }, cachelife); // 指定された時間後にキャッシュを削除
        return () => { };
    }, [request_key]); // URL, bodyが変わったら再実行

    // 読み込み中は「現在のリクエストの結果がまだ確定していない」ことから導出する
    // (effect 内で同期的に setLoading(true) すると連鎖的な再レンダリングになるため。react-hooks/set-state-in-effect)
    const loading = state.settled_key !== request_key;
    return { response: state.response, loading, error: state.error };
};

// キャッシュを経由してfetchを実行する関数の型定義
type PromiseWrapType<T> = {
    request: Request;
    takeData?: (response: Response) => Promise<T>;
};

// キャッシュを経由してfetchを実行する関数
const promiseWrap = <T>({ request, takeData = (p) => p.json() }: PromiseWrapType<T>) => {
    // キャッシュからデータを取得
    return caches.match(request).then((cached_response) => {
        if (cached_response) {
            // console.log('Cache hit:', cached_response);
            return takeData(cached_response);
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