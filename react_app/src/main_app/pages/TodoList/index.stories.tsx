import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { AppStoryFrame, appApiBeforeEach, problemStoryReply } from '@/main_app/testing/story_api';
import { pageOf } from '@/main_app/testing/story_data';
import { SAMPLE_TODOS, SECOND_TODO_ID, THIRD_TODO_ID, todoStoryApiOf } from '@/main_app/pages/TodoCommon/story_support';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppTodoListPage } from '.';

const LIST_KEY = 'GET /api/v1/todos';

const meta = {
    title: 'AP/TodoList',
    component: AppTodoListPage,
    parameters: { layout: 'fullscreen', initial_path: '/alpha/todos' },
    decorators: [withAppAuth, withMemoryRouter],
    beforeEach: appApiBeforeEach,
    render: () => (
        <AppStoryFrame>
            <Route path="todos" element={<AppTodoListPage />} />
        </AppStoryFrame>
    ),
} satisfies Meta<typeof AppTodoListPage>;

export default meta;
type Story = StoryObj<typeof meta>;

/** テナント管理者 (すべての行でステータスを変えられる) */
export const TenantAdmin: Story = {
    parameters: { app_api: todoStoryApiOf(['tenant_admin', 'member'], { [LIST_KEY]: { status: 200, body: pageOf(SAMPLE_TODOS) } }) },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-table')).toBeInTheDocument();
        await expect(canvas.getByTestId(`todo-status-select-${SECOND_TODO_ID}`)).toBeInTheDocument();
        await expect(canvas.getByTestId(`todo-status-select-${THIRD_TODO_ID}`)).toBeInTheDocument();
    },
};

/** メンバー (自分が作成・担当の行だけステータスを変えられる。他の行はチップ表示。期限切れは文字でも示す) */
export const Member: Story = {
    parameters: { app_auth: { user_name: 'taro', roles: ['member'] }, app_api: todoStoryApiOf(['member'], { [LIST_KEY]: { status: 200, body: pageOf(SAMPLE_TODOS) } }) },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-table')).toBeInTheDocument();
        await expect(canvas.getByTestId(`todo-status-select-${SAMPLE_TODOS[0].id}`)).toBeInTheDocument();
        await expect(canvas.getByTestId(`todo-status-select-${SECOND_TODO_ID}`)).toBeInTheDocument();
        await expect(canvas.queryByTestId(`todo-status-select-${THIRD_TODO_ID}`)).toBeNull();
        await expect(canvas.getByTestId(`todo-due-${THIRD_TODO_ID}`)).toHaveTextContent('期限切れ');
    },
};

/** 読み込み中 */
export const Loading: Story = { parameters: { app_api: todoStoryApiOf(['tenant_admin'], { [LIST_KEY]: { status: 200, never_settles: true } }) } };

/** ToDo がない */
export const Empty: Story = { parameters: { app_api: todoStoryApiOf(['tenant_admin'], { [LIST_KEY]: { status: 200, body: pageOf([]) } }) } };

/** 絞り込み中で、条件に合う ToDo がない */
export const EmptyFiltered: Story = {
    parameters: { initial_path: '/alpha/todos?scope=mine&status=done&q=見積', app_api: todoStoryApiOf(['tenant_admin'], { [LIST_KEY]: { status: 200, body: pageOf([]) } }) },
    play: async ({ canvasElement: canvas_element }) => {
        await expect(await within(canvas_element).findByTestId('todo-list-empty-clear')).toBeInTheDocument();
    },
};

/** 取得に失敗した (role="alert" と再試行) */
export const LoadError: Story = { parameters: { app_api: todoStoryApiOf(['tenant_admin'], { [LIST_KEY]: problemStoryReply(500, 'internal_error') }) } };

/** 続きのページがある (「さらに読み込む」) */
export const HasMore: Story = { parameters: { app_api: todoStoryApiOf(['tenant_admin'], { [LIST_KEY]: { status: 200, body: pageOf(SAMPLE_TODOS, 'next-cursor') } }) } };

/** 自分が担当のタブ (URL のクエリで表示範囲・絞り込み・並び順を持つ) */
export const AssignedScope: Story = {
    parameters: { initial_path: '/alpha/todos?scope=assigned&priority=low&sort=due_date', app_api: todoStoryApiOf(['member'], { [LIST_KEY]: { status: 200, body: pageOf([SAMPLE_TODOS[1]]) } }) },
};
