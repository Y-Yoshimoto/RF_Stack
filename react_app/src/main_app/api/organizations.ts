// AP の組織 API (`/api/v1/organizations`) を呼び出す関数
// フック (main_app/organizations/) から使う。ApiClient を引数で受け取り、副作用はそれだけにする (テストで差し替えられる)。
import type { ApiClient } from '@/shared/api/client';
import { ifMatchHeaders, requestWithEtag, requireBody, type WithEtag } from '@/shared/api/etag';
import {
    APP_API_PATHS,
    type OrganizationCreate,
    type OrganizationDetail,
    type OrganizationListQuery,
    type OrganizationPage,
    type OrganizationRead,
    type OrganizationSortKey,
    type OrganizationUpdate,
} from './contract';

/**
 * 一覧の並び順 (画面からの指定)。
 */
export type OrganizationListFilter = {
    /** 並び順 (省略時はサーバーの既定 `name`)。 */
    sort?: OrganizationSortKey;
    /** 1 ページの件数 (省略時はサーバーの既定 50。1〜200)。 */
    limit?: number;
};

/**
 * 楽観ロックの対象 (組織 ID と、保持している ETag)。
 * 一覧の要素から作る場合は `ifMatchOf(item.version)` を etag にする。
 */
export type OrganizationTarget = {
    organization_id: string;
    /** 取得済みの ETag。null は未取得 (送信しない。フックが API を呼ばずに弾く)。 */
    etag: string | null;
};

/**
 * 画面の指定を一覧 API のクエリにする関数
 * @param {OrganizationListFilter} filter 並び順・件数
 * @returns {OrganizationListQuery} クエリ (cursor は含まない)
*/
export const toOrganizationListQuery = (filter: OrganizationListFilter): OrganizationListQuery => ({
    ...(filter.limit !== undefined ? { limit: filter.limit } : {}),
    ...(filter.sort !== undefined ? { sort: filter.sort } : {}),
});

/**
 * 一覧 API の URL を作る関数
 * @param {OrganizationListQuery} query クエリ
 * @returns {string} URL (クエリが無ければパスのみ)
*/
export const buildOrganizationListUrl = (query: OrganizationListQuery): string => {
    const params = new URLSearchParams();
    if (query.limit !== undefined) params.set('limit', String(query.limit));
    if (query.cursor !== undefined) params.set('cursor', query.cursor);
    if (query.sort !== undefined) params.set('sort', query.sort);
    const search = params.toString();
    return search === '' ? APP_API_PATHS.ORGANIZATIONS : `${APP_API_PATHS.ORGANIZATIONS}?${search}`;
};

/**
 * 組織一覧の 1 ページを取得する関数
 * @param {ApiClient} client API クライアント
 * @param {OrganizationListQuery} query クエリ (2 ページ目以降は cursor を付ける)
 * @returns {Promise<OrganizationPage>} 1 ページ
*/
export const fetchOrganizationPage = async (client: ApiClient, query: OrganizationListQuery): Promise<OrganizationPage> => {
    const url = buildOrganizationListUrl(query);
    return requireBody(await client.request<OrganizationPage>({ url, method: 'GET' }), url);
};

/**
 * 組織の詳細 (メンバーのユーザー ID を含む) と ETag を取得する関数
 * @param {ApiClient} client API クライアント
 * @param {string} organization_id 組織 ID
 * @returns {Promise<WithEtag<OrganizationDetail>>} 詳細と ETag
*/
export const fetchOrganization = (client: ApiClient, organization_id: string): Promise<WithEtag<OrganizationDetail>> => {
    return requestWithEtag<OrganizationDetail>(client, { url: APP_API_PATHS.organization(organization_id), method: 'GET' }, (organization) => organization.version);
};

/**
 * 組織を作成する関数 (メンバーは空)
 * @param {ApiClient} client API クライアント
 * @param {OrganizationCreate} input 入力
 * @returns {Promise<WithEtag<OrganizationDetail>>} 作成した組織と ETag
*/
export const createOrganization = (client: ApiClient, input: OrganizationCreate): Promise<WithEtag<OrganizationDetail>> => {
    return requestWithEtag<OrganizationDetail>(client, { url: APP_API_PATHS.ORGANIZATIONS, method: 'POST', body: input }, (organization) => organization.version);
};

/**
 * 組織名を変更する関数。If-Match は必須。応答にメンバーは含まれない
 * @param {ApiClient} client API クライアント
 * @param {string} organization_id 組織 ID
 * @param {OrganizationUpdate} input 入力
 * @param {string} etag 保持している ETag
 * @returns {Promise<WithEtag<OrganizationRead>>} 更新後の組織と新しい ETag
*/
export const updateOrganization = (client: ApiClient, organization_id: string, input: OrganizationUpdate, etag: string): Promise<WithEtag<OrganizationRead>> => {
    return requestWithEtag<OrganizationRead>(
        client,
        { url: APP_API_PATHS.organization(organization_id), method: 'PATCH', body: input, headers: ifMatchHeaders(etag) },
        (organization) => organization.version,
    );
};

/**
 * 組織のメンバーを置き換える関数 (全置換。重複は除いて送る)。If-Match は必須
 * @param {ApiClient} client API クライアント
 * @param {string} organization_id 組織 ID
 * @param {readonly string[]} user_ids メンバーにするユーザー ID の全件 (空配列で全員を外す)
 * @param {string} etag 保持している ETag
 * @returns {Promise<WithEtag<OrganizationDetail>>} 置き換え後の組織と新しい ETag
*/
export const replaceOrganizationMembers = (client: ApiClient, organization_id: string, user_ids: readonly string[], etag: string): Promise<WithEtag<OrganizationDetail>> => {
    return requestWithEtag<OrganizationDetail>(
        client,
        { url: APP_API_PATHS.organizationMembers(organization_id), method: 'PUT', body: { user_ids: [...new Set(user_ids)] }, headers: ifMatchHeaders(etag) },
        (organization) => organization.version,
    );
};

/**
 * 204 の応答を読む関数 (本文は無い。requestFetch の既定の takeData は JSON を読むため差し替える)
 * @returns {Promise<true>} 常に true
*/
const takeNoContent = async (): Promise<true> => true;

/**
 * 組織を削除する関数 (論理削除。204)。If-Match は必須
 * @param {ApiClient} client API クライアント
 * @param {string} organization_id 組織 ID
 * @param {string} etag 保持している ETag
*/
export const deleteOrganization = async (client: ApiClient, organization_id: string, etag: string): Promise<void> => {
    await client.request<true>({ url: APP_API_PATHS.organization(organization_id), method: 'DELETE', headers: ifMatchHeaders(etag), takeData: takeNoContent });
};
