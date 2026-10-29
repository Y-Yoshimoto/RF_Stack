// ホームの要約 (AP-UX-01) の件数から、絞り込み済みの一覧へのリンクを作る関数 (純粋関数)
// 画面は toTodoListSearch(filter) で URL クエリにして一覧へ移る。件数とリンク先の条件はサーバーの数え方 (§10 #21) に合わせる:
// 未完了は open / in_progress、期限切れは due_date < today (= due_before: 前日)、期限間近は today <= due_date <= due_soon_until。
import type { TodoStatus, TodoSummary } from '@/main_app/api/contract';
import type { TodoListFilter } from '@/main_app/api/todos';
import { addDays } from './todo_dates';

/** 未完了のステータス */
const UNFINISHED: readonly TodoStatus[] = ['open', 'in_progress'];

/** 要約の項目 (カードの種類)。 */
export type TodoSummaryCard = 'assigned_unfinished' | 'assigned_overdue' | 'assigned_due_soon' | 'created_unfinished';

/** ホームの「期限の近い担当 ToDo」の件数 (AP-UX-01)。 */
export const TODO_SUMMARY_UPCOMING_LIMIT = 5;

/**
 * 要約のカードの件数を返す関数
 * @param {TodoSummary} summary 要約
 * @returns {Record<TodoSummaryCard, number>} 件数
*/
export const todoSummaryCountsOf = (summary: TodoSummary): Record<TodoSummaryCard, number> => ({
    assigned_unfinished: summary.assigned.open + summary.assigned.in_progress,
    assigned_overdue: summary.assigned.overdue,
    assigned_due_soon: summary.assigned.due_soon,
    created_unfinished: summary.created.open + summary.created.in_progress,
});

/**
 * 要約のカードから移る一覧の絞り込みを返す関数
 * @param {TodoSummary} summary 要約 (today / due_soon_until を使う)
 * @returns {Record<TodoSummaryCard, TodoListFilter>} 絞り込み
*/
export const todoSummaryFiltersOf = (summary: TodoSummary): Record<TodoSummaryCard, TodoListFilter> => ({
    assigned_unfinished: { scope: 'assigned', status: UNFINISHED },
    assigned_overdue: { scope: 'assigned', status: UNFINISHED, due_before: addDays(summary.today, -1), sort: 'due_date' },
    assigned_due_soon: { scope: 'assigned', status: UNFINISHED, due_after: summary.today, due_before: summary.due_soon_until, sort: 'due_date' },
    created_unfinished: { scope: 'mine', status: UNFINISHED },
});

/** ホームの「期限の近い担当 ToDo」の一覧の絞り込み (useTodoList に渡す。期限切れが先頭、期限なしは末尾)。 */
export const TODO_SUMMARY_UPCOMING_FILTER: TodoListFilter = { scope: 'assigned', status: UNFINISHED, sort: 'due_date', limit: TODO_SUMMARY_UPCOMING_LIMIT };
