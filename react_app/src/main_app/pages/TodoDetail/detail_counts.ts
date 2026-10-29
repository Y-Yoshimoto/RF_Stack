// 詳細画面で、コメント数・チェックリストの進捗の表示を更新する関数 (純粋関数)
// ToDo の詳細 (TodoDetail) の comment_count / checklist は、コメント・チェックリストの変更では自動で変わらない (ToDo 本体の版を変えないため)。
// そこで画面が変更を受けて上書き値 (override) を持つ。上書き値は、詳細の値 (server) が変わったら (取り直したら) 使わない。
import type { TodoChecklistProgress } from '@/main_app/api/contract';

/**
 * コメント数の上書き。
 */
export type CommentCountOverride = {
    /** 上書きしたときの詳細の値。 */
    server: number;
    value: number;
};

/**
 * チェックリストの進捗の上書き。
 */
export type ChecklistProgressOverride = {
    server: TodoChecklistProgress;
    value: TodoChecklistProgress;
};

/**
 * 表示するコメント数を返す関数
 * @param {number} server 詳細の comment_count
 * @param {CommentCountOverride | null} override 上書き
 * @returns {number} 表示する件数
*/
export const shownCommentCount = (server: number, override: CommentCountOverride | null): number => (override !== null && override.server === server ? override.value : server);

/**
 * コメントの増減を反映した上書きを返す関数 (0 未満にはしない)
 * @param {number} server 詳細の comment_count
 * @param {CommentCountOverride | null} override 現在の上書き
 * @param {number} delta 増減 (投稿は 1、削除は -1)
 * @returns {CommentCountOverride} 新しい上書き
*/
export const withCommentDelta = (server: number, override: CommentCountOverride | null, delta: number): CommentCountOverride => ({
    server,
    value: Math.max(0, shownCommentCount(server, override) + delta),
});

/**
 * 進捗が同じかを判定する関数
 * @param {TodoChecklistProgress} a 進捗
 * @param {TodoChecklistProgress} b 進捗
 * @returns {boolean} 同じなら true
*/
const sameProgress = (a: TodoChecklistProgress, b: TodoChecklistProgress): boolean => a.done_count === b.done_count && a.total_count === b.total_count;

/**
 * 表示するチェックリストの進捗を返す関数
 * @param {TodoChecklistProgress} server 詳細の checklist
 * @param {ChecklistProgressOverride | null} override 上書き
 * @returns {TodoChecklistProgress} 表示する進捗
*/
export const shownChecklistProgress = (server: TodoChecklistProgress, override: ChecklistProgressOverride | null): TodoChecklistProgress => (
    override !== null && sameProgress(override.server, server) ? override.value : server
);

/**
 * 進捗の上書きを作る関数
 * @param {TodoChecklistProgress} server 詳細の checklist
 * @param {TodoChecklistProgress} value チェックリストの変更後の進捗
 * @returns {ChecklistProgressOverride} 上書き
*/
export const withChecklistProgress = (server: TodoChecklistProgress, value: TodoChecklistProgress): ChecklistProgressOverride => ({
    server,
    value: { done_count: value.done_count, total_count: value.total_count },
});
