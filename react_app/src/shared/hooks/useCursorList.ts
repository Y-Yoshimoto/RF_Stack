/**
 * @description:
 * カーソル方式の一覧 (03 §3) を「さらに読み込む」で取得するカスタムフック (プレーン共通)
 * query_key が変わるか reload を呼ぶと先頭ページから取り直す。古い取得の結果は捨てる。
 * プレーンの一覧フック (useTenantList・useUserList 等) が、エンドポイント関数とエラー分類を渡して使う。
 * 操作の結果は取り直さずに反映できる: replaceItem (更新)・removeItem (削除)・insertItem (作成・別の一覧からの移動)。
 * total (include_total を指定した場合) は insertItem / removeItem で増減する。
*/
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
    /** 読み込み済みの要素から、指定した ID のものを除く (削除操作の結果の反映。除いたときは total を 1 減らす)。 */
    removeItem: (id: string) => void;
    /**
     * 要素を差し込む (作成操作・別の一覧からの移動の結果の反映)。同じ ID の要素があれば移す (total は変えない)。無ければ total を 1 増やす。
     * - 'start': 先頭 / 数値: 読み込み済みの要素のその位置 (範囲外は端に寄せる)
     * - 'end': 末尾。続きのページがあるときは読み込み済みの要素の後ろに仮に置き、最後のページまで読み込んだら末尾に並べる
     *   (古い順の一覧で、新しく作った要素が途中のページの間に入らないようにする)
     * 取得前・取得の失敗時は何もしない。
     */
    insertItem: (item: T, at: CursorInsertPosition) => void;
};

/** insertItem の差し込み位置。 */
export type CursorInsertPosition = 'start' | 'end' | number;

export type UseCursorListParams<T> = {
    /** 絞り込み・並び順を表すキー (変わると先頭ページから取り直す)。 */
    query_key: string;
    /** 1 ページを取得する関数 (cursor が null なら先頭ページ)。query_key が変わったときの値を使う。 */
    fetchPage: (cursor: string | null) => Promise<CursorPage<T>>;
    /** エラーの分類 (プレーンごと)。 */
    classify: (error: unknown) => ApiErrorInfo;
};

/** 取得済みの一覧 (どの取得の結果かを request_key で判別する) */
export type ListSnapshot<T> = {
    request_key: string;
    first: { status: 'success' } | { status: 'error'; error: ApiErrorInfo };
    items: T[];
    /** 続きのページがあるときに insertItem(…, 'end') で末尾に置いた要素 (ページで届いたら除く) */
    tail: T[];
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
 * 次のページを取得した後の要素と末尾に置いた要素を作る関数 (最後のページなら末尾に置いた要素を連結する)
 * @param {ListSnapshot<T>} prev 取得前の状態
 * @param {CursorPage<T>} page 次のページ
 * @returns {Pick<ListSnapshot<T>, 'items' | 'tail'>} 要素と末尾に置いた要素
*/
const appendPage = <T extends { id: string }>(prev: ListSnapshot<T>, page: CursorPage<T>): Pick<ListSnapshot<T>, 'items' | 'tail'> => {
    const items = appendById(prev.items, page.items);
    const known = new Set(items.map((item) => item.id));
    const tail = prev.tail.filter((item) => !known.has(item.id));
    return page.next_cursor === null ? { items: [...items, ...tail], tail: [] } : { items, tail };
};

/**
 * 総件数を増減する関数 (不明なら不明のまま。0 未満にしない)
 * @param {number | null} total 総件数
 * @param {number} delta 増減
 * @returns {number | null} 増減後の総件数
*/
const shiftTotal = (total: number | null, delta: number): number | null => (total === null ? null : Math.max(0, total + delta));

/**
 * 要素を差し込んだ状態を作る関数 (同じ ID の要素は移す)
 * @param {ListSnapshot<T>} prev 状態
 * @param {T} item 要素
 * @param {CursorInsertPosition} at 位置
 * @returns {ListSnapshot<T>} 差し込んだ状態
*/
export const insertIntoSnapshot = <T extends { id: string }>(prev: ListSnapshot<T>, item: T, at: CursorInsertPosition): ListSnapshot<T> => {
    const existed = prev.items.some((known) => known.id === item.id) || prev.tail.some((known) => known.id === item.id);
    const items = prev.items.filter((known) => known.id !== item.id);
    const tail = prev.tail.filter((known) => known.id !== item.id);
    const total = existed ? prev.total : shiftTotal(prev.total, 1);
    if (at === 'start') return { ...prev, items: [item, ...items], tail, total };
    if (at === 'end') return prev.next_cursor === null ? { ...prev, items: [...items, ...tail, item], tail: [], total } : { ...prev, items, tail: [...tail, item], total };
    const index = Math.min(Math.max(0, Math.trunc(at)), items.length);
    return { ...prev, items: [...items.slice(0, index), item, ...items.slice(index)], tail, total };
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
                if (is_current) setSnapshot({ request_key, first: { status: 'success' }, items: page.items, tail: [], next_cursor: page.next_cursor, total: page.total ?? null, is_loading_more: false, load_more_error: null });
            },
            (error: unknown) => {
                if (is_current) setSnapshot({ request_key, first: { status: 'error', error: classify(error) }, items: [], tail: [], next_cursor: null, total: null, is_loading_more: false, load_more_error: null });
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
                    ? { ...prev, ...appendPage(prev, page), next_cursor: page.next_cursor, is_loading_more: false }
                    : prev)),
                (error: unknown) => setSnapshot((prev) => (prev?.request_key === request_key ? { ...prev, is_loading_more: false, load_more_error: classify(error) } : prev)),
            )
            .finally(() => {
                if (loading_more_key.current === request_key) loading_more_key.current = null;
            });
    }, [current, request_key, fetchPage, classify]);

    const reload = useCallback(() => setGeneration((value) => value + 1), []);

    const replaceItem = useCallback((item: T) => {
        const swap = (known: T) => (known.id === item.id ? item : known);
        setSnapshot((prev) => (prev?.request_key === request_key ? { ...prev, items: prev.items.map(swap), tail: prev.tail.map(swap) } : prev));
    }, [request_key]);

    const removeItem = useCallback((id: string) => {
        setSnapshot((prev) => {
            if (prev?.request_key !== request_key) return prev;
            const existed = prev.items.some((known) => known.id === id) || prev.tail.some((known) => known.id === id);
            if (!existed) return prev;
            return { ...prev, items: prev.items.filter((known) => known.id !== id), tail: prev.tail.filter((known) => known.id !== id), total: shiftTotal(prev.total, -1) };
        });
    }, [request_key]);

    const insertItem = useCallback((item: T, at: CursorInsertPosition) => {
        setSnapshot((prev) => (prev?.request_key === request_key && prev.first.status === 'success' ? insertIntoSnapshot(prev, item, at) : prev));
    }, [request_key]);

    const items = useMemo(() => (current === null ? [] : current.tail.length === 0 ? current.items : [...current.items, ...current.tail]), [current]);

    if (current === null) {
        return { status: 'loading', items, total: null, has_more: false, is_loading_more: false, error: null, load_more_error: null, loadMore, reload, replaceItem, removeItem, insertItem };
    }
    return {
        status: current.first.status,
        items,
        total: current.total,
        has_more: current.next_cursor !== null,
        is_loading_more: current.is_loading_more,
        error: current.first.status === 'error' ? current.first.error : null,
        load_more_error: current.load_more_error,
        loadMore,
        reload,
        replaceItem,
        removeItem,
        insertItem,
    };
};

export default useCursorList;
