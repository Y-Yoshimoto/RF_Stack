// ToDo のチェックリストの、API を呼ぶ前の確認と並べ替えの計算 (純粋関数。AP-CHK)
// - 権限はチェックリストの permissions: 追加・名前変更・削除・並べ替えは can_edit、完了・未完了の切り替えは can_check
// - 項目名は前後の空白を除いて 1〜200 文字 (送るのも除いた値)。項目数は 100 まで
// - 並べ替えは現在の項目 ID の集合と一致する並びだけを送る (一致しなければサーバーは 422 mismatch)
// useTodoChecklist が使う。画面は moveChecklistItemIds / shiftChecklistItemIds で並べ替え後の ID の並びを作れる。
import { TODO_CHECKLIST_INPUT_ERROR, TODO_LIMITS, type TodoChecklistItemRead, type TodoChecklistRead } from '@/main_app/api/contract';
import { AppGuardError, type AppErrorInfo } from '@/main_app/api/errors';
import { sameIdSet, TodoGuardError } from './todo_changes';

/**
 * 項目名を送る形にする関数 (前後の空白を除く)
 * @param {string} title 入力
 * @returns {string} 送る項目名
*/
export const normalizeChecklistTitle = (title: string): string => title.trim();

/**
 * 項目名として送れるかを判定する関数 (前後の空白を除いて 1〜200 文字)
 * @param {string} title 入力
 * @returns {boolean} 送れるなら true
*/
export const isValidChecklistTitle = (title: string): boolean => {
    const normalized = normalizeChecklistTitle(title);
    return normalized !== '' && normalized.length <= TODO_LIMITS.CHECKLIST_ITEM_TITLE_MAX;
};

/**
 * 項目を追加できる数に達しているかを判定する関数
 * @param {TodoChecklistRead} checklist チェックリスト
 * @returns {boolean} 上限 (100) に達していれば true
*/
export const isChecklistFull = (checklist: TodoChecklistRead): boolean => checklist.items.length >= TODO_LIMITS.CHECKLIST_ITEMS_MAX;

/**
 * 項目を追加する前に弾く理由を返す関数 (権限 → 項目名 → 上限の順)
 * @param {TodoChecklistRead} checklist チェックリスト
 * @param {string} title 項目名
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const checklistAddGuardOf = (checklist: TodoChecklistRead, title: string): AppGuardError | null => {
    if (!checklist.permissions.can_edit) return new TodoGuardError('edit_checklist');
    if (!isValidChecklistTitle(title)) return new AppGuardError('todo_checklist_title_invalid');
    if (isChecklistFull(checklist)) return new AppGuardError('todo_checklist_too_many_items');
    return null;
};

/**
 * 項目名を変える前に弾く理由を返す関数 (権限 → 項目名 → 変更なしの順)
 * @param {TodoChecklistRead} checklist チェックリスト
 * @param {TodoChecklistItemRead} item 項目
 * @param {string} title 新しい項目名
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const checklistRenameGuardOf = (checklist: TodoChecklistRead, item: TodoChecklistItemRead, title: string): AppGuardError | null => {
    if (!checklist.permissions.can_edit) return new TodoGuardError('edit_checklist');
    if (!isValidChecklistTitle(title)) return new AppGuardError('todo_checklist_title_invalid');
    if (normalizeChecklistTitle(title) === item.title) return new AppGuardError('empty_changes');
    return null;
};

/**
 * 完了・未完了を切り替える前に弾く理由を返す関数 (権限 → 変更なしの順)
 * @param {TodoChecklistRead} checklist チェックリスト
 * @param {TodoChecklistItemRead} item 項目
 * @param {boolean} is_done 切り替え後の値
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const checklistToggleGuardOf = (checklist: TodoChecklistRead, item: TodoChecklistItemRead, is_done: boolean): AppGuardError | null => {
    if (!checklist.permissions.can_check) return new TodoGuardError('check_checklist_item');
    if (item.is_done === is_done) return new AppGuardError('empty_changes');
    return null;
};

/**
 * 項目を削除する前に弾く理由を返す関数
 * @param {TodoChecklistRead} checklist チェックリスト
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const checklistRemoveGuardOf = (checklist: TodoChecklistRead): AppGuardError | null => (checklist.permissions.can_edit ? null : new TodoGuardError('edit_checklist'));

/**
 * 並べ替えの前に弾く理由を返す関数 (権限 → 集合の一致 → 変更なし → ETag の順)
 * @param {TodoChecklistRead} checklist チェックリスト
 * @param {readonly string[]} item_ids 新しい並び
 * @param {string | null} etag チェックリストの ETag
 * @returns {AppGuardError | null} 弾く理由 (無ければ null)
*/
export const checklistReorderGuardOf = (checklist: TodoChecklistRead, item_ids: readonly string[], etag: string | null): AppGuardError | null => {
    if (!checklist.permissions.can_edit) return new TodoGuardError('edit_checklist');
    const current = checklistItemIdsOf(checklist);
    if (item_ids.length !== current.length || !sameIdSet(current, item_ids)) return new AppGuardError('todo_checklist_order_mismatch');
    if (item_ids.every((id, index) => id === current[index])) return new AppGuardError('empty_changes');
    if (!etag) return new AppGuardError('missing_etag');
    return null;
};

/**
 * 項目 ID の並びを返す関数
 * @param {TodoChecklistRead} checklist チェックリスト
 * @returns {string[]} 項目 ID (表示順)
*/
export const checklistItemIdsOf = (checklist: TodoChecklistRead): string[] => checklist.items.map((item) => item.id);

/**
 * 項目 ID の並びの中で、1 つを別の位置へ移す関数 (ドラッグ & ドロップの結果。@dnd-kit/sortable の arrayMove と同じ)
 * @param {readonly string[]} item_ids 並び
 * @param {string} item_id 移す項目
 * @param {string} over_id 移動先にある項目 (その位置に入る)
 * @returns {string[]} 新しい並び (どちらかが無ければ元の並び)
*/
export const moveChecklistItemIds = (item_ids: readonly string[], item_id: string, over_id: string): string[] => {
    const from = item_ids.indexOf(item_id);
    const to = item_ids.indexOf(over_id);
    if (from < 0 || to < 0) return [...item_ids];
    const next = item_ids.filter((id) => id !== item_id);
    next.splice(to, 0, item_id);
    return next;
};

/**
 * 項目を上下に 1 つ動かした並びを返す関数 (「上へ」「下へ」のメニュー)
 * @param {readonly string[]} item_ids 並び
 * @param {string} item_id 動かす項目
 * @param {-1 | 1} delta -1 で上、1 で下
 * @returns {string[] | null} 新しい並び (端・見つからなければ null)
*/
export const shiftChecklistItemIds = (item_ids: readonly string[], item_id: string, delta: -1 | 1): string[] | null => {
    const from = item_ids.indexOf(item_id);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= item_ids.length) return null;
    return moveChecklistItemIds(item_ids, item_id, item_ids[to]);
};

/**
 * API の 422 が並べ替えの集合不一致 (field=item_ids、code=mismatch) かを判定する関数
 * @param {AppErrorInfo} info 分類したエラー
 * @returns {boolean} 集合不一致なら true
*/
export const isChecklistOrderMismatch = (info: AppErrorInfo): boolean => {
    const { field, code } = TODO_CHECKLIST_INPUT_ERROR.ORDER_MISMATCH;
    return (info.problem?.errors ?? []).some((error) => error.field === field && error.code === code);
};
