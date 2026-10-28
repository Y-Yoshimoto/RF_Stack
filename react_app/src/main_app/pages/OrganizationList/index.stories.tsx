import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { AppStoryFrame, appApiBeforeEach, problemStoryReply } from '@/main_app/testing/story_api';
import { SAMPLE_ORGANIZATIONS, pageOf } from '@/main_app/testing/story_data';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppOrganizationListPage } from '.';

const LIST_KEY = 'GET /api/v1/organizations';

const meta = {
    title: 'AP/OrganizationList',
    component: AppOrganizationListPage,
    parameters: { layout: 'fullscreen', initial_path: '/alpha/organizations' },
    decorators: [withAppAuth, withMemoryRouter],
    beforeEach: appApiBeforeEach,
    render: () => (
        <AppStoryFrame>
            <Route path="organizations" element={<AppOrganizationListPage />} />
        </AppStoryFrame>
    ),
} satisfies Meta<typeof AppOrganizationListPage>;

export default meta;
type Story = StoryObj<typeof meta>;

const LIST_OK = { [LIST_KEY]: { status: 200, body: pageOf(SAMPLE_ORGANIZATIONS) } };

/** テナント管理者 (作成・削除がある) */
export const TenantAdmin: Story = { parameters: { app_api: LIST_OK } };

/** メンバー (閲覧のみ) */
export const Member: Story = {
    parameters: { app_auth: { user_name: 'taro', roles: ['member'] }, app_api: LIST_OK },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('organization-table')).toBeInTheDocument();
        await expect(canvas.queryByTestId('organization-list-create')).toBeNull();
    },
};

/** 作成ダイアログを開いた */
export const CreateDialog: Story = {
    parameters: { app_api: LIST_OK },
    play: async ({ canvasElement: canvas_element }) => {
        await userEvent.click(await within(canvas_element).findByTestId('organization-list-create'));
        await expect(await within(document.body).findByRole('dialog', { name: '組織を作成' })).toBeInTheDocument();
    },
};

/** 削除の確認ダイアログを開いた */
export const DeleteConfirm: Story = {
    parameters: { app_api: LIST_OK },
    play: async ({ canvasElement: canvas_element }) => {
        await userEvent.click(await within(canvas_element).findByTestId(`organization-delete-${SAMPLE_ORGANIZATIONS[0].id}`));
        await expect(await within(document.body).findByRole('dialog', { name: '組織を削除しますか？' })).toBeInTheDocument();
    },
};

/** 読み込み中 */
export const Loading: Story = { parameters: { app_api: { [LIST_KEY]: { status: 200, never_settles: true } } } };

/** 組織がない */
export const Empty: Story = { parameters: { app_api: { [LIST_KEY]: { status: 200, body: pageOf([]) } } } };

/** 取得に失敗した */
export const LoadError: Story = { parameters: { app_api: { [LIST_KEY]: problemStoryReply(500, 'internal_error') } } };
