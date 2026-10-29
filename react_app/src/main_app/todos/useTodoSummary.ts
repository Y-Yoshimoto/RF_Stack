/**
 * @description:
 * ホームの ToDo の要約 (AP-UX-01。自分が担当・作成した未完了の件数) を取得するカスタムフック
 * - today はクライアントのローカル日付 (省略時は todayOf())。サーバーはこの日で期限切れ・期限間近を数える (§10 #21)
 * - today / due_soon_days が変わるか reload を呼ぶと取り直す
 * - 件数から一覧へのリンクは todo_summary.ts の todoSummaryFiltersOf、期限の近い ToDo は TODO_SUMMARY_UPCOMING_FILTER を useTodoList に渡す
*/
import { useAppApiClient } from '@/main_app/api/client';
import { TODO_SUMMARY_DUE_SOON_DAYS, type TodoSummary } from '@/main_app/api/contract';
import { classifyAppError, type AppErrorInfo } from '@/main_app/api/errors';
import { buildTodoSummaryUrl, fetchTodoSummary } from '@/main_app/api/todos';
import { useAsyncValue } from '@/shared/hooks/useAsyncValue';
import { todayOf } from './todo_dates';

/**
 * 要約の状態と操作。
 */
export type TodoSummaryState = {
    status: 'loading' | 'success' | 'error';
    /** 要約 (取得前・失敗時は null)。 */
    summary: TodoSummary | null;
    /** 取得の失敗 (status === 'error' のとき)。 */
    error: AppErrorInfo | null;
    /** 取り直す (取得中は loading)。 */
    reload: () => void;
};

export type UseTodoSummaryOptions = {
    /** 期限間近の日数 (省略時は 7。1〜30)。 */
    due_soon_days?: number;
};

/**
 * ホームの ToDo の要約を取得するカスタムフック (AppAuthProvider の内側で使う)
 * @param {string} today 今日 (`YYYY-MM-DD`。省略時はブラウザのローカル日付)
 * @param {UseTodoSummaryOptions} options 期限間近の日数
 * @returns {TodoSummaryState} 要約の状態と操作
*/
export const useTodoSummary = (today: string = todayOf(), { due_soon_days = TODO_SUMMARY_DUE_SOON_DAYS }: UseTodoSummaryOptions = {}): TodoSummaryState => {
    const client = useAppApiClient();
    const query = { today, due_soon_days };
    const { result, reload } = useAsyncValue(() => fetchTodoSummary(client, query), `app-todo-summary:${buildTodoSummaryUrl(query)}`);
    if (result.status === 'loading') return { status: 'loading', summary: null, error: null, reload };
    if (result.status === 'error') return { status: 'error', summary: null, error: classifyAppError(result.error), reload };
    return { status: 'success', summary: result.value, error: null, reload };
};

export default useTodoSummary;
