/**
 * @description:
 * Fetch APIを使用してデータを取得するカスタムフック
*/
import { useState, useEffect, useMemo } from 'react';
// 共通型定義, 関数読み込み
import { ResourceObj } from './type'
import { takeDataDef, generateRequestObject, generateRequestKey, requestFetch } from './common'
import { toApiError } from './problem'

/**
 * リクエストオブジェクトメモを生成するカスタムフック
 * リクエストキー (url・method・body・headers) が変わったときだけ再生成する。
 * @param {ResourceObj<T>} resource_obj リクエスト情報
 * @returns {Request} リクエストオブジェクト
*/
const useRequestObjectMemo = <T>(resource_obj: ResourceObj<T>) => {
    // useMemo の依存配列は単純な式にする (react-hooks/use-memo)。キーを先に計算して渡す。
    const request_key = generateRequestKey(resource_obj);
    // リクエストオブジェクトを生成
    return useMemo(() => generateRequestObject(resource_obj), [request_key]);
};
/**
 * Fetchプロミスメモを生成するカスタムフック
 * リクエストキー (url・method・body・headers) が変わったときだけ再生成する。
 * @param {ResourceObj<T>} resource_obj リクエスト情報
 * @returns {Promise<T>} Fetchプロミスオブジェクト
*/
export const useFetchPromiseMemo = <T>(resource_obj: ResourceObj<T>) => {
    const request_key = generateRequestKey(resource_obj);
    // リクエストプロミスを生成
    return useMemo(() => requestFetch<T>(resource_obj), [request_key]);
};

/** Fetchの結果 (どの URL のリクエストの結果かを保持する) */
type FetchState<T> = {
    response: T | null;
    error: Error | null;
    /** 結果が確定した URL (未確定なら null)。現在の URL と異なる間は読み込み中とみなす。 */
    settled_url: string | null;
};

export const useFetch = <T>({ url, method = 'GET', body, headers, takeData = takeDataDef }: ResourceObj<T>) => {
    // Fetch状態ステート
    const [state, setState] = useState<FetchState<T>>({ response: null, error: null, settled_url: null });
    // リクエストオブジェクトメモを生成
    const request = useRequestObjectMemo({ url, method, body, headers });

    // useEffectでfetchを実行 (URL が変わったら再実行)
    useEffect(() => {
        // クリーンアップ時用のAbortControllerを生成
        const controller = new AbortController();
        fetch(request, { signal: controller.signal })
            .then(async (res) => {
                // エラーステータスは ApiError (Problem Details を problem に保持) として送出する
                if (!res.ok) throw await toApiError(res);
                return takeData(res);
            })
            .then((data) => {
                setState({ response: data, error: null, settled_url: url });
            })
            .catch((err) => {
                // エラー時は直前のレスポンスを保持したままエラーを設定する
                setState((prev) => ({ ...prev, error: err, settled_url: url }));
            });
        return () => {
            // controller.abort();
        }
    }, [url]); // URL

    // 読み込み中は「現在の URL の結果がまだ確定していない」ことから導出する
    // (effect 内で同期的に setLoading(true) すると連鎖的な再レンダリングになるため。react-hooks/set-state-in-effect)
    const loading = state.settled_url !== url;
    return { response: state.response, loading, error: state.error };
};

export default useFetch;
