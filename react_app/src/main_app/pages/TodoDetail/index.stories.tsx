import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { AppStoryFrame, appApiBeforeEach, problemStoryReply, type AppApiStoryParameters } from '@/main_app/testing/story_api';
import { ASSIGNEE_TODO_PERMISSIONS, TODO_ID, activityOf, activityPageOf, todoDetailOf } from '@/main_app/testing/todo_test_data';
import { todoStoryApiOf } from '@/main_app/pages/TodoCommon/story_support';
import type { TodoDetail } from '@/main_app/api/contract';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppTodoDetailPage } from '.';

const NO_PERMISSIONS = { can_edit_fields: false, can_change_status: false, can_change_visibility: false, can_change_assignees: false, can_delete: false };

const meta = {
    title: 'AP/TodoDetail',
    component: AppTodoDetailPage,
    parameters: { layout: 'fullscreen', initial_path: `/alpha/todos/${TODO_ID}` },
    decorators: [withAppAuth, withMemoryRouter],
    beforeEach: appApiBeforeEach,
    render: () => (
        <AppStoryFrame>
            <Route path="todos/:todoId" element={<AppTodoDetailPage />} />
        </AppStoryFrame>
    ),
} satisfies Meta<typeof AppTodoDetailPage>;

export default meta;
type Story = StoryObj<typeof meta>;

const ACTIVITIES = activityPageOf([
    activityOf({ id: 'a3', action: 'status_changed', payload: { changes: { status: { before: 'open', after: 'in_progress' } } }, created_at: '2026-10-03T00:00:00Z' }),
    activityOf({ id: 'a2', action: 'assignees_changed', payload: { added: [OTHER_USER_ID], removed: [] }, actor_display_name: 'Hanako Admin', created_at: '2026-10-02T00:00:00Z' }),
    activityOf({ id: 'a1', action: 'created', payload: { values: {} }, actor_display_name: 'Hanako Admin', created_at: '2026-10-01T00:00:00Z' }),
], {
    [SELF_USER_ID]: { display_name: 'Hanako Admin', is_active: true },
    [OTHER_USER_ID]: { display_name: 'Taro Yamada', is_active: false },
});

/**
 * ストーリーの parameters を作る関数
 * @param {Partial<TodoDetail>} detail 詳細の上書き
 * @param {string[]} roles ログイン中のロール
 * @param {AppApiStoryParameters} extra 追加の応答
 * @returns {object} parameters
*/
const parametersOf = (detail: Partial<TodoDetail> = {}, roles: string[] = ['tenant_admin', 'member'], extra: AppApiStoryParameters = {}) => {
    const body = todoDetailOf({ created_by: SELF_USER_ID, ...detail });
    return {
        app_auth: { roles },
        app_api: todoStoryApiOf(roles, {
            [`GET /api/v1/todos/${TODO_ID}`]: { status: 200, body, headers: { ETag: `"${body.version}"` } },
            [`GET /api/v1/todos/${TODO_ID}/activities`]: { status: 200, body: ACTIVITIES },
            ...extra,
        }),
    };
};

/** テナント管理者 (すべての項目を編集でき、削除もできる) */
export const TenantAdmin: Story = {
    parameters: parametersOf(),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-fields-submit')).toBeInTheDocument();
        await expect(canvas.getByTestId('todo-detail-delete')).toBeInTheDocument();
    },
};

/** メンバー (他人が作成した ToDo の担当者のみ: ステータスと担当者だけ変えられる) */
export const AssigneeOnly: Story = {
    parameters: parametersOf({ created_by: OTHER_USER_ID, permissions: ASSIGNEE_TODO_PERMISSIONS }, ['member']),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-fields-readonly')).toBeInTheDocument();
        await expect(canvas.getByTestId('todo-edit-title')).toBeDisabled();
        await expect(canvas.queryByTestId('todo-fields-submit')).toBeNull();
        await expect(canvas.queryByTestId('todo-detail-delete')).toBeNull();
        await expect(canvas.getByTestId('todo-status-done')).toBeEnabled();
    },
};

/** メンバー (自分が作成した ToDo: すべての項目を編集でき、削除もできる) */
export const MemberCreator: Story = { parameters: parametersOf({}, ['member']) };

/** メンバー (閲覧のみ: 何も変更できない) */
export const ViewOnly: Story = {
    parameters: parametersOf({ created_by: OTHER_USER_ID, permissions: NO_PERMISSIONS }, ['member']),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-status-readonly')).toBeInTheDocument();
        await expect(canvas.getByTestId('todo-status-done')).toBeDisabled();
    },
};

/** 公開先の組織がすべて削除された (非公開と同じ扱いで、再指定を促す) */
export const NeedsOrganizationReselect: Story = {
    parameters: parametersOf({ visibility: 'organization', effective_visibility: 'private', organizations: [] }),
    play: async ({ canvasElement: canvas_element }) => {
        await expect(await within(canvas_element).findByTestId('todo-reselect-notice')).toBeInTheDocument();
    },
};

/** 読み込み中 */
export const Loading: Story = {
    parameters: { app_api: todoStoryApiOf(['tenant_admin'], { [`GET /api/v1/todos/${TODO_ID}`]: { status: 200, never_settles: true } }) },
};

/** 閲覧できない・削除済みの ToDo (404。存在を明かさない) */
export const NotFound: Story = {
    parameters: { app_api: todoStoryApiOf(['tenant_admin'], { [`GET /api/v1/todos/${TODO_ID}`]: problemStoryReply(404, 'todo_not_found') }) },
};

/** 他の操作で更新されていた (412。再読み込みを促す) */
export const VersionConflict: Story = {
    parameters: parametersOf({}, ['tenant_admin', 'member'], { [`PATCH /api/v1/todos/${TODO_ID}`]: problemStoryReply(412, 'todo_version_conflict') }),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await userEvent.click(await canvas.findByTestId('todo-status-done'));
        await expect(await canvas.findByTestId('todo-detail-action-error-reload')).toBeInTheDocument();
    },
};

/** 削除の確認ダイアログ (初期フォーカスは「キャンセル」) */
export const DeleteConfirm: Story = {
    parameters: parametersOf(),
    play: async ({ canvasElement: canvas_element }) => {
        await userEvent.click(await within(canvas_element).findByTestId('todo-detail-delete'));
        await expect(await within(document.body).findByRole('dialog', { name: 'ToDo を削除しますか' })).toBeInTheDocument();
    },
};
