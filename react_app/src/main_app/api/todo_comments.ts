// ToDo のコメント API (`/api/v1/todos/{todo_id}/comments`。AP-CMT) を呼び出す関数
// - 一覧は古い順のカーソル方式 (§10 #19)。投稿 (201) と編集 (200) はコメント (TodoCommentRead) と ETag (コメントの版) を返す
// - 編集・削除の If-Match はコメントの版 (一覧の要素の version から ifMatchOf で作る)。不一致は 412 todo_comment_version_conflict
// - コメントの変更は ToDo 本体の版・ETag を変えない (§10 #16)
// フック (main_app/todos/useTodoComments.ts) から使う。ApiClient を引数で受け取り、副作用はそれだけにする。
import type { ApiClient } from '@/shared/api/client';
import { ifMatchHeaders, requestWithEtag, requireBody, type WithEtag } from '@/shared/api/etag';
import { APP_API_PATHS, type TodoCommentListQuery, type TodoCommentPage, type TodoCommentRead, type TodoCommentWrite } from './contract';
import { takeNoContent } from './todos';

const versionOf = (comment: TodoCommentRead): number => comment.version;

/**
 * コメント一覧 API の URL を作る関数
 * @param {string} todo_id ToDo ID
 * @param {TodoCommentListQuery} query クエリ
 * @returns {string} URL
*/
export const buildTodoCommentsUrl = (todo_id: string, query: TodoCommentListQuery): string => {
    const params = new URLSearchParams();
    if (query.limit !== undefined) params.set('limit', String(query.limit));
    if (query.cursor !== undefined) params.set('cursor', query.cursor);
    const search = params.toString();
    const path = APP_API_PATHS.todoComments(todo_id);
    return search === '' ? path : `${path}?${search}`;
};

/**
 * コメント (古い順) の 1 ページを取得する関数
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {TodoCommentListQuery} query クエリ (2 ページ目以降は cursor を付ける)
 * @returns {Promise<TodoCommentPage>} 1 ページ
*/
export const fetchTodoCommentPage = async (client: ApiClient, todo_id: string, query: TodoCommentListQuery): Promise<TodoCommentPage> => {
    const url = buildTodoCommentsUrl(todo_id, query);
    return requireBody(await client.request<TodoCommentPage>({ url, method: 'GET' }), url);
};

/**
 * コメントを投稿する関数 (201)
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {TodoCommentWrite} body 本文
 * @returns {Promise<WithEtag<TodoCommentRead>>} 投稿したコメントと ETag (コメントの版)
*/
export const createTodoComment = (client: ApiClient, todo_id: string, body: TodoCommentWrite): Promise<WithEtag<TodoCommentRead>> => {
    return requestWithEtag<TodoCommentRead>(client, { url: APP_API_PATHS.todoComments(todo_id), method: 'POST', body }, versionOf);
};

/**
 * コメントの本文を編集する関数 (投稿者のみ)。If-Match は必須 (コメントの版)
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {string} comment_id コメント ID
 * @param {TodoCommentWrite} body 本文
 * @param {string} etag コメントの ETag
 * @returns {Promise<WithEtag<TodoCommentRead>>} 編集後のコメントと新しい ETag
*/
export const updateTodoComment = (client: ApiClient, todo_id: string, comment_id: string, body: TodoCommentWrite, etag: string): Promise<WithEtag<TodoCommentRead>> => {
    return requestWithEtag<TodoCommentRead>(client, { url: APP_API_PATHS.todoComment(todo_id, comment_id), method: 'PATCH', body, headers: ifMatchHeaders(etag) }, versionOf);
};

/**
 * コメントを削除する関数 (論理削除。204。投稿者・tenant_admin)。If-Match は必須 (コメントの版)
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {string} comment_id コメント ID
 * @param {string} etag コメントの ETag
*/
export const deleteTodoComment = async (client: ApiClient, todo_id: string, comment_id: string, etag: string): Promise<void> => {
    await client.request<true>({ url: APP_API_PATHS.todoComment(todo_id, comment_id), method: 'DELETE', headers: ifMatchHeaders(etag), takeData: takeNoContent });
};
