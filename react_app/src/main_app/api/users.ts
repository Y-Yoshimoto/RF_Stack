// AP のユーザー API (`/api/v1/users`) を呼び出す関数と、入力の組み立て (純粋関数)
// フック (main_app/users/) から使う。ApiClient を引数で受け取り、副作用はそれだけにする (テストで差し替えられる)。
// 一時パスワードを含むレスポンス (作成) はログに出さないこと。
import type { ApiClient } from '@/shared/api/client';
import { ifMatchHeaders, requestWithEtag, requireBody, type WithEtag } from '@/shared/api/etag';
import {
    APP_API_PATHS,
    APP_DEFAULT_ROLES,
    APP_ROLE,
    USER_IDS_QUERY_MAX,
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
    /**
     * ユーザー ID で絞り込む (重複を除いて最大 USER_IDS_QUERY_MAX 件。超えると 422)。空の配列は 0 件。省略時は絞り込まない。
     * 上限を超える可能性がある場合は useUsersByIds (分割して取得する) を使う。
     */
    ids?: readonly string[];
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

/** UUID の形式 (API の ids は UUID 以外を含むと全体が 422 になるため、送る前に除く) */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * ユーザー ID の重複と空文字を除く関数 (最初に現れた順を保つ)
 * @param {readonly string[]} user_ids ユーザー ID
 * @returns {string[]} 重複を除いた ID
*/
export const uniqueUserIdsOf = (user_ids: readonly string[]): string[] => [...new Set(user_ids.map((id) => id.trim()).filter((id) => id !== ''))];

/**
 * ユーザー ID を、API に送れるもの (UUID) と送れないものに分ける関数 (重複と空文字は除く)
 * @param {readonly string[]} user_ids ユーザー ID
 * @returns {{ ids: string[]; invalid_ids: string[] }} 送れる ID と、UUID でない ID (どちらも最初に現れた順)
*/
export const partitionUserIds = (user_ids: readonly string[]): { ids: string[]; invalid_ids: string[] } => {
    const unique = uniqueUserIdsOf(user_ids);
    return { ids: unique.filter((id) => UUID_PATTERN.test(id)), invalid_ids: unique.filter((id) => !UUID_PATTERN.test(id)) };
};

/**
 * ユーザー ID を、ids クエリの上限ごとに分ける関数
 * @param {readonly string[]} user_ids ユーザー ID (重複を除いたもの)
 * @param {number} size 1 回の件数 (既定 USER_IDS_QUERY_MAX)
 * @returns {string[][]} 分けた ID (空なら空の配列)
*/
export const chunkUserIds = (user_ids: readonly string[], size: number = USER_IDS_QUERY_MAX): string[][] => {
    const chunks: string[][] = [];
    for (let start = 0; start < user_ids.length; start += size) chunks.push(user_ids.slice(start, start + size));
    return chunks;
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
    ...(filter.ids !== undefined ? { ids: uniqueUserIdsOf(filter.ids).join(',') } : {}),
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
    // 空文字も送る (`ids=` は 0 件。省略すると絞り込まない)
    if (query.ids !== undefined) params.set('ids', query.ids);
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
 * 更新の応答のロールが、送ったロールの集合と一致するかを判定する関数
 * 応答のロールは写し (直接付与 + 既定ロール) で、IdP 上で変化が無かった場合は写しを書き換えない。
 * 写しが IdP と食い違っていた (IdP 側で直接変更された等) 場合は一致しないため、呼び出し側は詳細を取り直す。
 * @param {readonly AppRole[]} requested 送ったロール
 * @param {readonly AppRole[]} actual 応答のロール
 * @returns {boolean} 送ったロールをすべて含み、それ以外は既定ロールだけなら true
*/
export const rolesMatchRequest = (requested: readonly AppRole[], actual: readonly AppRole[]): boolean => {
    return requested.every((role) => actual.includes(role)) && actual.every((role) => requested.includes(role) || APP_DEFAULT_ROLES.includes(role));
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
 * ID を指定してユーザーを取得する関数 (名前の解決用)
 * - 重複・空文字・UUID でない ID は送らない (UUID でない値を含むと全体が 422 になるため)
 * - USER_IDS_QUERY_MAX 件ずつに分けて並行に取得し、各回は next_cursor が無くなるまで続きを取得する
 * - 存在しない ID・他テナントの ID は結果に含まれない (呼び出し側で「不明なユーザー」として扱う)
 * どれか 1 回でも失敗すれば reject する (一部だけの結果は返さない)。
 * @param {ApiClient} client API クライアント
 * @param {readonly string[]} user_ids ユーザー ID
 * @returns {Promise<UserRead[]>} 見つかったユーザー (順序は保証しない。同じ ID は 1 件)
*/
export const fetchUsersByIds = async (client: ApiClient, user_ids: readonly string[]): Promise<UserRead[]> => {
    const chunks = chunkUserIds(partitionUserIds(user_ids).ids);
    const pages = await Promise.all(chunks.map(async (chunk) => {
        const items: UserRead[] = [];
        const seen_cursors = new Set<string>();
        let cursor: string | null = null;
        do {
            const query: UserListQuery = { ids: chunk.join(','), limit: USER_IDS_QUERY_MAX, ...(cursor !== null ? { cursor } : {}) };
            const page: UserPage = await fetchUserPage(client, query);
            items.push(...page.items);
            // 同じカーソルが返った場合は打ち切る (無限ループの防止)
            cursor = page.next_cursor !== null && !seen_cursors.has(page.next_cursor) ? page.next_cursor : null;
            if (cursor !== null) seen_cursors.add(cursor);
        } while (cursor !== null);
        return items;
    }));
    return [...new Map(pages.flat().map((user) => [user.id, user])).values()];
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
 * ユーザーを更新する関数。If-Match は必須
 * 応答は UserDetail (変更した項目は IdP に設定した値、変更しない項目の姓・名・ロールは写しの値)。
 * @param {ApiClient} client API クライアント
 * @param {string} user_id ユーザー ID
 * @param {UserUpdate} body 本文 (送った項目だけを更新する)
 * @param {string} etag 保持している ETag
 * @returns {Promise<WithEtag<UserDetail>>} 更新後のユーザーと新しい ETag
*/
export const updateUser = (client: ApiClient, user_id: string, body: UserUpdate, etag: string): Promise<WithEtag<UserDetail>> => {
    return requestWithEtag<UserDetail>(client, { url: APP_API_PATHS.user(user_id), method: 'PATCH', body, headers: ifMatchHeaders(etag) }, (user) => user.version);
};
