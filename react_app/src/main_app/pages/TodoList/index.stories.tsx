import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { AppStoryFrame, appApiBeforeEach, problemStoryReply } from '@/main_app/testing/story_api';
import { pageOf } from '@/main_app/testing/story_data';
import { SAMPLE_TODOS, SECOND_TODO_ID, THIRD_TODO_ID, todoStoryApiOf } from '@/main_app/pages/TodoCommon/story_support';
import { todoDetailOf } from '@/main_app/testing/todo_test_data';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppTodoListPage } from '.';
import { BOARD_TODOS, boardColumnReplyOf } from './story_support';

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

/** 絞り込みを適用中 (検索語・ステータス・優先度。「絞り込み」ボタンのバッジとチップで示し、チップで個別に外せる) */
export const FilterApplied: Story = {
    parameters: { initial_path: '/alpha/todos?scope=assigned&status=open,in_progress&priority=high&q=見積', app_api: todoStoryApiOf(['member'], { [LIST_KEY]: { status: 200, body: pageOf([SAMPLE_TODOS[0]]) } }) },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-chip-status-open')).toBeInTheDocument();
        await expect(canvas.getByTestId('todo-filter-badge')).toHaveTextContent('4');
    },
};

/** 進捗・コメント数・総件数 (「N 件中 M 件を表示」)。続きは末尾が見えたら自動で読み込む */
export const WithProgressAndTotal: Story = {
    parameters: { app_api: todoStoryApiOf(['tenant_admin'], { [LIST_KEY]: { status: 200, body: { ...pageOf(BOARD_TODOS), total: 120 } } }) },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-table')).toBeInTheDocument();
        await expect(canvas.getByTestId('todo-list-count')).toHaveTextContent('120 件中 5 件を表示');
        await expect(canvas.getByTestId(`todo-progress-${BOARD_TODOS[0].id}`)).toHaveTextContent('2/5');
    },
};

/** 狭い画面 (md 未満) ではカード表示 */
export const NarrowCards: Story = {
    globals: { viewport: { value: 'mobile1', isRotated: false } },
    parameters: { app_api: todoStoryApiOf(['member'], { [LIST_KEY]: { status: 200, body: { ...pageOf(BOARD_TODOS), total: 5 } } }) },
    play: async ({ canvasElement: canvas_element }) => {
        await expect(await within(canvas_element).findByTestId('todo-card-list')).toBeInTheDocument();
    },
};

/** 表示範囲ごとの空の案内 (自分が担当) */
export const EmptyAssigned: Story = {
    parameters: { initial_path: '/alpha/todos?scope=assigned', app_api: todoStoryApiOf(['member'], { [LIST_KEY]: { status: 200, body: pageOf([]) } }) },
    play: async ({ canvasElement: canvas_element }) => {
        await expect(await within(canvas_element).findByTestId('todo-list-empty-create')).toBeInTheDocument();
    },
};

/** ボード表示 (テナント管理者。すべてのカードを掴める。ドラッグ・キーボード・カードのメニューで移せる) */
export const Board: Story = {
    parameters: {
        initial_path: '/alpha/todos?view=board',
        app_api: todoStoryApiOf(['tenant_admin', 'member'], {
            [LIST_KEY]: boardColumnReplyOf(),
            [`PATCH /api/v1/todos/${BOARD_TODOS[0].id}`]: { status: 200, body: todoDetailOf({ ...BOARD_TODOS[0], status: 'in_progress', version: 4 }), headers: { ETag: '"4"' } },
        }),
    },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-board-count-done')).toHaveTextContent('1 件');
        await expect(canvas.getByTestId(`todo-board-handle-${THIRD_TODO_ID}`)).toHaveAttribute('aria-disabled', 'false');
    },
};

/** ボード表示 (メンバー。自分が作成・担当のカードだけ掴める。他のカードは鍵アイコン) */
export const BoardMember: Story = {
    parameters: { initial_path: '/alpha/todos?view=board', app_auth: { user_name: 'taro', roles: ['member'] }, app_api: todoStoryApiOf(['member'], { [LIST_KEY]: boardColumnReplyOf() }) },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId(`todo-board-handle-${THIRD_TODO_ID}`)).toHaveAttribute('data-locked', 'true');
    },
};

/** ボード表示 (モバイル。列は横スクロールで 1 列が画面幅の 85%) */
export const BoardMobile: Story = {
    globals: { viewport: { value: 'mobile1', isRotated: false } },
    parameters: { initial_path: '/alpha/todos?view=board', app_api: todoStoryApiOf(['tenant_admin'], { [LIST_KEY]: boardColumnReplyOf() }) },
};

/** ボード表示 (移動に失敗。カードを元の列に戻し、エラーを出す) */
export const BoardMoveFailed: Story = {
    parameters: {
        initial_path: '/alpha/todos?view=board',
        app_api: todoStoryApiOf(['tenant_admin'], { [LIST_KEY]: boardColumnReplyOf(), [`PATCH /api/v1/todos/${BOARD_TODOS[0].id}`]: problemStoryReply(412, 'todo_version_conflict') }),
    },
};

/** ボード表示 (列の取得に失敗。その列だけにエラーと再試行) */
export const BoardColumnError: Story = {
    parameters: {
        initial_path: '/alpha/todos?view=board',
        app_api: todoStoryApiOf(['tenant_admin'], {
            [LIST_KEY]: (request) => (new URL(request.url).searchParams.get('status') === 'done' ? problemStoryReply(500, 'internal_error') : boardColumnReplyOf()(request)),
        }),
    },
};

/** ボード表示 (すべての列が空) */
export const BoardEmpty: Story = {
    parameters: { initial_path: '/alpha/todos?view=board', app_api: todoStoryApiOf(['tenant_admin'], { [LIST_KEY]: boardColumnReplyOf([]) }) },
};
