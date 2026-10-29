// AP の ToDo API (`/api/v1/todos`) を呼び出す関数と、一覧のクエリの組み立て (純粋関数)
// フック (main_app/todos/) から使う。ApiClient を引数で受け取り、副作用はそれだけにする (テストで差し替えられる)。
// 変更内容の差分・権限の事前確認は main_app/todos/todo_changes.ts。
import type { ApiClient } from '@/shared/api/client';
import { ifMatchHeaders, requestWithEtag, requireBody, type WithEtag } from '@/shared/api/etag';
import {
    APP_API_PATHS,
    TODO_DEFAULTS,
    TODO_LIMITS,
    TODO_PRIORITIES,
    TODO_STATUSES,
    type TodoActivityListQuery,
    type TodoActivityPage,
    type TodoCreate,
    type TodoDetail,
    type TodoListQuery,
    type TodoPage,
    type TodoPriority,
    type TodoScope,
    type TodoSortKey,
    type TodoStatus,
    type TodoSummary,
    type TodoSummaryQuery,
    type TodoUpdate,
} from './contract';

/**
 * 一覧の表示範囲・絞り込み・並び順 (画面からの指定)。URL のクエリとの相互変換は main_app/todos/list_search.ts。
 */
export type TodoListFilter = {
    /** 表示範囲 (省略時は `all`)。 */
    scope?: TodoScope;
    /** ステータス (複数可。空・省略は絞り込まない)。 */
    status?: readonly TodoStatus[];
    /** 優先度 (複数可。空・省略は絞り込まない)。 */
    priority?: readonly TodoPriority[];
    /** タイトルの部分一致 (前後の空白は除く。空は絞り込まない。最大 200 文字)。 */
    q?: string;
    /** 公開先に含まれる組織 ID。 */
    organization_id?: string;
    /** 担当者に含まれるユーザー ID。 */
    assignee_id?: string;
    /** 期限がこの日以前 (`YYYY-MM-DD`。この日を含む。期限なしは除く)。 */
    due_before?: string;
    /** 期限がこの日以降 (`YYYY-MM-DD`。この日を含む。期限なしは除く)。 */
    due_after?: string;
    /** 並び順 (キーは 1 つ。省略時は `-created_at`)。 */
    sort?: TodoSortKey;
    /** 1 ページの件数 (省略時はサーバーの既定 50。1〜200)。 */
    limit?: number;
};

/**
 * 値の並びを、既定の順序に揃えて重複を除く関数
 * @param {readonly T[]} values 値
 * @param {readonly T[]} order 既定の順序
 * @returns {T[]} 揃えた値
*/
const orderedUnique = <T,>(values: readonly T[], order: readonly T[]): T[] => order.filter((value) => values.includes(value));

/**
 * 空文字を undefined にする関数
 * @param {string | undefined} value 値
 * @returns {string | undefined} 空でなければ値
*/
const nonEmpty = (value: string | undefined): string | undefined => (value === '' ? undefined : value);

/**
 * 値が undefined の項目を除く関数
 * @param {T} value オブジェクト
 * @returns {T} undefined の項目を除いたオブジェクト
*/
const compact = <T extends object,>(value: T): T => Object.fromEntries(Object.entries(value).filter(([, item]) => item !== undefined)) as T;

/**
 * 絞り込みを正規化する関数 (同じ意味の指定を同じ形にする)
 * - ステータス・優先度は重複を除いて既定の順にし、空なら省く
 * - q は前後の空白を除いて最大 200 文字にし、空なら省く。空文字の ID・日付は省く
 * - サーバーの既定値 (scope: all、sort: -created_at) は省く
 * @param {TodoListFilter} filter 絞り込み
 * @returns {TodoListFilter} 正規化した絞り込み
*/
export const normalizeTodoListFilter = (filter: TodoListFilter): TodoListFilter => {
    const status = orderedUnique(filter.status ?? [], TODO_STATUSES);
    const priority = orderedUnique(filter.priority ?? [], TODO_PRIORITIES);
    return compact<TodoListFilter>({
        scope: filter.scope === TODO_DEFAULTS.SCOPE ? undefined : filter.scope,
        status: status.length > 0 ? status : undefined,
        priority: priority.length > 0 ? priority : undefined,
        q: nonEmpty((filter.q ?? '').trim().slice(0, TODO_LIMITS.QUERY_MAX)),
        organization_id: nonEmpty(filter.organization_id),
        assignee_id: nonEmpty(filter.assignee_id),
        due_before: nonEmpty(filter.due_before),
        due_after: nonEmpty(filter.due_after),
        sort: filter.sort === TODO_DEFAULTS.SORT ? undefined : filter.sort,
        limit: filter.limit,
    });
};

