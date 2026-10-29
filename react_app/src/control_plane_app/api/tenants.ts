// CP のテナント API (`/api/v1/cp/tenants`) を呼び出す関数
// フック (control_plane_app/tenants/) から使う。ApiClient を引数で受け取り、副作用はそれだけにする (テストで差し替えられる)。
// 一時パスワードを含むレスポンス (作成・再実行) はログに出さないこと。
// ETag / If-Match の部品は shared/api/etag.ts (WithEtag はここから再公開する)。
import type { ApiClient } from '@/shared/api/client';
import { ifMatchHeaders, requestWithEtag, requireBody, type WithEtag } from '@/shared/api/etag';
import {
    CP_API_PATHS,
    type InitialAdminInput,
    type TenantCreate,
    type TenantDetail,
    type TenantListQuery,
    type TenantPage,
    type TenantProvisioned,
    type TenantRead,
    type TenantSortKey,
    type TenantStatus,
} from './contract';

export type { WithEtag } from '@/shared/api/etag';

/**
 * テナントの最新の状態とその ETag (詳細の取得・停止・再開・削除要求の結果)。
 */
export type TenantVersioned<T extends TenantRead = TenantRead> = {
    tenant: T;
    etag: string;
};

/**
 * 楽観ロックの対象 (テナント ID と、保持している ETag)。
 * 一覧の要素から作る場合は `ifMatchOf(item.version)` を etag にする。
 */
export type TenantTarget = {
    tenant_id: string;
    /** 取得済みの ETag。null は未取得 (送信しない。呼び出し側で弾く)。 */
    etag: string | null;
};

/**
 * 一覧の絞り込み・並び順 (画面からの指定)。
 */
export type TenantListFilter = {
    /** 状態の絞り込み。空・省略時は削除済みを含む全件。 */
    status?: readonly TenantStatus[];
    /** 並び順 (省略時はサーバーの既定 `-created_at`)。 */
    sort?: TenantSortKey;
    /** 総件数を取得する (先頭ページのみで要求する)。 */
    include_total?: boolean;
    /** 1 ページの件数 (省略時はサーバーの既定 50。1〜200)。 */
    limit?: number;
};

/**
 * 画面の絞り込みを一覧 API のクエリにする関数 (状態は重複を除いて並べ替え、同じ絞り込みが同じクエリになるようにする)
 * @param {TenantListFilter} filter 絞り込み
 * @returns {TenantListQuery} クエリ (cursor は含まない)
*/
export const toTenantListQuery = (filter: TenantListFilter): TenantListQuery => {
    const statuses = [...new Set(filter.status ?? [])].sort();
    return {
        ...(filter.limit !== undefined ? { limit: filter.limit } : {}),
        ...(filter.include_total ? { include_total: true } : {}),
        ...(filter.sort !== undefined ? { sort: filter.sort } : {}),
        ...(statuses.length > 0 ? { status: statuses.join(',') } : {}),
    };
};

/**
 * 一覧 API の URL を作る関数
 * @param {TenantListQuery} query クエリ
 * @returns {string} URL (クエリが無ければパスのみ)
*/
export const buildTenantListUrl = (query: TenantListQuery): string => {
    const params = new URLSearchParams();
    if (query.limit !== undefined) params.set('limit', String(query.limit));
    if (query.cursor !== undefined) params.set('cursor', query.cursor);
    if (query.include_total) params.set('include_total', 'true');
    if (query.sort !== undefined) params.set('sort', query.sort);
    if (query.status !== undefined && query.status !== '') params.set('status', query.status);
    const search = params.toString();
    return search === '' ? CP_API_PATHS.TENANTS : `${CP_API_PATHS.TENANTS}?${search}`;
};

/**
 * テナント一覧の 1 ページを取得する関数
 * @param {ApiClient} client API クライアント
 * @param {TenantListQuery} query クエリ (2 ページ目以降は cursor を付ける)
 * @returns {Promise<TenantPage>} 1 ページ
*/
export const fetchTenantPage = async (client: ApiClient, query: TenantListQuery): Promise<TenantPage> => {
    const url = buildTenantListUrl(query);
    return requireBody(await client.request<TenantPage>({ url, method: 'GET' }), url);
};

