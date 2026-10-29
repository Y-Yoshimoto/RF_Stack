// Storybook のストーリー用: ToDo の画面で共通の API の応答とデータ (アプリ本体・vitest からは import しない)
import { OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import type { AppApiStoryParameters } from '@/main_app/testing/story_api';
import { SAMPLE_ORGANIZATIONS, SAMPLE_USERS, THIRD_USER_ID, meBodyOf, pageOf } from '@/main_app/testing/story_data';
import { assigneeOf, todoOf } from '@/main_app/testing/todo_test_data';

/** 2 つ目・3 つ目のサンプルの ToDo ID */
export const SECOND_TODO_ID = '01900000-0000-7000-8000-00000000c002';
export const THIRD_TODO_ID = '01900000-0000-7000-8000-00000000c003';

/** サンプルの ToDo (自分が作成・他人が作成して自分が担当・他人が作成して自分は無関係・期限切れ) */
export const SAMPLE_TODOS = [
    todoOf({ title: '見積もりを作る', created_by: SELF_USER_ID, status: 'in_progress', priority: 'high', due_date: '2026-11-01' }),
    todoOf({
        id: SECOND_TODO_ID,
        title: '議事録を共有する',
        created_by: OTHER_USER_ID,
        assignees: [assigneeOf({ user_id: SELF_USER_ID, display_name: 'Hanako Admin' })],
        visibility: 'tenant',
        effective_visibility: 'tenant',
        organizations: [],
        priority: 'low',
        due_date: null,
    }),
    todoOf({
        id: THIRD_TODO_ID,
        title: '請求書を確認する (期限切れ)',
        created_by: OTHER_USER_ID,
        assignees: [assigneeOf({ user_id: THIRD_USER_ID, display_name: 'Jiro Suzuki', is_active: false })],
        visibility: 'private',
        effective_visibility: 'private',
        organizations: [],
        due_date: '2026-09-01',
    }),
];

/**
 * ToDo の画面が共通で呼ぶ API (自分・ユーザー・組織) の応答を作る関数
 * @param {string[]} roles ログイン中のロール
 * @param {AppApiStoryParameters} extra 追加の応答
 * @returns {AppApiStoryParameters} 応答の対応表
*/
export const todoStoryApiOf = (roles: string[] = ['tenant_admin', 'member'], extra: AppApiStoryParameters = {}): AppApiStoryParameters => ({
    'GET /api/v1/me': { status: 200, body: meBodyOf(SELF_USER_ID, roles) },
    'GET /api/v1/users': { status: 200, body: pageOf(SAMPLE_USERS) },
    'GET /api/v1/organizations': { status: 200, body: pageOf(SAMPLE_ORGANIZATIONS) },
    ...extra,
});
