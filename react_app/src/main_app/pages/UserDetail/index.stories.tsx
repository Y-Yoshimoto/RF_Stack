import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { AppStoryFrame, appApiBeforeEach, problemStoryReply, type AppApiStoryParameters } from '@/main_app/testing/story_api';
import { SAMPLE_USER_DETAILS, THIRD_USER_ID, meBodyOf } from '@/main_app/testing/story_data';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppUserDetailPage } from '.';

const meta = {
    title: 'AP/UserDetail',
    component: AppUserDetailPage,
    parameters: { layout: 'fullscreen' },
    decorators: [withAppAuth, withMemoryRouter],
    beforeEach: appApiBeforeEach,
    render: () => (
        <AppStoryFrame>
            <Route path="users/:userId" element={<AppUserDetailPage />} />
        </AppStoryFrame>
    ),
} satisfies Meta<typeof AppUserDetailPage>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * ストーリーのパスと API の応答を作る関数
 * @param {string} user_id 表示するユーザーの ID
 * @param {string[]} roles ログイン中のユーザーのロール
 * @returns {{ initial_path: string; app_api: AppApiStoryParameters }} parameters
*/
const parametersOf = (user_id: string, roles: string[] = ['tenant_admin', 'member']) => ({
    initial_path: `/alpha/users/${user_id}`,
    app_api: {
        'GET /api/v1/me': { status: 200, body: meBodyOf(SELF_USER_ID, roles) },
        [`GET /api/v1/users/${user_id}`]: { status: 200, body: SAMPLE_USER_DETAILS[user_id], headers: { ETag: `"${SAMPLE_USER_DETAILS[user_id].version}"` } },
    } satisfies AppApiStoryParameters,
});

/** テナント管理者が、他のユーザーを編集する */
export const TenantAdmin: Story = { parameters: parametersOf(OTHER_USER_ID) };

/** 自分自身 (無効化とテナント管理者ロールの解除は無効で、理由を表示する) */
export const Self: Story = {
    parameters: parametersOf(SELF_USER_ID),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('user-deactivate')).toBeDisabled();
        await expect(canvas.getByTestId('user-edit-role-tenant_admin')).toBeDisabled();
    },
};

/** 無効なユーザー (再度有効にできる) */
export const Inactive: Story = { parameters: parametersOf(THIRD_USER_ID) };

/** メンバー (閲覧のみ。編集・有効/無効の UI を出さない) */
export const Member: Story = {
    parameters: { ...parametersOf(OTHER_USER_ID, ['member']), app_auth: { user_name: 'taro', roles: ['member'] } },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('user-info')).toBeInTheDocument();
        await expect(canvas.queryByTestId('user-edit')).toBeNull();
    },
};

/** 読み込み中 */
export const Loading: Story = {
    parameters: { initial_path: `/alpha/users/${OTHER_USER_ID}`, app_api: { 'GET /api/v1/me': { status: 200, never_settles: true }, [`GET /api/v1/users/${OTHER_USER_ID}`]: { status: 200, never_settles: true } } },
};

/** ユーザーが見つからない */
export const NotFound: Story = {
    parameters: {
        initial_path: `/alpha/users/${OTHER_USER_ID}`,
        app_api: { 'GET /api/v1/me': { status: 200, body: meBodyOf() }, [`GET /api/v1/users/${OTHER_USER_ID}`]: problemStoryReply(404, 'user_not_found') },
    },
};

/** 更新が他の操作と競合した (412。再読み込みを促す) */
export const VersionConflict: Story = {
    parameters: {
        ...parametersOf(OTHER_USER_ID),
        app_api: { ...parametersOf(OTHER_USER_ID).app_api, [`PATCH /api/v1/users/${OTHER_USER_ID}`]: problemStoryReply(412, 'user_version_conflict') },
    },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await userEvent.click(await canvas.findByTestId('user-edit-role-tenant_admin'));
        await userEvent.click(canvas.getByTestId('user-edit-submit'));
        await expect(await canvas.findByTestId('user-detail-action-error')).toHaveAttribute('role', 'alert');
    },
};
