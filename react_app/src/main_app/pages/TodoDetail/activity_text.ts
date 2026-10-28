// ToDo のアクティビティ (変更履歴) を、画面に出す文にする関数 (純粋関数)
// payload の読み取りは todos/activity_payload.ts。ID は担当者・組織の名前に引き直す (引けなければ「不明」)。
import type { TodoActivityRead } from '@/main_app/api/contract';
import { TODO_FIELD_LABELS, todoFieldValueTextOf } from '@/main_app/pages/TodoCommon/todo_labels';
import { todoActivityChangesOf, todoActivityDeletedTitleOf, todoActivityIdDeltaOf } from '@/main_app/todos/activity_payload';

/**
 * ID から名前を引く関数の型 (引けなければ「不明」を返す)。
 */
export type NameLookup = (id: string) => string;

/**
 * ID の追加と削除を文にする関数
 * @param {string} label 対象 (担当者 / 公開先の組織)
 * @param {{ added: string[]; removed: string[] }} delta 追加と削除
 * @param {NameLookup} nameOf 名前の引き当て
 * @returns {string[]} 文 (変化が無ければ空)
*/
const deltaLinesOf = (label: string, delta: { added: string[]; removed: string[] }, nameOf: NameLookup): string[] => [
    ...(delta.added.length > 0 ? [`${label}を追加: ${delta.added.map(nameOf).join('、')}`] : []),
    ...(delta.removed.length > 0 ? [`${label}を削除: ${delta.removed.map(nameOf).join('、')}`] : []),
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
 * アクティビティの内容を文の並びにする関数
 * @param {TodoActivityRead} activity アクティビティ
 * @param {{ user: NameLookup; organization: NameLookup }} lookups 名前の引き当て
 * @returns {string[]} 文 (1 行ずつ。内容が読み取れなければ種別の説明だけ)
*/
export const activityLinesOf = (activity: TodoActivityRead, lookups: { user: NameLookup; organization: NameLookup }): string[] => {
    switch (activity.action) {
        case 'created':
            return ['ToDo を作成しました'];
        case 'deleted': {
            const title = todoActivityDeletedTitleOf(activity);
            return [title === null ? 'ToDo を削除しました' : `ToDo「${title}」を削除しました`];
        }
        case 'assignees_changed': {
            const lines = deltaLinesOf('担当者', todoActivityIdDeltaOf(activity), lookups.user);
            return lines.length > 0 ? lines : ['担当者を変更しました'];
        }
        case 'visibility_changed': {
            const lines = [
                ...todoActivityChangesOf(activity).map((change) => changeLineOf(change.field, change.before, change.after)),
                ...deltaLinesOf('公開先の組織', todoActivityIdDeltaOf(activity), lookups.organization),
            ];
            return lines.length > 0 ? lines : ['閲覧範囲を変更しました'];
        }
        default: {
            const lines = todoActivityChangesOf(activity).map((change) => changeLineOf(change.field, change.before, change.after));
            return lines.length > 0 ? lines : [activity.action === 'status_changed' ? 'ステータスを変更しました' : '項目を変更しました'];
        }
    }
};
