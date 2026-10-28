// ToDo のアクティビティの payload を読む関数 (純粋関数)
// payload は action ごとに形が異なり、OpenAPI では任意の JSON (Record<string, unknown>)。形が合わない部分は空として扱う (例外にしない)。
// | action | payload |
// | created | {values: {title, description, status, priority, due_date, visibility, organization_ids, assignee_ids}} |
// | updated | {changes: {<title / description / due_date / priority>: {before, after}}} |
// | status_changed | {changes: {status: {before, after}}} |
// | visibility_changed | {changes?: {visibility: {before, after}}, organization_ids?: {added, removed}} (変わった方だけ) |
// | assignees_changed | {added: [...], removed: [...]} |
// | deleted | {title} |
// ID はユーザー・組織の ID (名前は useTodoAssigneeChoices / useTodoOrganizationChoices の選択肢などで引く)。
import type { TodoActivityRead } from '@/main_app/api/contract';

/**
 * 項目の変更 (変更前と変更後。値は文字列か null)。
 */
export type TodoFieldChange = {
    /** 項目名 (title / description / due_date / priority / status / visibility)。 */
    field: string;
    before: string | null;
    after: string | null;
};

/**
 * ID の追加と削除。
 */
export type TodoIdDelta = {
    added: string[];
    removed: string[];
};

/**
 * 値がオブジェクト (配列・null 以外) かを判定する関数
 * @param {unknown} value 値
 * @returns {boolean} オブジェクトなら true
*/
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * 値を文字列か null にする関数
 * @param {unknown} value 値
 * @returns {string | null} 文字列か null
*/
const textOf = (value: unknown): string | null => {
    if (value === null || value === undefined) return null;
    return typeof value === 'string' ? value : JSON.stringify(value);
};

/**
 * 値を文字列の配列にする関数 (文字列以外の要素は除く)
 * @param {unknown} value 値
 * @returns {string[]} 文字列の配列
*/
const idsOf = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []);

/**
 * 項目の変更を取り出す関数 (updated / status_changed / visibility_changed の payload.changes)
 * @param {TodoActivityRead} activity アクティビティ
 * @returns {TodoFieldChange[]} 項目の変更 (無ければ空)
*/
export const todoActivityChangesOf = (activity: TodoActivityRead): TodoFieldChange[] => {
    const changes = activity.payload.changes;
    if (!isRecord(changes)) return [];
    return Object.entries(changes)
        .filter((entry): entry is [string, Record<string, unknown>] => isRecord(entry[1]))
        .map(([field, change]) => ({ field, before: textOf(change.before), after: textOf(change.after) }));
};

/**
 * ID の追加と削除を取り出す関数 (assignees_changed の担当者、visibility_changed の公開先組織)
 * @param {TodoActivityRead} activity アクティビティ
 * @returns {TodoIdDelta} 追加と削除 (該当しなければ空)
*/
export const todoActivityIdDeltaOf = (activity: TodoActivityRead): TodoIdDelta => {
    const source = activity.action === 'visibility_changed' ? activity.payload.organization_ids : activity.payload;
    if (activity.action !== 'assignees_changed' && activity.action !== 'visibility_changed') return { added: [], removed: [] };
    if (!isRecord(source)) return { added: [], removed: [] };
    return { added: idsOf(source.added), removed: idsOf(source.removed) };
};

/**
 * 作成時の値を取り出す関数 (created の payload.values)
 * @param {TodoActivityRead} activity アクティビティ
 * @returns {Record<string, unknown> | null} 作成時の値 (created 以外・形が合わなければ null)
*/
export const todoActivityCreatedValuesOf = (activity: TodoActivityRead): Record<string, unknown> | null => {
    const values = activity.payload.values;
    return activity.action === 'created' && isRecord(values) ? values : null;
};

/**
 * 削除時のタイトルを取り出す関数 (deleted の payload.title)
 * @param {TodoActivityRead} activity アクティビティ
 * @returns {string | null} タイトル (deleted 以外・形が合わなければ null)
*/
export const todoActivityDeletedTitleOf = (activity: TodoActivityRead): string | null => {
    const title = activity.payload.title;
    return activity.action === 'deleted' && typeof title === 'string' ? title : null;
};
