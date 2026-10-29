// 詳細画面のフォーム (項目・閲覧範囲・担当者) の下書きの形と、他の人の変更と重なった項目の案内 (純粋関数。AP-UX-07・AP-UX-08)
// 下書きの載せ替えは todos/useRebasedDraft.ts。下書きは詳細 (TodoDetail) から作り、配列の項目は順序を問わない集合で比べる。
import type { TodoDetail, TodoPriority, TodoVisibility } from '@/main_app/api/contract';
import { sameIdSet } from '@/main_app/todos/todo_changes';
import type { DraftEquals } from '@/main_app/todos/rebase_draft';

/** 項目フォームの下書き (期限は空文字で「なし」) */
export type FieldsDraft = {
    title: string;
    description: string;
    due_date: string;
    priority: TodoPriority;
};

/** 閲覧範囲フォームの下書き */
export type AudienceDraft = {
    visibility: TodoVisibility;
    organization_ids: string[];
};

/** 担当者フォームの下書き */
export type AssigneesDraft = {
    assignee_ids: string[];
};

/** 閲覧範囲の公開先組織は集合で比べる */
export const AUDIENCE_EQUALS: DraftEquals<AudienceDraft> = { organization_ids: sameIdSet };

/** 担当者は集合で比べる */
export const ASSIGNEES_EQUALS: DraftEquals<AssigneesDraft> = { assignee_ids: sameIdSet };

/**
 * 詳細から項目フォームの値を作る関数
 * @param {TodoDetail} todo 詳細
 * @returns {FieldsDraft} 項目フォームの値
*/
export const fieldsDraftOf = (todo: TodoDetail): FieldsDraft => ({
    title: todo.title,
    description: todo.description ?? '',
    due_date: todo.due_date ?? '',
    priority: todo.priority,
});

/**
 * 詳細から閲覧範囲フォームの値を作る関数
 * @param {TodoDetail} todo 詳細
 * @returns {AudienceDraft} 閲覧範囲フォームの値
*/
export const audienceDraftOf = (todo: TodoDetail): AudienceDraft => ({
    visibility: todo.visibility,
    organization_ids: todo.organizations.map((organization) => organization.id),
});

/**
 * 詳細から担当者フォームの値を作る関数
 * @param {TodoDetail} todo 詳細
 * @returns {AssigneesDraft} 担当者フォームの値
*/
export const assigneesDraftOf = (todo: TodoDetail): AssigneesDraft => ({ assignee_ids: todo.assignees.map((assignee) => assignee.user_id) });

/** 下書きの項目名 → 画面に出す名前 */
export const DRAFT_FIELD_LABELS: Readonly<Record<string, string>> = {
    title: 'タイトル',
    description: '説明',
    due_date: '期限',
    priority: '優先度',
    visibility: '閲覧範囲',
    organization_ids: '公開先の組織',
    assignee_ids: '担当者',
};

/**
 * 他の人の変更と重なった項目を、画面に出す名前にする関数 (重複は除き、最初に出た順)
 * @param {readonly string[]} keys 下書きの項目名 (3 つのフォームの conflicts を連結したもの)
 * @returns {string[]} 名前
*/
export const conflictLabelsOf = (keys: readonly string[]): string[] => [...new Set(keys.map((key) => DRAFT_FIELD_LABELS[key] ?? key))];

/**
 * 同時編集を検知して最新の内容を自動で再表示したときの案内文を作る関数
 * @param {readonly string[]} labels 他の人の変更と重なった項目の名前 (無ければ空)
 * @returns {string} 案内文
*/
export const refreshedNoticeTextOf = (labels: readonly string[]): string => {
    const overlap = labels.length > 0 ? `${labels.join('、')}は他の人も変更しています。` : '';
    return `他のユーザーが更新したため最新の内容を表示しました。${overlap}確認してもう一度保存してください`;
};
