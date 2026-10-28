// ToDo 一覧の行の操作可否 (純粋関数)
// 一覧 API の要素 (TodoRead) は permissions を持たない。一覧からの状態変更は「詳細を開いて判定する」のではなく、
// サーバーの権限表 (ToDoApp.md §9.3: ステータスの変更は tenant_admin・作成者・担当者) と同じ条件を、操作者の ID とロールで先に判定して出し分ける。
// 判定が古い場合 (担当から外された直後など) は API が 403 todo_operation_forbidden / 412 を返し、画面は再読み込みを促す。
import type { TodoRead } from '@/main_app/api/contract';

/**
 * 一覧の行から、ステータスを変えられるかを判定する関数
 * @param {TodoRead} todo 一覧の要素
 * @param {string | null} self_user_id 操作者のユーザー ID (未取得なら null)
 * @param {boolean} is_tenant_admin tenant_admin か
 * @returns {boolean} 変えられるなら true
*/
export const canChangeStatusInList = (todo: TodoRead, self_user_id: string | null, is_tenant_admin: boolean): boolean => {
    if (is_tenant_admin) return true;
    if (self_user_id === null) return false;
    return todo.created_by === self_user_id || todo.assignees.some((assignee) => assignee.user_id === self_user_id);
};

/**
 * 絞り込み (表示範囲と並び順を除く) が指定されているかを判定する関数
 * @param {Record<string, unknown>} filter 絞り込み (parseTodoListSearch の結果)
 * @returns {boolean} 指定されていれば true
*/
export const hasListConditions = (filter: Record<string, unknown>): boolean => Object.keys(filter).some((key) => key !== 'scope' && key !== 'sort');
