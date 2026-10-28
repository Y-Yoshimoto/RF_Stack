import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { AppStoryFrame, appApiBeforeEach, problemStoryReply } from '@/main_app/testing/story_api';
import { SAMPLE_USERS, pageOf } from '@/main_app/testing/story_data';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppUserListPage } from '.';

const LIST_KEY = 'GET /api/v1/users';

const meta = {
    title: 'AP/UserList',
    component: AppUserListPage,
    parameters: { layout: 'fullscreen', initial_path: '/alpha/users' },
    decorators: [withAppAuth, withMemoryRouter],
    beforeEach: appApiBeforeEach,
    render: () => (
        <AppStoryFrame>
            <Route path="users" element={<AppUserListPage />} />
        </AppStoryFrame>
    ),
} satisfies Meta<typeof AppUserListPage>;

export default meta;
type Story = StoryObj<typeof meta>;

/** テナント管理者 (作成の導線がある) */
export const TenantAdmin: Story = {
    parameters: { app_api: { [LIST_KEY]: { status: 200, body: pageOf(SAMPLE_USERS) } } },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('user-table')).toBeInTheDocument();
        await expect(canvas.getByTestId('user-list-create')).toBeInTheDocument();
    },
};

/** メンバー (閲覧のみ。作成の導線を出さない) */
export const Member: Story = {
    parameters: { app_auth: { user_name: 'taro', roles: ['member'] }, app_api: { [LIST_KEY]: { status: 200, body: pageOf(SAMPLE_USERS) } } },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('user-table')).toBeInTheDocument();
        await expect(canvas.queryByTestId('user-list-create')).toBeNull();
        await expect(canvas.getByTestId('user-list-readonly')).toBeInTheDocument();
    },
};

/** 読み込み中 */
export const Loading: Story = { parameters: { app_api: { [LIST_KEY]: { status: 200, never_settles: true } } } };

/** ユーザーがいない */
export const Empty: Story = { parameters: { app_api: { [LIST_KEY]: { status: 200, body: pageOf([]) } } } };

/** 取得に失敗した (role="alert" と再試行) */
export const LoadError: Story = { parameters: { app_api: { [LIST_KEY]: problemStoryReply(500, 'internal_error') } } };

/** 続きのページがある (「さらに読み込む」) */
export const HasMore: Story = { parameters: { app_api: { [LIST_KEY]: { status: 200, body: pageOf(SAMPLE_USERS, 'next-cursor') } } } };

/** 無効なユーザーだけに絞り込んでいる */
export const InactiveOnly: Story = {
    parameters: { initial_path: '/alpha/users?status=inactive', app_api: { [LIST_KEY]: { status: 200, body: pageOf(SAMPLE_USERS.filter((user) => !user.is_active)) } } },
};
