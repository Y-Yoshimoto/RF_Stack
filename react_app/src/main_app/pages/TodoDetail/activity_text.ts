// ToDo のアクティビティ (変更履歴) を、画面に出す文にする関数 (純粋関数)
// payload の読み取りは todos/activity_payload.ts。ID は担当者・組織の名前に引き直す (引けなければ「不明」)。
// ユーザー (操作者・担当者) の名前は応答の users (todos/activity_users.ts) で引く。外れた担当者や無効化されたユーザーも名前で出し、無効は「(無効)」を添える。
import type { TodoActivityRead, TodoActivityUsers } from '@/main_app/api/contract';
import { TODO_FIELD_LABELS, todoFieldValueTextOf } from '@/main_app/pages/TodoCommon/todo_labels';
import { todoActivityChangesOf, todoActivityDeletedTitleOf, todoActivityIdDeltaOf } from '@/main_app/todos/activity_payload';
import { UNKNOWN_USER_LABEL, todoActivityAssigneeDeltaOf, todoActivityCreatedAssigneesOf, type TodoActivityUserRef } from '@/main_app/todos/activity_users';

/**
 * ID から名前を引く関数の型 (引けなければ「不明」を返す)。
 */
export type NameLookup = (id: string) => string;

/**
 * 名前を解決したユーザーを表示用の文字にする関数 (引けなければ「不明なユーザー」。無効なユーザーは色だけに頼らず「(無効)」を添える)
 * @param {TodoActivityUserRef} ref 名前を解決したユーザーの参照
 * @returns {string} 表示用の文字
*/
export const userRefTextOf = (ref: TodoActivityUserRef): string => {
    if (ref.user === null) return UNKNOWN_USER_LABEL;
    return ref.user.is_active ? ref.user.display_name : `${ref.user.display_name} (無効)`;
};

/**
 * ID の追加と削除を文にする関数
 * @param {string} label 対象 (担当者 / 公開先の組織)
 * @param {{ added: string[]; removed: string[] }} delta 追加と削除 (表示用の名前)
 * @returns {string[]} 文 (変化が無ければ空)
*/
const deltaLinesOf = (label: string, delta: { added: string[]; removed: string[] }): string[] => [
    ...(delta.added.length > 0 ? [`${label}を追加: ${delta.added.join('、')}`] : []),
    ...(delta.removed.length > 0 ? [`${label}を削除: ${delta.removed.join('、')}`] : []),
];

/**
 * 説明の変更は本文が長いため、内容を出さず「変更」とだけ示す関数
 * @param {string} field 項目名
 * @param {string | null} before 変更前
 * @param {string | null} after 変更後
 * @returns {string} 文
*/
const changeLineOf = (field: string, before: string | null, after: string | null): string => {
    const label = TODO_FIELD_LABELS[field] ?? field;
    if (field === 'description') return `${label}を変更しました`;
    return `${label}: ${todoFieldValueTextOf(field, before)} → ${todoFieldValueTextOf(field, after)}`;
};

/**
 * 公開先の組織の追加と削除を、名前に引き直す関数
 * @param {TodoActivityRead} activity アクティビティ
 * @param {NameLookup} nameOf 組織の名前の引き当て
 * @returns {{ added: string[]; removed: string[] }} 追加と削除 (表示用の名前)
*/
const organizationDeltaOf = (activity: TodoActivityRead, nameOf: NameLookup): { added: string[]; removed: string[] } => {
    const delta = todoActivityIdDeltaOf(activity);
    return { added: delta.added.map(nameOf), removed: delta.removed.map(nameOf) };
};

/**
 * アクティビティの内容を文の並びにする関数
 * @param {TodoActivityRead} activity アクティビティ
 * @param {{ users: TodoActivityUsers; organization: NameLookup }} lookups ユーザー (応答の users) と組織の名前の引き当て
 * @returns {string[]} 文 (1 行ずつ。内容が読み取れなければ種別の説明だけ)
*/
export const activityLinesOf = (activity: TodoActivityRead, lookups: { users: TodoActivityUsers; organization: NameLookup }): string[] => {
    switch (activity.action) {
        case 'created': {
            const assignees = todoActivityCreatedAssigneesOf(activity, lookups.users).map(userRefTextOf);
            return ['ToDo を作成しました', ...(assignees.length > 0 ? [`担当者: ${assignees.join('、')}`] : [])];
        }
        case 'deleted': {
            const title = todoActivityDeletedTitleOf(activity);
            return [title === null ? 'ToDo を削除しました' : `ToDo「${title}」を削除しました`];
        }
        case 'assignees_changed': {
            const delta = todoActivityAssigneeDeltaOf(activity, lookups.users);
            const lines = deltaLinesOf('担当者', { added: delta.added.map(userRefTextOf), removed: delta.removed.map(userRefTextOf) });
            return lines.length > 0 ? lines : ['担当者を変更しました'];
        }
        case 'visibility_changed': {
            const lines = [
                ...todoActivityChangesOf(activity).map((change) => changeLineOf(change.field, change.before, change.after)),
                ...deltaLinesOf('公開先の組織', organizationDeltaOf(activity, lookups.organization)),
            ];
            return lines.length > 0 ? lines : ['閲覧範囲を変更しました'];
        }
        default: {
            const lines = todoActivityChangesOf(activity).map((change) => changeLineOf(change.field, change.before, change.after));
            return lines.length > 0 ? lines : [activity.action === 'status_changed' ? 'ステータスを変更しました' : '項目を変更しました'];
        }
    }
};
