/**
 * @description:
 * AP の ToDo 一覧 (閲覧できるもの) を取得するカスタムフック (カーソル方式の「さらに読み込む」・無限スクロール)
 * 表示範囲・絞り込み・並び順が変わるか reload を呼ぶと先頭ページから取り直す。古い取得の結果は捨てる。
 * - 絞り込みは画面の URL クエリから parseTodoListSearch で作る (list_search.ts)。同じ意味の指定は同じキーになる (normalizeTodoListFilter)
 * - 一覧の要素に説明・permissions は含まれない (useTodo で取得する)。各要素から todoTargetOf で操作の対象を作れる (権限の確認は API に任せる)
 * - 変更の反映: 更新は replaceItem(todoReadOf(update.todo))、削除は removeItem、作成は reload。
 *   更新で絞り込みに合わなくなった要素 (ステータスを変えた等) も残るため、合わせたい場合は reload する
*/
import { useAppApiClient } from '@/main_app/api/client';
import type { TodoListQuery, TodoRead } from '@/main_app/api/contract';
import { classifyAppError } from '@/main_app/api/errors';
import { buildTodoListUrl, fetchTodoPage, toTodoListQuery, type TodoListFilter } from '@/main_app/api/todos';
import { useCursorList, type CursorListState } from '@/shared/hooks/useCursorList';

/**
 * ToDo 一覧の状態と操作 (total は常に null)。
 */
export type TodoListState = CursorListState<TodoRead>;

/**
 * AP の ToDo 一覧を取得するカスタムフック (AppAuthProvider の内側で使う)
 * @param {TodoListFilter} filter 表示範囲・絞り込み・並び順・件数
 * @returns {TodoListState} 一覧の状態と操作
*/
export const useTodoList = (filter: TodoListFilter = {}): TodoListState => {
    const client = useAppApiClient();
    const query: TodoListQuery = toTodoListQuery(filter);
    return useCursorList<TodoRead>({
        query_key: `app-todos:${buildTodoListUrl(query)}`,
        fetchPage: (cursor) => fetchTodoPage(client, cursor === null ? query : { ...query, cursor }),
        classify: classifyAppError,
    });
};

export default useTodoList;
