// ToDo 一覧の「適用中の条件」(AP-UX-05) の純粋関数
// 絞り込み (TodoListFilter) を、個別に外せる条件 (チップ) の並びにする。表示範囲 (scope) と並び順 (sort) は条件に含めない。
// ボード表示ではステータスが列になるため、ステータスの条件は出さない・数えない (AP-BRD-02)。
import type { TodoListFilter } from '@/main_app/api/todos';
import type { TodoListView } from '@/main_app/todos/list_search';
import { TODO_PRIORITY_LABELS, TODO_STATUS_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';

/** 適用中の条件 1 つ。 */
export type TodoFilterChip = {
    /** 安定した識別子 (data-testid の接尾辞にも使う)。 */
    id: string;
    /** 表示 (「ステータス: 未着手」など)。 */
    label: string;
    /** この条件だけを外した絞り込み。 */
    without: TodoListFilter;
    /** 検索語 (検索欄が常に見えているため、絞り込みの適用数には数えない)。 */
    is_search: boolean;
};

export type TodoFilterChipLookups = {
    /** 担当者の表示名 (ID → 表示。無ければ「不明なユーザー」)。 */
    assigneeNameOf: (id: string) => string | undefined;
    /** 組織名 (ID → 名前。無ければ「不明な組織」)。 */
    organizationNameOf: (id: string) => string | undefined;
};

/**
 * ステータスの絞り込みを除いた絞り込みを返す関数 (ボードの列の絞り込みに使う)
 * @param {TodoListFilter} filter 絞り込み
 * @returns {TodoListFilter} ステータスを除いた絞り込み
*/
export const withoutStatusOf = (filter: TodoListFilter): TodoListFilter => {
    const rest = { ...filter };
    delete rest.status;
    return rest;
};

/**
 * 適用中の条件の並びを作る関数
 * @param {TodoListFilter} filter 絞り込み (parseTodoListSearch の結果)
 * @param {TodoListView} view 表示方法 (board ではステータスを出さない)
 * @param {TodoFilterChipLookups} lookups ID から表示名を引く関数
 * @returns {TodoFilterChip[]} 条件
*/
export const activeFilterChipsOf = (filter: TodoListFilter, view: TodoListView, lookups: TodoFilterChipLookups): TodoFilterChip[] => {
    const chips: TodoFilterChip[] = [];
    if (filter.q) chips.push({ id: 'q', label: `タイトル: 「${filter.q}」`, without: { ...filter, q: undefined }, is_search: true });
    if (view === 'list') {
        for (const status of filter.status ?? []) {
            chips.push({ id: `status-${status}`, label: `ステータス: ${TODO_STATUS_LABELS[status]}`, without: { ...filter, status: (filter.status ?? []).filter((value) => value !== status) }, is_search: false });
        }
    }
    for (const priority of filter.priority ?? []) {
        chips.push({ id: `priority-${priority}`, label: `優先度: ${TODO_PRIORITY_LABELS[priority]}`, without: { ...filter, priority: (filter.priority ?? []).filter((value) => value !== priority) }, is_search: false });
    }
    if (filter.assignee_id) chips.push({ id: 'assignee', label: `担当者: ${lookups.assigneeNameOf(filter.assignee_id) ?? '(不明なユーザー)'}`, without: { ...filter, assignee_id: undefined }, is_search: false });
    if (filter.organization_id) chips.push({ id: 'organization', label: `公開先: ${lookups.organizationNameOf(filter.organization_id) ?? '(不明な組織)'}`, without: { ...filter, organization_id: undefined }, is_search: false });
    if (filter.due_after) chips.push({ id: 'due-after', label: `期限: ${filter.due_after} 以降`, without: { ...filter, due_after: undefined }, is_search: false });
    if (filter.due_before) chips.push({ id: 'due-before', label: `期限: ${filter.due_before} 以前`, without: { ...filter, due_before: undefined }, is_search: false });
    return chips;
};

/**
 * 絞り込みの適用数 (「絞り込み」ボタンのバッジ。検索語は数えない) を返す関数
 * @param {readonly TodoFilterChip[]} chips 適用中の条件
 * @returns {number} 適用数
*/
export const filterCountOf = (chips: readonly TodoFilterChip[]): number => chips.filter((chip) => !chip.is_search).length;
