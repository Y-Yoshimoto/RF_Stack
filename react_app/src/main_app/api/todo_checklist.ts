// ToDo のチェックリスト API (`/api/v1/todos/{todo_id}/checklist`。AP-CHK) を呼び出す関数
// - GET と変更系はすべてチェックリスト全体 (TodoChecklistRead) と ETag (チェックリストの版) を返す (追加は 201、削除も 200。§10 #23)
// - If-Match: 名前変更・切り替え・削除は項目の版 (項目の version から ifMatchOf で作る)、並べ替えはチェックリストの版 (GET の ETag)。
//   追加は不要。不一致は 412 todo_checklist_version_conflict (拡張メンバー target: item / checklist)
// - チェックリストの変更は ToDo 本体の版・ETag を変えない (§10 #16)
// フック (main_app/todos/useTodoChecklist.ts) から使う。ApiClient を引数で受け取り、副作用はそれだけにする。
import type { ApiClient } from '@/shared/api/client';
import { ifMatchHeaders, requestWithEtag, type WithEtag } from '@/shared/api/etag';
import { APP_API_PATHS, type TodoChecklistItemCreate, type TodoChecklistItemUpdate, type TodoChecklistRead } from './contract';

const versionOf = (checklist: TodoChecklistRead): number => checklist.version;

/**
 * チェックリスト全体と ETag (チェックリストの版) を取得する関数
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @returns {Promise<WithEtag<TodoChecklistRead>>} チェックリストと ETag
*/
export const fetchTodoChecklist = (client: ApiClient, todo_id: string): Promise<WithEtag<TodoChecklistRead>> => {
    return requestWithEtag<TodoChecklistRead>(client, { url: APP_API_PATHS.todoChecklist(todo_id), method: 'GET' }, versionOf);
};

/**
 * チェックリスト項目を追加する関数 (201。If-Match 不要。作成者・tenant_admin)
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {TodoChecklistItemCreate} body 項目名と位置 (位置の省略時は末尾)
 * @returns {Promise<WithEtag<TodoChecklistRead>>} 追加後のチェックリストと ETag
*/
export const addTodoChecklistItem = (client: ApiClient, todo_id: string, body: TodoChecklistItemCreate): Promise<WithEtag<TodoChecklistRead>> => {
    return requestWithEtag<TodoChecklistRead>(client, { url: APP_API_PATHS.todoChecklistItems(todo_id), method: 'POST', body }, versionOf);
};

/**
 * チェックリスト項目の名前・完了を変更する関数 (送った項目だけ)。If-Match は必須 (項目の版)
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {string} item_id 項目 ID
 * @param {TodoChecklistItemUpdate} body 変更する項目
 * @param {string} item_etag 項目の版 (ifMatchOf(item.version))
 * @returns {Promise<WithEtag<TodoChecklistRead>>} 変更後のチェックリストと ETag
*/
export const updateTodoChecklistItem = (client: ApiClient, todo_id: string, item_id: string, body: TodoChecklistItemUpdate, item_etag: string): Promise<WithEtag<TodoChecklistRead>> => {
    return requestWithEtag<TodoChecklistRead>(client, { url: APP_API_PATHS.todoChecklistItem(todo_id, item_id), method: 'PATCH', body, headers: ifMatchHeaders(item_etag) }, versionOf);
};

/**
 * チェックリスト項目を削除する関数 (物理削除。200 で全体を返す)。If-Match は必須 (項目の版)
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {string} item_id 項目 ID
 * @param {string} item_etag 項目の版 (ifMatchOf(item.version))
 * @returns {Promise<WithEtag<TodoChecklistRead>>} 削除後のチェックリストと ETag
*/
export const deleteTodoChecklistItem = (client: ApiClient, todo_id: string, item_id: string, item_etag: string): Promise<WithEtag<TodoChecklistRead>> => {
    return requestWithEtag<TodoChecklistRead>(client, { url: APP_API_PATHS.todoChecklistItem(todo_id, item_id), method: 'DELETE', headers: ifMatchHeaders(item_etag) }, versionOf);
};

/**
 * チェックリスト項目を並べ替える関数 (項目 ID の並びの全置換)。If-Match は必須 (チェックリストの版)
 * @param {ApiClient} client API クライアント
 * @param {string} todo_id ToDo ID
 * @param {readonly string[]} item_ids 全項目の ID (新しい順序。集合が一致しなければ 422)
 * @param {string} checklist_etag チェックリストの ETag
 * @returns {Promise<WithEtag<TodoChecklistRead>>} 並べ替え後のチェックリストと ETag
*/
export const reorderTodoChecklist = (client: ApiClient, todo_id: string, item_ids: readonly string[], checklist_etag: string): Promise<WithEtag<TodoChecklistRead>> => {
    return requestWithEtag<TodoChecklistRead>(
        client,
        { url: APP_API_PATHS.todoChecklistOrder(todo_id), method: 'PUT', body: { item_ids: [...item_ids] }, headers: ifMatchHeaders(checklist_etag) },
        versionOf,
    );
};
