import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { ORGANIZATION_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { AppStoryFrame, appApiBeforeEach, problemStoryReply, type AppApiStoryParameters } from '@/main_app/testing/story_api';
import { SAMPLE_ORGANIZATIONS, SAMPLE_USER_DETAILS, SECOND_ORGANIZATION_ID, meBodyOf } from '@/main_app/testing/story_data';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppProfilePage } from '.';

const meta = {
    title: 'AP/Profile',
    component: AppProfilePage,
    parameters: { layout: 'fullscreen', initial_path: '/alpha/profile' },
    decorators: [withAppAuth, withMemoryRouter],
    beforeEach: appApiBeforeEach,
    render: () => (
        <AppStoryFrame>
            <Route path="profile" element={<AppProfilePage />} />
        </AppStoryFrame>
    ),
} satisfies Meta<typeof AppProfilePage>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * プロフィールの API の応答を作る関数
 * @param {string[]} roles ロール
 * @param {string[]} member_of 所属する組織の ID
 * @returns {AppApiStoryParameters} 応答
*/
const apiOf = (roles: string[], member_of: string[]): AppApiStoryParameters => ({
    // 所属組織は /api/v1/me の応答に含まれる
    'GET /api/v1/me': { status: 200, body: meBodyOf(SELF_USER_ID, roles, SAMPLE_ORGANIZATIONS.filter(({ id }) => member_of.includes(id)).map(({ id, name }) => ({ id, name }))) },
    [`GET /api/v1/users/${SELF_USER_ID}`]: { status: 200, body: SAMPLE_USER_DETAILS[SELF_USER_ID], headers: { ETag: '"7"' } },
});

/** テナント管理者 (所属組織あり) */
export const TenantAdmin: Story = {
    parameters: { app_api: apiOf(['tenant_admin', 'member'], [ORGANIZATION_ID, SECOND_ORGANIZATION_ID]) },
    play: async ({ canvasElement: canvas_element }) => {
        await expect(await within(canvas_element).findByTestId('profile-organizations-list')).toBeInTheDocument();
    },
};

/** メンバー */
export const Member: Story = { parameters: { app_auth: { user_name: 'taro', roles: ['member'] }, app_api: apiOf(['member'], [ORGANIZATION_ID]) } };

/** どの組織にも所属していない */
export const NoOrganizations: Story = { parameters: { app_api: apiOf(['member'], []) } };

/** 読み込み中 */
export const Loading: Story = { parameters: { app_api: { 'GET /api/v1/me': { status: 200, never_settles: true } } } };

/** 取得に失敗した */
export const LoadError: Story = { parameters: { app_api: { 'GET /api/v1/me': problemStoryReply(500, 'internal_error') } } };