/**
 * 画面の絞り込みを一覧 API のクエリにする関数 (正規化してから、複数値はカンマ区切りにする)
 * @param {TodoListFilter} filter 絞り込み
 * @returns {TodoListQuery} クエリ (cursor は含まない)
*/
export const toTodoListQuery = (filter: TodoListFilter): TodoListQuery => {
    const { status, priority, ...rest } = normalizeTodoListFilter(filter);
    return {
        ...rest,
        ...(status !== undefined ? { status: status.join(',') } : {}),
        ...(priority !== undefined ? { priority: priority.join(',') } : {}),
    };
};

/** URL に載せるクエリの順序 (同じ指定が同じ URL・キーになるよう固定する) */
const TODO_LIST_QUERY_ORDER: readonly (keyof TodoListQuery)[] = ['limit', 'cursor', 'scope', 'status', 'priority', 'q', 'organization_id', 'assignee_id', 'due_before', 'due_after', 'sort', 'include_total'];

/**
 * 一覧 API の URL を作る関数
 * @param {TodoListQuery} query クエリ
 * @returns {string} URL (クエリが無ければパスのみ)
*/
export const buildTodoListUrl = (query: TodoListQuery): string => {
    const params = new URLSearchParams();
    for (const key of TODO_LIST_QUERY_ORDER) {
        const value = query[key];
        // include_total は true のときだけ送る (false はサーバーの既定と同じ)
        if (value !== undefined && value !== false) params.set(key, String(value));
    }
    const search = params.toString();
    return search === '' ? APP_API_PATHS.TODOS : `${APP_API_PATHS.TODOS}?${search}`;
};

/**
 * ToDo 一覧の 1 ページを取得する関数
 * @param {ApiClient} client API クライアント
 * @param {TodoListQuery} query クエリ (2 ページ目以降は cursor を付ける)
 * @returns {Promise<TodoPage>} 1 ページ
*/
export const fetchTodoPage = async (client: ApiClient, query: TodoListQuery): Promise<TodoPage> => {
    const url = buildTodoListUrl(query);
    return requireBody(await client.request<TodoPage>({ url, method: 'GET' }), url);
};

const versionOf = (todo: TodoDetail): number => todo.version;

/**
 * ToDo の詳細 (説明・permissions を含む) と ETag を取得する関数
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @returns {Promise<WithEtag<TodoDetail>>} 詳細と ETag
*/
export const fetchTodo = (client: ApiClient, todo_id: string): Promise<WithEtag<TodoDetail>> => {
    return requestWithEtag<TodoDetail>(client, { url: APP_API_PATHS.todo(todo_id), method: 'GET' }, versionOf);
};

/**
 * ToDo を作成する関数 (作成者は操作者)
 * @param {ApiClient} client API クライアント
 * @param {TodoCreate} input 入力
 * @returns {Promise<WithEtag<TodoDetail>>} 作成した ToDo と ETag
*/
export const createTodo = (client: ApiClient, input: TodoCreate): Promise<WithEtag<TodoDetail>> => {
    return requestWithEtag<TodoDetail>(client, { url: APP_API_PATHS.TODOS, method: 'POST', body: input }, versionOf);
};

/**
 * ToDo を更新する関数 (送った項目だけ)。If-Match は必須
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {TodoUpdate} body 本文
 * @param {string} etag 保持している ETag
 * @returns {Promise<WithEtag<TodoDetail>>} 更新後の ToDo と新しい ETag
*/
export const updateTodo = (client: ApiClient, todo_id: string, body: TodoUpdate, etag: string): Promise<WithEtag<TodoDetail>> => {
    return requestWithEtag<TodoDetail>(client, { url: APP_API_PATHS.todo(todo_id), method: 'PATCH', body, headers: ifMatchHeaders(etag) }, versionOf);
};

