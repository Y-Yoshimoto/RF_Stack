/**
 * @description:
 * ToDo のアクティビティ (変更履歴。新しい順) を取得するカスタムフック (カーソル方式の「さらに読み込む」)
 * todo_id が変わるか reload を呼ぶと先頭ページから取り直す。閲覧できない ToDo は 404 todo_not_found。
 * 変更操作の後は新しい行が先頭に増えるため、useTodoActions の onUpdated で reload を呼ぶこと。
 * payload の読み取りは activity_payload.ts。
*/
import { useAppApiClient } from '@/main_app/api/client';
import type { TodoActivityListQuery, TodoActivityRead } from '@/main_app/api/contract';
import { classifyAppError } from '@/main_app/api/errors';
import { buildTodoActivitiesUrl, fetchTodoActivityPage } from '@/main_app/api/todos';
import { useCursorList, type CursorListState } from '@/shared/hooks/useCursorList';

/**
 * アクティビティの状態と操作。
 */
export type TodoActivitiesState = CursorListState<TodoActivityRead>;

export type UseTodoActivitiesOptions = {
    /** 1 ページの件数 (省略時はサーバーの既定 50。1〜200)。 */
    limit?: number;
};

/**
 * ToDo のアクティビティを取得するカスタムフック (AppAuthProvider の内側で使う)
 * @param {string} todo_id ToDo ID
 * @param {UseTodoActivitiesOptions} options 件数
 * @returns {TodoActivitiesState} 一覧の状態と操作
*/
export const useTodoActivities = (todo_id: string, { limit }: UseTodoActivitiesOptions = {}): TodoActivitiesState => {
    const client = useAppApiClient();
    const query: TodoActivityListQuery = limit !== undefined ? { limit } : {};
    return useCursorList<TodoActivityRead>({
        query_key: `app-todo-activities:${buildTodoActivitiesUrl(todo_id, query)}`,
        fetchPage: (cursor) => fetchTodoActivityPage(client, todo_id, cursor === null ? query : { ...query, cursor }),
        classify: classifyAppError,
    });
};

export default useTodoActivities;
