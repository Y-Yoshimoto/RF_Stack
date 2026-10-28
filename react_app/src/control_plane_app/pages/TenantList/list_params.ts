// テナント一覧の絞り込み・並び順と URL のクエリ (`?status=ACTIVE&sort=name`) の対応 (純粋関数)
// URL に持たせることで、ダッシュボードからの絞り込み付きの遷移・再読み込み・共有ができる。
import type { TenantSortKey, TenantStatus } from '@/control_plane_app/api/contract';
import { TENANT_STATUSES } from '@/control_plane_app/components/tenant_labels';

/** 並び順の既定 (API の既定と同じ) */
export const DEFAULT_TENANT_SORT: TenantSortKey = '-created_at';

/** 並べ替えできる列 */
export type SortableColumn = 'tenant_code' | 'name' | 'created_at';

const SORT_KEYS: readonly TenantSortKey[] = ['created_at', '-created_at', 'tenant_code', '-tenant_code', 'name', '-name'];

/**
 * 一覧の画面の条件。
 */
export type TenantListParams = {
    /** 状態の絞り込み (null は全件)。 */
    status: TenantStatus | null;
    sort: TenantSortKey;
};

/**
 * URL のクエリから一覧の条件を取り出す関数 (不正な値は無視して既定にする)
 * @param {URLSearchParams} search クエリ
 * @returns {TenantListParams} 条件
*/
export const parseTenantListParams = (search: URLSearchParams): TenantListParams => {
    const status = TENANT_STATUSES.find((item) => item === search.get('status')) ?? null;
    const sort = SORT_KEYS.find((item) => item === search.get('sort')) ?? DEFAULT_TENANT_SORT;
    return { status, sort };
};

/**
 * 一覧の条件を URL のクエリにする関数 (既定の値は含めない)
 * @param {TenantListParams} params 条件
 * @returns {URLSearchParams} クエリ
*/
export const buildTenantListSearch = (params: TenantListParams): URLSearchParams => {
    const search = new URLSearchParams();
    if (params.status !== null) search.set('status', params.status);
    if (params.sort !== DEFAULT_TENANT_SORT) search.set('sort', params.sort);
    return search;
};

/**
 * 列の見出しを押したときの次の並び順を返す関数 (同じ列なら昇順と降順を入れ替え、別の列なら昇順から)
 * @param {TenantSortKey} current 現在の並び順
 * @param {SortableColumn} column 押した列
 * @returns {TenantSortKey} 次の並び順
*/
export const nextTenantSort = (current: TenantSortKey, column: SortableColumn): TenantSortKey => (current === column ? `-${column}` : column);

/**
 * 並び順から、列と向きを求める関数
 * @param {TenantSortKey} sort 並び順
 * @returns {{ column: SortableColumn, direction: 'asc' | 'desc' }} 列と向き
*/
export const sortColumnOf = (sort: TenantSortKey): { column: SortableColumn; direction: 'asc' | 'desc' } => {
    const direction = sort.startsWith('-') ? 'desc' : 'asc';
    return { column: sort.replace(/^-/, '') as SortableColumn, direction };
};
