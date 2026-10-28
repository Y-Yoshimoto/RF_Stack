import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { ORGANIZATION_ID } from '@/main_app/testing/app_test_support';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { AppStoryFrame, appApiBeforeEach, problemStoryReply, type AppApiStoryParameters } from '@/main_app/testing/story_api';
import { SAMPLE_ORGANIZATION_DETAILS, SAMPLE_USERS, SECOND_ORGANIZATION_ID, pageOf } from '@/main_app/testing/story_data';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppOrganizationDetailPage } from '.';

const meta = {
    title: 'AP/OrganizationDetail',
    component: AppOrganizationDetailPage,
    parameters: { layout: 'fullscreen' },
    decorators: [withAppAuth, withMemoryRouter],
    beforeEach: appApiBeforeEach,
    render: () => (
        <AppStoryFrame>
            <Route path="organizations/:organizationId" element={<AppOrganizationDetailPage />} />
        </AppStoryFrame>
    ),
} satisfies Meta<typeof AppOrganizationDetailPage>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * ストーリーのパスと API の応答を作る関数
 * @param {string} organization_id 表示する組織の ID
 * @returns {{ initial_path: string; app_api: AppApiStoryParameters }} parameters
*/
const parametersOf = (organization_id: string) => ({
    initial_path: `/alpha/organizations/${organization_id}`,
    app_api: {
        [`GET /api/v1/organizations/${organization_id}`]: { status: 200, body: SAMPLE_ORGANIZATION_DETAILS[organization_id], headers: { ETag: `"${SAMPLE_ORGANIZATION_DETAILS[organization_id].version}"` } },
        'GET /api/v1/users': { status: 200, body: pageOf(SAMPLE_USERS) },
    } satisfies AppApiStoryParameters,
});

/** テナント管理者 (名前変更・メンバーの設定・削除) */
export const TenantAdmin: Story = {
    parameters: parametersOf(ORGANIZATION_ID),
    play: async ({ canvasElement: canvas_element }) => {
        await expect(await within(canvas_element).findByTestId('organization-members-select')).toBeInTheDocument();
    },
};

/** メンバー (閲覧のみ。メンバーは一覧で表示する) */
export const Member: Story = {
    parameters: { ...parametersOf(ORGANIZATION_ID), app_auth: { user_name: 'taro', roles: ['member'] } },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('organization-members-list')).toBeInTheDocument();
        await expect(canvas.queryByTestId('organization-members-save')).toBeNull();
        await expect(canvas.queryByTestId('organization-delete')).toBeNull();
    },
};

/** メンバーがいない組織 */
export const NoMembers: Story = { parameters: { ...parametersOf(SECOND_ORGANIZATION_ID), app_auth: { user_name: 'taro', roles: ['member'] } } };

/** 読み込み中 */
export const Loading: Story = {
    parameters: { initial_path: `/alpha/organizations/${ORGANIZATION_ID}`, app_api: { [`GET /api/v1/organizations/${ORGANIZATION_ID}`]: { status: 200, never_settles: true } } },
};

/** 組織が見つからない */
export const NotFound: Story = {
    parameters: {
        initial_path: `/alpha/organizations/${ORGANIZATION_ID}`,
        app_api: { [`GET /api/v1/organizations/${ORGANIZATION_ID}`]: problemStoryReply(404, 'organization_not_found'), 'GET /api/v1/users': { status: 200, body: pageOf(SAMPLE_USERS) } },
    },
};
