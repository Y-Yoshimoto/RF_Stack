// Storybook のストーリー用: ToDo のカンバン・要約のサンプルデータと API の応答 (アプリ本体・vitest からは import しない)
import { OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import type { StoryApiReply } from '@/main_app/testing/story_api';
import { THIRD_USER_ID, pageOf } from '@/main_app/testing/story_data';
import { assigneeOf, todoOf } from '@/main_app/testing/todo_test_data';
import { SECOND_TODO_ID, THIRD_TODO_ID } from '@/main_app/pages/TodoCommon/story_support';

const FOURTH_TODO_ID = '01900000-0000-7000-8000-00000000c004';
const FIFTH_TODO_ID = '01900000-0000-7000-8000-00000000c005';

/** ボード・進捗表示用のサンプル (3 つのステータスに分かれ、進捗・コメント・期限切れ・権限の違いを含む) */
export const BOARD_TODOS = [
    todoOf({ title: '見積もりを作る', status: 'open', priority: 'high', due_date: '2026-11-01', created_by: SELF_USER_ID, assignees: [], checklist: { done_count: 2, total_count: 5 }, comment_count: 3 }),
    todoOf({ id: SECOND_TODO_ID, title: '議事録を共有する', status: 'open', priority: 'low', due_date: null, created_by: OTHER_USER_ID, assignees: [assigneeOf({ user_id: SELF_USER_ID, display_name: 'Hanako Admin' })], checklist: { done_count: 0, total_count: 0 } }),
    todoOf({ id: THIRD_TODO_ID, title: '請求書を確認する (期限切れ)', status: 'in_progress', due_date: '2026-09-01', created_by: OTHER_USER_ID, assignees: [assigneeOf({ user_id: THIRD_USER_ID, display_name: 'Jiro Suzuki', is_active: false })], comment_count: 12 }),
    todoOf({ id: FOURTH_TODO_ID, title: '新機能の仕様を書く', status: 'in_progress', priority: 'medium', created_by: SELF_USER_ID, assignees: [assigneeOf()], checklist: { done_count: 3, total_count: 4 } }),
    todoOf({ id: FIFTH_TODO_ID, title: 'リリースノートを公開する', status: 'done', priority: 'medium', created_by: SELF_USER_ID, assignees: [], checklist: { done_count: 3, total_count: 3 } }),
];

/**
 * ステータス (列) ごとに ToDo と総件数を返す一覧 API の応答を作る関数
 * @param {typeof BOARD_TODOS} todos ToDo
 * @returns {(request: Request) => StoryApiReply} リクエストから応答を決める関数
*/
export const boardColumnReplyOf = (todos: typeof BOARD_TODOS = BOARD_TODOS) => (request: Request): StoryApiReply => {
    const status = new URL(request.url).searchParams.get('status');
    const items = todos.filter((todo) => todo.status === status);
    return { status: 200, body: { ...pageOf(items), total: items.length } };
};
