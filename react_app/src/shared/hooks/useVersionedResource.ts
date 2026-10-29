/**
 * @description:
 * ETag 付きのリソース (詳細) を取得・保持するカスタムフック (プレーン共通)
 * - key が変わるか reload を呼ぶと取り直す (取得中は loading)。古い取得の結果は捨てる
 * - refresh は表示を保ったまま取り直す (loading に戻さない。取得中は is_refreshing)。412 の後に最新を自動で再表示する用途 (AP-UX-07)
 * - 更新操作の結果を applyUpdate で重ねる (取得し直さずに表示と ETag を新しくする)。取り直した後は前の取得結果への更新を使わない
 * プレーンの詳細フック (useTenant・useUser・useOrganization・useTodo) が、取得関数・重ね方・エラー分類を渡して使う。
*/
import { useCallback, useEffect, useRef, useState } from 'react';
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
    /** 取り直す (取得中は status が loading になる)。 */
    reload: () => void;
    /** 更新操作の結果を重ねる (取得前・失敗時は何もしない)。 */
    applyUpdate: (update: U) => void;
    /**
     * 表示を保ったまま取り直す (status は success のまま。取得中は is_refreshing)。412 などで requires_reload のときに使う。
     * 成功すれば true (取得した値で置き換え、それまでの applyUpdate の結果は捨てる)。
     * 失敗・途中で key が変わった・後から別の refresh を始めた場合は false (表示はそのまま。失敗は refresh_error)。
     * 取得前・取得の失敗時は reload と同じく取り直し (loading になる)、false を返す。
     */
    refresh: () => Promise<boolean>;
    /** refresh の取得中。 */
    is_refreshing: boolean;
    /** 最後の refresh の失敗 (次の refresh・reload・key の変更で消える)。404 なら対象が削除された・閲覧できなくなった。 */
    refresh_error: ApiErrorInfo | null;
};

export type UseVersionedResourceParams<T, U> = {
    /** 取得のキー (変わると取り直す)。 */
    key: string;
    /** 詳細と ETag を取得する関数。key が変わったときの値を使う (refresh は呼び出し時の値を使う)。 */
    load: () => Promise<WithEtag<T>>;
    /** 更新を重ねる関数 (別のリソースへの更新など、重ねないものは current をそのまま返す)。 */
    merge: (current: WithEtag<T>, update: U) => WithEtag<T>;
    /** エラーの分類 (プレーンごと)。 */
    classify: (error: unknown) => ApiErrorInfo;
};

/** 取得結果に重ねた状態 (どの値に対するものかを base で判別する) */
type Overlay<T> = {
    base: WithEtag<T>;
    current: WithEtag<T>;
};

/** refresh の状態 (どの取得結果に対するものかを origin で判別する) */
type RefreshState<T> = {
    /** refresh を始めたときの取得結果 (useAsyncValue の値) */
    origin: WithEtag<T>;
    /** 取り直した値 (取得中・失敗時は null) */
    value: WithEtag<T> | null;
    is_refreshing: boolean;
    error: ApiErrorInfo | null;
};

/**
 * ETag 付きのリソースを取得・保持するカスタムフック
 * @param {UseVersionedResourceParams<T, U>} params キー・取得関数・重ね方・エラー分類
 * @returns {VersionedResourceState<T, U>} 詳細の状態と操作
*/
export const useVersionedResource = <T, U>({ key, load, merge, classify }: UseVersionedResourceParams<T, U>): VersionedResourceState<T, U> => {
    const { result, reload } = useAsyncValue(load, key);
    const [overlay, setOverlay] = useState<Overlay<T> | null>(null);
    const [refreshed, setRefreshed] = useState<RefreshState<T> | null>(null);
    const origin = result.status === 'success' ? result.value : null;
    // refresh の結果が最新の呼び出しのものかを判別する (イベントハンドラーと effect からのみ読み書きする)
    const refresh_seq = useRef(0);
    const latest = useRef({ origin, load });
    useEffect(() => {
        latest.current = { origin, load };
    });

    // 表示の基準: refresh で取り直した値があればそれ、無ければ取得結果
    const current_refresh = refreshed !== null && refreshed.origin === origin ? refreshed : null;
    const base = current_refresh?.value ?? origin;

    const applyUpdate = useCallback((update: U) => {
        if (base === null) return;
        // 同じ値に対する更新は順に重ねる (PATCH の応答が一部の項目しか持たない場合に、前の更新を失わないため)
        setOverlay((prev) => ({ base, current: merge(prev !== null && prev.base === base ? prev.current : base, update) }));
    }, [base, merge]);

    const refresh = useCallback(async (): Promise<boolean> => {
        const start = latest.current;
        if (start.origin === null) {
            reload();
            return false;
        }
        const started_origin = start.origin;
        const seq = ++refresh_seq.current;
        setRefreshed((prev) => ({ origin: started_origin, value: prev?.origin === started_origin ? prev.value : null, is_refreshing: true, error: null }));
        const isLatest = () => seq === refresh_seq.current && latest.current.origin === started_origin;
        try {
            const value = await start.load();
            if (!isLatest()) return false;
            setRefreshed({ origin: started_origin, value, is_refreshing: false, error: null });
            return true;
        } catch (error) {
            if (isLatest()) setRefreshed((prev) => ({ origin: started_origin, value: prev?.origin === started_origin ? prev.value : null, is_refreshing: false, error: classify(error) }));
            return false;
        }
    }, [reload, classify]);

    const common = { reload, applyUpdate, refresh, is_refreshing: current_refresh?.is_refreshing ?? false, refresh_error: current_refresh?.error ?? null };
    if (result.status === 'loading') return { status: 'loading', value: null, etag: null, error: null, ...common };
    if (result.status === 'error') return { status: 'error', value: null, etag: null, error: classify(result.error), ...common };
    const shown = overlay !== null && overlay.base === base ? overlay.current : (base ?? result.value);
    return { status: 'success', value: shown.body, etag: shown.etag, error: null, ...common };
};

export default useVersionedResource;