/**
 * テナント詳細 (払い出し履歴を含む) と ETag を取得する関数
 * @param {ApiClient} client API クライアント
 * @param {string} tenant_id テナント ID
 * @returns {Promise<TenantVersioned<TenantDetail>>} 詳細と ETag
*/
export const fetchTenant = async (client: ApiClient, tenant_id: string): Promise<TenantVersioned<TenantDetail>> => {
    const { body, etag } = await requestWithEtag<TenantDetail>(client, { url: CP_API_PATHS.tenant(tenant_id), method: 'GET' }, (tenant) => tenant.version);
    return { tenant: body, etag };
};

/**
 * テナントを作成 (同期払い出し) する関数。201 の本文に一時パスワードが一度だけ含まれる
 * @param {ApiClient} client API クライアント
 * @param {TenantCreate} input 入力
 * @returns {Promise<WithEtag<TenantProvisioned>>} 払い出しの結果と ETag
*/
export const createTenant = (client: ApiClient, input: TenantCreate): Promise<WithEtag<TenantProvisioned>> => {
    return requestWithEtag<TenantProvisioned>(client, { url: CP_API_PATHS.TENANTS, method: 'POST', body: input }, (result) => result.tenant.version);
};

/**
 * 払い出しを再実行する関数。初期管理者は台帳に保存されていないため本文で渡す。一時パスワードは新しい値が一度だけ返る
 * @param {ApiClient} client API クライアント
 * @param {string} tenant_id テナント ID
 * @param {InitialAdminInput} initial_admin 初期管理者
 * @param {string | null} etag 保持している ETag (任意。指定すると不一致で 412)
 * @returns {Promise<WithEtag<TenantProvisioned>>} 払い出しの結果と ETag
*/
export const retryTenantProvisioning = (client: ApiClient, tenant_id: string, initial_admin: InitialAdminInput, etag: string | null = null): Promise<WithEtag<TenantProvisioned>> => {
    return requestWithEtag<TenantProvisioned>(
        client,
        { url: CP_API_PATHS.tenantProvisioningRetry(tenant_id), method: 'POST', body: { initial_admin }, headers: ifMatchHeaders(etag) },
        (result) => result.tenant.version,
    );
};

/**
 * 状態を変える操作 (停止・再開・削除要求) を送る関数。If-Match は必須
 * @param {ApiClient} client API クライアント
 * @param {{ url: string, method: string }} resource_obj URL とメソッド
 * @param {string} etag 保持している ETag
 * @returns {Promise<TenantVersioned>} 更新後のテナントと新しい ETag
*/
const transitTenant = async (client: ApiClient, resource_obj: { url: string; method: 'POST' | 'DELETE' }, etag: string): Promise<TenantVersioned> => {
    const { body, etag: next_etag } = await requestWithEtag<TenantRead>(client, { ...resource_obj, headers: ifMatchHeaders(etag) }, (tenant) => tenant.version);
    return { tenant: body, etag: next_etag };
};

/**
 * テナントを停止する関数
 * @param {ApiClient} client API クライアント
 * @param {string} tenant_id テナント ID
 * @param {string} etag 保持している ETag
 * @returns {Promise<TenantVersioned>} 更新後のテナントと新しい ETag
*/
export const suspendTenant = (client: ApiClient, tenant_id: string, etag: string) => transitTenant(client, { url: CP_API_PATHS.tenantSuspend(tenant_id), method: 'POST' }, etag);

/**
 * テナントを再開する関数
 * @param {ApiClient} client API クライアント
 * @param {string} tenant_id テナント ID
 * @param {string} etag 保持している ETag
 * @returns {Promise<TenantVersioned>} 更新後のテナントと新しい ETag
*/
export const resumeTenant = (client: ApiClient, tenant_id: string, etag: string) => transitTenant(client, { url: CP_API_PATHS.tenantResume(tenant_id), method: 'POST' }, etag);

/**
 * テナントの削除を要求する関数 (PENDING_DELETION にする。物理削除は猶予期間後の定期ジョブ)
 * @param {ApiClient} client API クライアント
 * @param {string} tenant_id テナント ID
 * @param {string} etag 保持している ETag
 * @returns {Promise<TenantVersioned>} 更新後のテナントと新しい ETag
*/
export const requestTenantDeletion = (client: ApiClient, tenant_id: string, etag: string) => transitTenant(client, { url: CP_API_PATHS.tenant(tenant_id), method: 'DELETE' }, etag);
