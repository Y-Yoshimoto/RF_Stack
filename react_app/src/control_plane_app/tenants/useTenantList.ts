/**
 * @description:
 * CP のテナント一覧を取得するカスタムフック (カーソル方式の「さらに読み込む」)
 * 絞り込み・並び順が変わるか reload を呼ぶと先頭ページから取り直す。古い取得の結果は捨てる (本体は shared/hooks/useCursorList)。
*/
import { useCpApiClient } from '@/control_plane_app/api/client';
import type { TenantListItem, TenantListQuery } from '@/control_plane_app/api/contract';
import { classifyCpError, type CpErrorInfo } from '@/control_plane_app/api/errors';
import { buildTenantListUrl, fetchTenantPage, toTenantListQuery, type TenantListFilter } from '@/control_plane_app/api/tenants';
import { appendById, useCursorList } from '@/shared/hooks/useCursorList';

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

/**
 * ページを連結する関数 (同じ ID の要素は後から来たもので置き換えず、先に読み込んだものを残す)
 * @param {readonly TenantListItem[]} items 読み込み済みの要素
 * @param {readonly TenantListItem[]} next 次のページの要素
 * @returns {TenantListItem[]} 連結した要素
*/
export const appendTenantItems = (items: readonly TenantListItem[], next: readonly TenantListItem[]): TenantListItem[] => appendById(items, next);

/**
 * CP のテナント一覧を取得するカスタムフック (ControlPlaneAuthProvider の内側で使う)
 * @param {TenantListFilter} filter 絞り込み・並び順・総件数の要否・件数
 * @returns {TenantListState} 一覧の状態と操作
*/
export const useTenantList = (filter: TenantListFilter = {}): TenantListState => {
    const client = useCpApiClient();
    const query: TenantListQuery = toTenantListQuery(filter);
    // 総件数は先頭ページの値を使うため、2 ページ目以降では要求しない
    const { include_total: _, ...rest } = query;
    const { status, items, total, has_more, is_loading_more, error, load_more_error, loadMore, reload } = useCursorList<TenantListItem>({
        query_key: buildTenantListUrl(query),
        fetchPage: (cursor) => fetchTenantPage(client, cursor === null ? query : { ...rest, cursor }),
        classify: classifyCpError,
    });
    return { status, items, total, has_more, is_loading_more, error, load_more_error, loadMore, reload };
};

export default useTenantList;
