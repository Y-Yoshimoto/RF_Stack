/**
 * @description:
 * CP のテナント一覧を取得するカスタムフック (カーソル方式の「さらに読み込む」)
 * 絞り込み・並び順が変わるか reload を呼ぶと先頭ページから取り直す。古い取得の結果は捨てる。
*/
import { useCallback, useEffect, useRef, useState } from 'react';
import { useCpApiClient } from '@/control_plane_app/api/client';
import type { TenantListItem, TenantListQuery, TenantPage } from '@/control_plane_app/api/contract';
import { classifyCpError, type CpErrorInfo } from '@/control_plane_app/api/errors';
import { buildTenantListUrl, fetchTenantPage, toTenantListQuery, type TenantListFilter } from '@/control_plane_app/api/tenants';

/**
 * テナント一覧の状態と操作。
 */
export type TenantListState = {
    /** 先頭ページの取得状態。 */
    status: 'loading' | 'success' | 'error';
    /** 読み込み済みの要素 (ページを連結したもの)。 */
    items: TenantListItem[];
    /** 総件数 (include_total を指定した場合のみ。先頭ページの値)。 */
    total: number | null;
    /** 次のページがある。 */
    has_more: boolean;
    /** 次のページを取得中。 */
    is_loading_more: boolean;
    /** 先頭ページの取得失敗 (status === 'error' のとき)。 */
    error: CpErrorInfo | null;
    /** 次のページの取得失敗 (読み込み済みの要素は保持する。requires_reload なら reload で先頭から取り直す)。 */
    load_more_error: CpErrorInfo | null;
    /** 次のページを取得して連結する (取得中・最後のページでは何もしない)。 */
    loadMore: () => void;
    /** 先頭ページから取り直す。 */
    reload: () => void;
};

/** 取得済みの一覧 (どの取得の結果かを request_key で判別する) */
type ListSnapshot = {
    request_key: string;
    first: { status: 'success' } | { status: 'error'; error: CpErrorInfo };
    items: TenantListItem[];
    next_cursor: string | null;
    total: number | null;
    is_loading_more: boolean;
    load_more_error: CpErrorInfo | null;
};

/**
 * ページを連結する関数 (同じ ID の要素は後から来たもので置き換えず、先に読み込んだものを残す)
 * @param {readonly TenantListItem[]} items 読み込み済みの要素
 * @param {readonly TenantListItem[]} next 次のページの要素
 * @returns {TenantListItem[]} 連結した要素
*/
export const appendTenantItems = (items: readonly TenantListItem[], next: readonly TenantListItem[]): TenantListItem[] => {
    const known = new Set(items.map((item) => item.id));
    return [...items, ...next.filter((item) => !known.has(item.id))];
};

/**
 * 先頭ページから一覧の状態を作る関数
 * @param {string} request_key 取得のキー
 * @param {TenantPage} page 先頭ページ
 * @returns {ListSnapshot} 状態
*/
const firstPageSnapshot = (request_key: string, page: TenantPage): ListSnapshot => ({
    request_key,
    first: { status: 'success' },
    items: page.items,
    next_cursor: page.next_cursor,
    total: page.total ?? null,
    is_loading_more: false,
    load_more_error: null,
});

/**
 * CP のテナント一覧を取得するカスタムフック (ControlPlaneAuthProvider の内側で使う)
 * @param {TenantListFilter} filter 絞り込み・並び順・総件数の要否・件数
 * @returns {TenantListState} 一覧の状態と操作
*/
export const useTenantList = (filter: TenantListFilter = {}): TenantListState => {
    const client = useCpApiClient();
    const query: TenantListQuery = toTenantListQuery(filter);
    const [generation, setGeneration] = useState(0);
    const request_key = `${buildTenantListUrl(query)}#${generation}`;
    const [snapshot, setSnapshot] = useState<ListSnapshot | null>(null);
    // 次のページの二重取得を防ぐ (イベントハンドラーからのみ読み書きする)
    const loading_more_key = useRef<string | null>(null);

    useEffect(() => {
        let is_current = true;
        fetchTenantPage(client, query).then(
            (page) => {
                if (is_current) setSnapshot(firstPageSnapshot(request_key, page));
            },
            (error: unknown) => {
                if (is_current) setSnapshot({ request_key, first: { status: 'error', error: classifyCpError(error) }, items: [], next_cursor: null, total: null, is_loading_more: false, load_more_error: null });
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
        // 総件数は先頭ページの値を使うため、2 ページ目以降では要求しない
        const { include_total: _, ...rest } = query;
        fetchTenantPage(client, { ...rest, cursor })
            .then(
                (page) => setSnapshot((prev) => (prev?.request_key === request_key && prev.next_cursor === cursor
                    ? { ...prev, items: appendTenantItems(prev.items, page.items), next_cursor: page.next_cursor, is_loading_more: false }
                    : prev)),
                (error: unknown) => setSnapshot((prev) => (prev?.request_key === request_key ? { ...prev, is_loading_more: false, load_more_error: classifyCpError(error) } : prev)),
            )
            .finally(() => {
                if (loading_more_key.current === request_key) loading_more_key.current = null;
            });
    }, [current, request_key, client]);

    const reload = useCallback(() => setGeneration((value) => value + 1), [setGeneration]);

    if (current === null) {
        return { status: 'loading', items: [], total: null, has_more: false, is_loading_more: false, error: null, load_more_error: null, loadMore, reload };
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
    };
};

export default useTenantList;
