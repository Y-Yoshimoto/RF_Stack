/**
 * @description:
 * カーソル方式の一覧 (03 §3) を「さらに読み込む」で取得するカスタムフック (プレーン共通)
 * query_key が変わるか reload を呼ぶと先頭ページから取り直す。古い取得の結果は捨てる。
 * プレーンの一覧フック (useTenantList・useUserList 等) が、エンドポイント関数とエラー分類を渡して使う。
*/
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ApiErrorInfo } from '@/shared/api/errors';

/**
 * カーソル方式の 1 ページ (FastAPI: modules/api_common/pagination)。
 */
export type CursorPage<T> = {
    items: T[];
    /** 次のページのカーソル。最後のページでは null。 */
    next_cursor: string | null;
    /** 総件数 (include_total を指定した場合のみ)。 */
    total?: number | null;
};

/**
 * 一覧の状態と操作。
 */
export type CursorListState<T> = {
    /** 先頭ページの取得状態。 */
    status: 'loading' | 'success' | 'error';
    /** 読み込み済みの要素 (ページを連結したもの)。 */
    items: T[];
    /** 総件数 (include_total を指定した場合のみ。先頭ページの値)。 */
    total: number | null;
    /** 次のページがある。 */
    has_more: boolean;
    /** 次のページを取得中。 */
    is_loading_more: boolean;
    /** 先頭ページの取得失敗 (status === 'error' のとき)。 */
    error: ApiErrorInfo | null;
    /** 次のページの取得失敗 (読み込み済みの要素は保持する。requires_reload なら reload で先頭から取り直す)。 */
    load_more_error: ApiErrorInfo | null;
    /** 次のページを取得して連結する (取得中・最後のページでは何もしない)。 */
    loadMore: () => void;
    /** 先頭ページから取り直す。 */
    reload: () => void;
    /** 読み込み済みの要素のうち、同じ ID のものを置き換える (更新操作の結果の反映。無ければ何もしない)。 */
    replaceItem: (item: T) => void;
    /** 読み込み済みの要素から、指定した ID のものを除く (削除操作の結果の反映)。 */
    removeItem: (id: string) => void;
};

export type UseCursorListParams<T> = {
    /** 絞り込み・並び順を表すキー (変わると先頭ページから取り直す)。 */
    query_key: string;
    /** 1 ページを取得する関数 (cursor が null なら先頭ページ)。query_key が変わったときの値を使う。 */
    fetchPage: (cursor: string | null) => Promise<CursorPage<T>>;
    /** エラーの分類 (プレーンごと)。 */
    classify: (error: unknown) => ApiErrorInfo;
};

/** 取得済みの一覧 (どの取得の結果かを request_key で判別する) */
type ListSnapshot<T> = {
    request_key: string;
    first: { status: 'success' } | { status: 'error'; error: ApiErrorInfo };
    items: T[];
    next_cursor: string | null;
    total: number | null;
    is_loading_more: boolean;
    load_more_error: ApiErrorInfo | null;
};

/**
 * ページを連結する関数 (同じ ID の要素は後から来たもので置き換えず、先に読み込んだものを残す)
 * @param {readonly T[]} items 読み込み済みの要素
 * @param {readonly T[]} next 次のページの要素
 * @returns {T[]} 連結した要素
*/
export const appendById = <T extends { id: string }>(items: readonly T[], next: readonly T[]): T[] => {
    const known = new Set(items.map((item) => item.id));
    return [...items, ...next.filter((item) => !known.has(item.id))];
};

/**
 * カーソル方式の一覧を取得するカスタムフック
 * @param {UseCursorListParams<T>} params キー・取得関数・エラー分類
 * @returns {CursorListState<T>} 一覧の状態と操作
*/
export const useCursorList = <T extends { id: string }>({ query_key, fetchPage, classify }: UseCursorListParams<T>): CursorListState<T> => {
    const [generation, setGeneration] = useState(0);
    const request_key = `${query_key}#${generation}`;
    const [snapshot, setSnapshot] = useState<ListSnapshot<T> | null>(null);
    // 次のページの二重取得を防ぐ (イベントハンドラーからのみ読み書きする)
    const loading_more_key = useRef<string | null>(null);

    useEffect(() => {
        let is_current = true;
        fetchPage(null).then(
            (page) => {
                if (is_current) setSnapshot({ request_key, first: { status: 'success' }, items: page.items, next_cursor: page.next_cursor, total: page.total ?? null, is_loading_more: false, load_more_error: null });
            },
            (error: unknown) => {
                if (is_current) setSnapshot({ request_key, first: { status: 'error', error: classify(error) }, items: [], next_cursor: null, total: null, is_loading_more: false, load_more_error: null });
            },
        );
        return () => {
            is_current = false;
        };
    }, [request_key]);

    const current = snapshot !== null && snapshot.request_key === request_key ? snapshot : null;

    const loadMore = useCallback(() => {
        if (current === null || current.first.status !== 'success' || current.next_cursor === null || loading_more_key.current === request_key) return;
        const cursor = current.next_cursor;
        loading_more_key.current = request_key;
        setSnapshot({ ...current, is_loading_more: true, load_more_error: null });
        fetchPage(cursor)
            .then(
                (page) => setSnapshot((prev) => (prev?.request_key === request_key && prev.next_cursor === cursor
                    ? { ...prev, items: appendById(prev.items, page.items), next_cursor: page.next_cursor, is_loading_more: false }
                    : prev)),
                (error: unknown) => setSnapshot((prev) => (prev?.request_key === request_key ? { ...prev, is_loading_more: false, load_more_error: classify(error) } : prev)),
            )
            .finally(() => {
                if (loading_more_key.current === request_key) loading_more_key.current = null;
            });
    }, [current, request_key, fetchPage, classify]);

    const reload = useCallback(() => setGeneration((value) => value + 1), []);

    const replaceItem = useCallback((item: T) => {
        setSnapshot((prev) => (prev?.request_key === request_key ? { ...prev, items: prev.items.map((known) => (known.id === item.id ? item : known)) } : prev));
    }, [request_key]);

    const removeItem = useCallback((id: string) => {
        setSnapshot((prev) => (prev?.request_key === request_key ? { ...prev, items: prev.items.filter((known) => known.id !== id) } : prev));
    }, [request_key]);

    if (current === null) {
        return { status: 'loading', items: [], total: null, has_more: false, is_loading_more: false, error: null, load_more_error: null, loadMore, reload, replaceItem, removeItem };
    }
    return {
        status: current.first.status,
        items: current.items,
        total: current.total,
        has_more: current.next_cursor !== null,
        is_loading_more: current.is_loading_more,
        error: current.first.status === 'error' ? current.first.error : null,
        load_more_error: current.load_more_error,
        loadMore,
        reload,
        replaceItem,
        removeItem,
    };
};

export default useCursorList;
