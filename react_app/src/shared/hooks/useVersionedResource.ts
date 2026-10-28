/**
 * @description:
 * ETag 付きのリソース (詳細) を取得・保持するカスタムフック (プレーン共通)
 * - key が変わるか reload を呼ぶと取り直す (取得中は loading)。古い取得の結果は捨てる
 * - 更新操作の結果を applyUpdate で重ねる (取得し直さずに表示と ETag を新しくする)。取り直した後は前の取得結果への更新を使わない
 * プレーンの詳細フック (useTenant・useUser・useOrganization) が、取得関数・重ね方・エラー分類を渡して使う。
*/
import { useCallback, useState } from 'react';
import type { ApiErrorInfo } from '@/shared/api/errors';
import type { WithEtag } from '@/shared/api/etag';
import { useAsyncValue } from '@/shared/hooks/useAsyncValue';

/**
 * 詳細の状態と操作。
 */
export type VersionedResourceState<T, U> = {
    status: 'loading' | 'success' | 'error';
    /** 詳細 (取得前・失敗時は null)。applyUpdate で反映した更新を含む。 */
    value: T | null;
    /** 保持している ETag (取得前・失敗時は null)。更新系の If-Match に渡す。 */
    etag: string | null;
    /** 取得の失敗 (status === 'error' のとき)。 */
    error: ApiErrorInfo | null;
    /** 取り直す。412 などで requires_reload のときに使う。 */
    reload: () => void;
    /** 更新操作の結果を重ねる (取得前・失敗時は何もしない)。 */
    applyUpdate: (update: U) => void;
};

export type UseVersionedResourceParams<T, U> = {
    /** 取得のキー (変わると取り直す)。 */
    key: string;
    /** 詳細と ETag を取得する関数。key が変わったときの値を使う。 */
    load: () => Promise<WithEtag<T>>;
    /** 更新を重ねる関数 (別のリソースへの更新など、重ねないものは current をそのまま返す)。 */
    merge: (current: WithEtag<T>, update: U) => WithEtag<T>;
    /** エラーの分類 (プレーンごと)。 */
    classify: (error: unknown) => ApiErrorInfo;
};

/** 取得結果に重ねた状態 (どの取得結果に対するものかを base で判別する) */
type Overlay<T> = {
    base: WithEtag<T>;
    current: WithEtag<T>;
};

/**
 * ETag 付きのリソースを取得・保持するカスタムフック
 * @param {UseVersionedResourceParams<T, U>} params キー・取得関数・重ね方・エラー分類
 * @returns {VersionedResourceState<T, U>} 詳細の状態と操作
*/
export const useVersionedResource = <T, U>({ key, load, merge, classify }: UseVersionedResourceParams<T, U>): VersionedResourceState<T, U> => {
    const { result, reload } = useAsyncValue(load, key);
    const [overlay, setOverlay] = useState<Overlay<T> | null>(null);

    const base = result.status === 'success' ? result.value : null;
    const applyUpdate = useCallback((update: U) => {
        if (base === null) return;
        // 同じ取得結果に対する更新は順に重ねる (PATCH の応答が一部の項目しか持たない場合に、前の更新を失わないため)
        setOverlay((prev) => ({ base, current: merge(prev !== null && prev.base === base ? prev.current : base, update) }));
    }, [base, merge]);

    if (result.status === 'loading') return { status: 'loading', value: null, etag: null, error: null, reload, applyUpdate };
    if (result.status === 'error') return { status: 'error', value: null, etag: null, error: classify(result.error), reload, applyUpdate };
    const current = overlay !== null && overlay.base === result.value ? overlay.current : result.value;
    return { status: 'success', value: current.body, etag: current.etag, error: null, reload, applyUpdate };
};

export default useVersionedResource;
