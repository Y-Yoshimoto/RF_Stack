// ToDo の画面で使う、人の表示 (担当者・作成者)
import type { TodoRead, TodoUserRef } from '@/main_app/api/contract';

/**
 * ユーザーの表示にする関数 (無効なユーザーは「無効」を付ける)
 * @param {TodoUserRef} user ユーザー
 * @returns {string} 表示
*/
export const userRefTextOf = (user: TodoUserRef): string => (user.is_active ? user.display_name : `${user.display_name} (無効)`);

/**
 * 担当者の表示にする関数 (無効なユーザーは「無効」を付ける)
 * @param {TodoRead} todo ToDo
 * @returns {string} 表示
*/
export const assigneeTextOf = (todo: TodoRead): string => (
    todo.assignees.length === 0 ? '未割り当て' : todo.assignees.map((assignee) => (assignee.is_active ? assignee.display_name : `${assignee.display_name} (無効)`)).join('、')
);