/**
 * ToDo の担当者を置き換える関数 (全置換。重複は除いて送る)。If-Match は必須
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {readonly string[]} user_ids 担当者にするユーザー ID の全件 (空配列で全員を外す)
 * @param {string} etag 保持している ETag
 * @returns {Promise<WithEtag<TodoDetail>>} 置き換え後の ToDo と新しい ETag
*/
export const replaceTodoAssignees = (client: ApiClient, todo_id: string, user_ids: readonly string[], etag: string): Promise<WithEtag<TodoDetail>> => {
    return requestWithEtag<TodoDetail>(
        client,
        { url: APP_API_PATHS.todoAssignees(todo_id), method: 'PUT', body: { user_ids: [...new Set(user_ids)] }, headers: ifMatchHeaders(etag) },
        versionOf,
    );
};

/**
 * 204 の応答を読む関数 (本文は無い。requestFetch の既定の takeData は JSON を読むため差し替える)
 * @returns {Promise<true>} 常に true
*/
export const takeNoContent = async (): Promise<true> => true;

/**
 * ToDo を削除する関数 (論理削除。204)。If-Match は必須
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {string} etag 保持している ETag
*/
export const deleteTodo = async (client: ApiClient, todo_id: string, etag: string): Promise<void> => {
    await client.request<true>({ url: APP_API_PATHS.todo(todo_id), method: 'DELETE', headers: ifMatchHeaders(etag), takeData: takeNoContent });
};

/**
 * アクティビティ一覧 API の URL を作る関数
 * @param {string} todo_id ToDo ID
 * @param {TodoActivityListQuery} query クエリ
 * @returns {string} URL
*/
export const buildTodoActivitiesUrl = (todo_id: string, query: TodoActivityListQuery): string => {
    const params = new URLSearchParams();
    if (query.limit !== undefined) params.set('limit', String(query.limit));
    if (query.cursor !== undefined) params.set('cursor', query.cursor);
    const search = params.toString();
    const path = APP_API_PATHS.todoActivities(todo_id);
    return search === '' ? path : `${path}?${search}`;
};

/**
 * アクティビティ (新しい順) の 1 ページを取得する関数
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {TodoActivityListQuery} query クエリ (2 ページ目以降は cursor を付ける)
 * @returns {Promise<TodoActivityPage>} 1 ページ
*/
export const fetchTodoActivityPage = async (client: ApiClient, todo_id: string, query: TodoActivityListQuery): Promise<TodoActivityPage> => {
    const url = buildTodoActivitiesUrl(todo_id, query);
    return requireBody(await client.request<TodoActivityPage>({ url, method: 'GET' }), url);
};

/**
 * ホームの要約 API の URL を作る関数
 * @param {TodoSummaryQuery} query クエリ (today は `YYYY-MM-DD`)
 * @returns {string} URL
*/
export const buildTodoSummaryUrl = (query: TodoSummaryQuery): string => {
    const params = new URLSearchParams();
    if (query.today !== undefined) params.set('today', query.today);
    if (query.due_soon_days !== undefined) params.set('due_soon_days', String(query.due_soon_days));
    const search = params.toString();
    return search === '' ? APP_API_PATHS.TODO_SUMMARY : `${APP_API_PATHS.TODO_SUMMARY}?${search}`;
};

/**
 * ホームの要約 (自分が担当・作成した未完了の件数) を取得する関数 (AP-UX-01)
 * @param {ApiClient} client API クライアント
 * @param {TodoSummaryQuery} query クエリ (today はクライアントのローカル日付を渡す。§10 #21)
 * @returns {Promise<TodoSummary>} 要約
*/
export const fetchTodoSummary = async (client: ApiClient, query: TodoSummaryQuery): Promise<TodoSummary> => {
    const url = buildTodoSummaryUrl(query);
    return requireBody(await client.request<TodoSummary>({ url, method: 'GET' }), url);
};
