// AP のユーザー API (`/api/v1/users`) を呼び出す関数と、入力の組み立て (純粋関数)
// フック (main_app/users/) から使う。ApiClient を引数で受け取り、副作用はそれだけにする (テストで差し替えられる)。
// 一時パスワードを含むレスポンス (作成) はログに出さないこと。
import type { ApiClient } from '@/shared/api/client';
import { ifMatchHeaders, requestWithEtag, requireBody, type WithEtag } from '@/shared/api/etag';
import {
    APP_API_PATHS,
    APP_ROLE,
    type AppRole,
    type SelfModificationOperation,
    type UserCreate,
    type UserCreated,
    type UserDetail,
    type UserListQuery,
    type UserPage,
    type UserRead,
    type UserSortKey,
    type UserUpdate,
} from './contract';

/**
 * 一覧の絞り込み・並び順 (画面からの指定)。
 */
export type UserListFilter = {
    /** 並び順 (省略時はサーバーの既定 `display_name`)。 */
    sort?: UserSortKey;
    /** true で有効なユーザーのみ、false で無効化されたユーザーのみ。省略時は両方。 */
    is_active?: boolean;
    /** 1 ページの件数 (省略時はサーバーの既定 50。1〜200)。 */
    limit?: number;
};

/**
 * 楽観ロックの対象 (ユーザー ID と、保持している ETag)。
 * 一覧の要素から作る場合は `ifMatchOf(item.version)` を etag にする。
 */
export type UserTarget = {
    user_id: string;
    /** 取得済みの ETag。null は未取得 (送信しない。フックが API を呼ばずに弾く)。 */
    etag: string | null;
};

/**
 * ユーザーの変更内容 (画面からの指定)。指定した項目だけを送る。
 */
export type UserChanges = {
    /** 姓・名 (両方を指定する。表示名は `"{名} {姓}"` になる)。 */
    name?: { first_name: string; last_name: string };
    /** ロールの集合 (置き換え。1 件以上)。 */
    roles?: readonly AppRole[];
    /** false で無効化、true で再有効化。 */
    is_active?: boolean;
};

/**
 * 画面の絞り込みを一覧 API のクエリにする関数
 * @param {UserListFilter} filter 絞り込み
 * @returns {UserListQuery} クエリ (cursor は含まない)
*/
export const toUserListQuery = (filter: UserListFilter): UserListQuery => ({
    ...(filter.limit !== undefined ? { limit: filter.limit } : {}),
    ...(filter.sort !== undefined ? { sort: filter.sort } : {}),
    ...(filter.is_active !== undefined ? { is_active: filter.is_active } : {}),
});

/**
 * 一覧 API の URL を作る関数
 * @param {UserListQuery} query クエリ
 * @returns {string} URL (クエリが無ければパスのみ)
*/
export const buildUserListUrl = (query: UserListQuery): string => {
    const params = new URLSearchParams();
    if (query.limit !== undefined) params.set('limit', String(query.limit));
    if (query.cursor !== undefined) params.set('cursor', query.cursor);
    if (query.sort !== undefined) params.set('sort', query.sort);
    if (query.is_active !== undefined) params.set('is_active', String(query.is_active));
    const search = params.toString();
    return search === '' ? APP_API_PATHS.USERS : `${APP_API_PATHS.USERS}?${search}`;
};

/**
 * 変更内容を PATCH の本文にする関数 (指定した項目だけを入れる。null は入れない)
 * @param {UserChanges} changes 変更内容
 * @returns {UserUpdate} 本文
*/
export const toUserUpdate = (changes: UserChanges): UserUpdate => ({
    ...(changes.name !== undefined ? { first_name: changes.name.first_name, last_name: changes.name.last_name } : {}),
    ...(changes.roles !== undefined ? { roles: [...new Set(changes.roles)] } : {}),
    ...(changes.is_active !== undefined ? { is_active: changes.is_active } : {}),
});

/**
 * 自分自身に対して拒否される変更かを判定する関数 (API の 409 user_self_modification_forbidden と同じ条件)
 * 画面はボタンの無効化に、フックは API を呼ぶ前の確認に使う。
 * @param {string} target_user_id 変更するユーザーの ID
 * @param {string | null} self_user_id 自分の ID (`/api/v1/me` の user.id。未取得なら null で、判定しない)
 * @param {UserChanges} changes 変更内容
 * @returns {SelfModificationOperation | null} 拒否される操作 (無ければ null)
*/
export const selfModificationOf = (target_user_id: string, self_user_id: string | null, changes: UserChanges): SelfModificationOperation | null => {
    if (self_user_id === null || target_user_id !== self_user_id) return null;
    if (changes.is_active === false) return 'deactivate';
    if (changes.roles !== undefined && !changes.roles.includes(APP_ROLE.TENANT_ADMIN)) return 'remove_tenant_admin';
    return null;
};

/**
 * ユーザー一覧の 1 ページを取得する関数
 * @param {ApiClient} client API クライアント
 * @param {UserListQuery} query クエリ (2 ページ目以降は cursor を付ける)
 * @returns {Promise<UserPage>} 1 ページ
*/
export const fetchUserPage = async (client: ApiClient, query: UserListQuery): Promise<UserPage> => {
    const url = buildUserListUrl(query);
    return requireBody(await client.request<UserPage>({ url, method: 'GET' }), url);
};

/**
 * ユーザー詳細 (ロールを含む) と ETag を取得する関数
 * @param {ApiClient} client API クライアント
 * @param {string} user_id ユーザー ID
 * @returns {Promise<WithEtag<UserDetail>>} 詳細と ETag
*/
export const fetchUser = (client: ApiClient, user_id: string): Promise<WithEtag<UserDetail>> => {
    return requestWithEtag<UserDetail>(client, { url: APP_API_PATHS.user(user_id), method: 'GET' }, (user) => user.version);
};

/**
 * ユーザーを作成する関数。201 の本文に一時パスワードが一度だけ含まれる
 * @param {ApiClient} client API クライアント
 * @param {UserCreate} input 入力
 * @returns {Promise<WithEtag<UserCreated>>} 作成したユーザー・一時パスワードと ETag
*/
export const createUser = (client: ApiClient, input: UserCreate): Promise<WithEtag<UserCreated>> => {
    return requestWithEtag<UserCreated>(client, { url: APP_API_PATHS.USERS, method: 'POST', body: input }, (result) => result.user.version);
};

/**
 * ユーザーを更新する関数。If-Match は必須。応答にロールは含まれない
 * @param {ApiClient} client API クライアント
 * @param {string} user_id ユーザー ID
 * @param {UserUpdate} body 本文 (送った項目だけを更新する)
 * @param {string} etag 保持している ETag
 * @returns {Promise<WithEtag<UserRead>>} 更新後のユーザーと新しい ETag
*/
export const updateUser = (client: ApiClient, user_id: string, body: UserUpdate, etag: string): Promise<WithEtag<UserRead>> => {
    return requestWithEtag<UserRead>(client, { url: APP_API_PATHS.user(user_id), method: 'PATCH', body, headers: ifMatchHeaders(etag) }, (user) => user.version);
};
