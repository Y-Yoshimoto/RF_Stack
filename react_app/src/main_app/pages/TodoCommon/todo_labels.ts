// ToDo の画面で使う表示名 (ステータス・優先度・閲覧範囲・表示範囲・並び順)
import type { TodoPriority, TodoScope, TodoSortKey, TodoStatus, TodoVisibility } from '@/main_app/api/contract';

/** ステータスの表示名 */
export const TODO_STATUS_LABELS: Readonly<Record<TodoStatus, string>> = {
    open: '未着手',
    in_progress: '進行中',
    done: '完了',
};

/** 優先度の表示名 */
export const TODO_PRIORITY_LABELS: Readonly<Record<TodoPriority, string>> = {
    low: '低',
    medium: '中',
    high: '高',
};

/** 閲覧範囲の表示名 */
export const TODO_VISIBILITY_LABELS: Readonly<Record<TodoVisibility, string>> = {
    private: '非公開',
    organization: '組織',
    tenant: 'テナント全体',
};

/** 閲覧範囲の説明 (選択肢に添える) */
export const TODO_VISIBILITY_HINTS: Readonly<Record<TodoVisibility, string>> = {
    private: '作成者と担当者だけが見られます。',
    organization: '選んだ組織のメンバーと、作成者・担当者が見られます。',
    tenant: 'テナントの全メンバーが見られます。',
};

/** 一覧の表示範囲の表示名 */
export const TODO_SCOPE_LABELS: Readonly<Record<TodoScope, string>> = {
    all: 'すべて',
    mine: '自分が作成',
    assigned: '自分が担当',
    shared: '共有された',
};

/** 並び順の表示名 (期限なしは昇順で末尾・降順で先頭) */
export const TODO_SORT_LABELS: Readonly<Record<TodoSortKey, string>> = {
    '-created_at': '作成日時が新しい順',
    created_at: '作成日時が古い順',
    '-updated_at': '更新日時が新しい順',
    updated_at: '更新日時が古い順',
    due_date: '期限が近い順 (期限なしは最後)',
    '-due_date': '期限が遠い順 (期限なしは最初)',
    '-priority': '優先度が高い順',
    priority: '優先度が低い順',
};

/** アクティビティの項目名 */
export const TODO_FIELD_LABELS: Readonly<Record<string, string>> = {
    title: 'タイトル',
    description: '説明',
    due_date: '期限',
    priority: '優先度',
    status: 'ステータス',
    visibility: '閲覧範囲',
};

/**
 * 項目の値を表示用にする関数 (ステータス・優先度・閲覧範囲は表示名、それ以外はそのまま、値が無ければ「なし」)
 * @param {string} field 項目名
 * @param {string | null} value 値
 * @returns {string} 表示用の値
*/
export const todoFieldValueTextOf = (field: string, value: string | null): string => {
    if (value === null || value === '') return 'なし';
    if (field === 'status' && Object.hasOwn(TODO_STATUS_LABELS, value)) return TODO_STATUS_LABELS[value as TodoStatus];
    if (field === 'priority' && Object.hasOwn(TODO_PRIORITY_LABELS, value)) return TODO_PRIORITY_LABELS[value as TodoPriority];
    if (field === 'visibility' && Object.hasOwn(TODO_VISIBILITY_LABELS, value)) return TODO_VISIBILITY_LABELS[value as TodoVisibility];
    return value;
};
