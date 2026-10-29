import type { Meta, StoryObj } from '@storybook/react-vite';
import { Route, Routes } from 'react-router-dom';
import { AppLayout } from '@/main_app/layouts/AppLayout';
import { SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { appApiBeforeEach, problemStoryReply, type AppApiStoryParameters } from '@/main_app/testing/story_api';
import { pageOf } from '@/main_app/testing/story_data';
import { assigneeOf, summaryOf, todoOf } from '@/main_app/testing/todo_test_data';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppHomePage } from '.';

const meta = {
    title: 'AP/Home',
    component: AppHomePage,
    parameters: { layout: 'fullscreen', initial_path: '/alpha/' },
    decorators: [withAppAuth, withMemoryRouter],
    beforeEach: appApiBeforeEach,
    // ホームは認証後のレイアウトの中に表示される
    render: () => (
        <Routes>
            <Route path="/:tenantCode/*" element={<AppLayout />}>
                <Route index element={<AppHomePage />} />
            </Route>
        </Routes>
    ),
} satisfies Meta<typeof AppHomePage>;

export default meta;
type Story = StoryObj<typeof meta>;

const SUMMARY_KEY = 'GET /api/v1/todos/summary';
const LIST_KEY = 'GET /api/v1/todos';

/** 期限の近い担当 ToDo (期限切れを含む) */
const UPCOMING = [
    todoOf({ title: '請求書を確認する', due_date: '2026-10-20', assignees: [assigneeOf({ user_id: SELF_USER_ID })], checklist: { done_count: 1, total_count: 3 }, comment_count: 2 }),
    todoOf({ id: '01900000-0000-7000-8000-00000000c002', title: '見積もりを送る', due_date: '2026-11-02', priority: 'high', assignees: [assigneeOf({ user_id: SELF_USER_ID })] }),
    todoOf({ id: '01900000-0000-7000-8000-00000000c003', title: '議事録を共有する', status: 'in_progress', due_date: null, priority: 'low', assignees: [assigneeOf({ user_id: SELF_USER_ID })] }),
];

/** 要約と期限の近い ToDo の応答 */
const todoApiOf = (extra: AppApiStoryParameters = {}): AppApiStoryParameters => ({
    [SUMMARY_KEY]: { status: 200, body: summaryOf() },
    [LIST_KEY]: { status: 200, body: pageOf(UPCOMING) },
    ...extra,
});

export const TenantAdmin: Story = { parameters: { app_api: todoApiOf() } };

export const Member: Story = { parameters: { app_auth: { user_name: 'taro', roles: ['member'] }, app_api: todoApiOf() } };

/** 要約の読み込み中 */
export const SummaryLoading: Story = { parameters: { app_api: todoApiOf({ [SUMMARY_KEY]: { status: 200, never_settles: true }, [LIST_KEY]: { status: 200, never_settles: true } }) } };

/** 要約の取得に失敗 (その部分だけにエラーと再試行を出し、他の部分は表示する) */
export const SummaryError: Story = { parameters: { app_api: todoApiOf({ [SUMMARY_KEY]: problemStoryReply(500, 'internal_error') }) } };

/** 期限の近い ToDo の取得に失敗 */
export const UpcomingError: Story = { parameters: { app_api: todoApiOf({ [LIST_KEY]: problemStoryReply(500, 'internal_error') }) } };

/** 担当の ToDo が無い (件数 0・期限の近い ToDo なし) */
export const NothingAssigned: Story = {
    parameters: { app_api: todoApiOf({ [SUMMARY_KEY]: { status: 200, body: summaryOf({ assigned: { open: 0, in_progress: 0, overdue: 0, due_soon: 0 }, created: { open: 0, in_progress: 0, overdue: 0 } }) }, [LIST_KEY]: { status: 200, body: pageOf([]) } }) },
};

/** 狭い画面 (要約のカードは 2 列) */
export const Narrow: Story = {
    globals: { viewport: { value: 'mobile1', isRotated: false } },
    parameters: { app_api: todoApiOf() },
};
