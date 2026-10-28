// ToDo 一覧の絞り込みと、画面の URL クエリ (`?scope=mine&status=open,in_progress`) の相互変換 (純粋関数)
// - クエリ名は API と同じ (scope / status / priority / q / organization_id / assignee_id / due_before / due_after / sort)。
//   status / priority はカンマ区切り。件数 (limit) とカーソルは URL に載せない
// - 読み取りでは不正な値 (未知の値・日付や UUID の形式違い・複数キーの sort) を捨てる (API の 422 を避ける)
// - 書き出しは正規化した形 (既定値・空は省く、並びを固定) にする。parseTodoListSearch(toTodoListSearch(f)) は normalizeTodoListFilter(f) と等しい
// 画面は react-router の useSearchParams と組み合わせて使う: `const filter = parseTodoListSearch(search_params)`、
// 変更時は `setSearchParams(toTodoListSearch(next, search_params))` (絞り込み以外のクエリは残す)。
import { TODO_LIMITS, TODO_PRIORITIES, TODO_SCOPES, TODO_SORT_KEYS, TODO_STATUSES } from '@/main_app/api/contract';
import { normalizeTodoListFilter, type TodoListFilter } from '@/main_app/api/todos';

/** URL クエリのうち、絞り込みに使う名前 */
export const TODO_LIST_SEARCH_KEYS = ['scope', 'status', 'priority', 'q', 'organization_id', 'assignee_id', 'due_before', 'due_after', 'sort'] as const;

const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * 値が候補のいずれかかを判定する関数
 * @param {readonly T[]} values 候補
 * @param {string | null} value 値
 * @returns {T | undefined} 候補に含まれれば値、無ければ undefined
*/
const oneOf = <T extends string,>(values: readonly T[], value: string | null): T | undefined => values.find((candidate) => candidate === value);

/**
 * カンマ区切りの値から、候補に含まれるものだけを取り出す関数
 * @param {readonly T[]} values 候補
 * @param {string | null} value カンマ区切りの値
 * @returns {T[]} 候補に含まれる値
*/
const listOf = <T extends string,>(values: readonly T[], value: string | null): T[] => {
    const items = (value ?? '').split(',').map((item) => item.trim());
    return values.filter((candidate) => items.includes(candidate));
};

/**
 * 実在する日付 (`YYYY-MM-DD`) かを判定する関数
 * @param {string} value 値
 * @returns {boolean} 実在する日付なら true
*/
export const isIsoDate = (value: string): boolean => {
    const match = DATE_PATTERN.exec(value);
    if (match === null) return false;
    const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
    const date = new Date(Date.UTC(year, month - 1, day));
    return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
};

/**
 * UUID の形式かを判定する関数
 * @param {string} value 値
 * @returns {boolean} UUID の形式なら true
*/
export const isUuid = (value: string): boolean => UUID_PATTERN.test(value);

/**
 * 値が条件を満たすときだけ返す関数
 * @param {string | null} value 値
 * @param {(value: string) => boolean} accept 条件
 * @returns {string | undefined} 条件を満たせば値、満たさなければ undefined
*/
const accepted = (value: string | null, accept: (value: string) => boolean): string | undefined => (value !== null && accept(value) ? value : undefined);

/**
 * URL クエリから一覧の絞り込みを読み取る関数 (不正な値は捨て、正規化して返す)
 * @param {URLSearchParams | string} search URL クエリ (useSearchParams の値、または `location.search`)
 * @returns {TodoListFilter} 絞り込み (limit は含まない)
*/
export const parseTodoListSearch = (search: URLSearchParams | string): TodoListFilter => {
    const params = typeof search === 'string' ? new URLSearchParams(search) : search;
    return normalizeTodoListFilter({
        scope: oneOf(TODO_SCOPES, params.get('scope')),
        status: listOf(TODO_STATUSES, params.get('status')),
        priority: listOf(TODO_PRIORITIES, params.get('priority')),
        q: (params.get('q') ?? '').slice(0, TODO_LIMITS.QUERY_MAX),
        organization_id: accepted(params.get('organization_id'), isUuid),
        assignee_id: accepted(params.get('assignee_id'), isUuid),
        due_before: accepted(params.get('due_before'), isIsoDate),
        due_after: accepted(params.get('due_after'), isIsoDate),
        sort: oneOf(TODO_SORT_KEYS, params.get('sort')),
    });
};

/**
 * 一覧の絞り込みを URL クエリにする関数 (正規化し、既定値・空は省く)
 * @param {TodoListFilter} filter 絞り込み (limit は載せない)
 * @param {URLSearchParams | string} base 元の URL クエリ (絞り込み以外のクエリは残す。省略時は空)
 * @returns {URLSearchParams} URL クエリ
*/
export const toTodoListSearch = (filter: TodoListFilter, base: URLSearchParams | string = ''): URLSearchParams => {
    const params = new URLSearchParams(base);
    for (const key of TODO_LIST_SEARCH_KEYS) params.delete(key);
    const normalized = normalizeTodoListFilter(filter);
    for (const key of TODO_LIST_SEARCH_KEYS) {
        const value = normalized[key];
        if (value === undefined) continue;
        params.set(key, typeof value === 'string' ? value : value.join(','));
    }
    return params;
};
