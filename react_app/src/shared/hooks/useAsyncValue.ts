/**
 * @description:
 * 非同期処理 (Promise を返す関数) の結果を状態として扱うカスタムフック
 * key が変わるか reload を呼ぶと再実行する。古い実行の結果は捨てる。
*/
import { useCallback, useEffect, useState } from 'react';

/**
 * 非同期処理の結果。
 */
export type AsyncResult<T> =
    | { status: 'loading' }
    | { status: 'success'; value: T }
    | { status: 'error'; error: unknown };

/** 実行キーと結果の組 (結果がどの実行のものかを判別するため) */
type SettledEntry<T> = {
    request_key: string;
    result: AsyncResult<T>;
};

/**
 * 非同期処理の結果を状態として扱うカスタムフック
 * - 実行中は { status: 'loading' }、完了後は success / error
 * - load は key が変わったとき (または reload 時) の値を使う。load の参照の変化だけでは再実行しない
 * - effect 内で同期的に setState しないよう、loading は「現在のキーの結果がまだ無い」ことから導出する
 * @param {() => Promise<T>} load 非同期処理
 * @param {string} key 実行キー (変わると再実行する)
 * @returns {{ result: AsyncResult<T>, reload: () => void }} 結果と再実行関数
*/
export const useAsyncValue = <T,>(load: () => Promise<T>, key: string) => {
    const [generation, setGeneration] = useState(0);
    const [settled, setSettled] = useState<SettledEntry<T> | null>(null);
    const request_key = `${key}#${generation}`;

    useEffect(() => {
        let is_current = true;
        load().then(
            (value) => {
                if (is_current) setSettled({ request_key, result: { status: 'success', value } });
            },
            (error: unknown) => {
                if (is_current) setSettled({ request_key, result: { status: 'error', error } });
            },
        );
        return () => {
            is_current = false;
        };
    }, [request_key]);

    const reload = useCallback(() => setGeneration((value) => value + 1), []);
    const result: AsyncResult<T> = settled !== null && settled.request_key === request_key ? settled.result : { status: 'loading' };
    return { result, reload };
};

export default useAsyncValue;
