import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { cpApiBeforeEach, CpStoryFrame, problemStoryReply } from '@/control_plane_app/testing/story_api';
import { sampleTenant, SAMPLE_TENANT_ID } from '@/control_plane_app/testing/story_data';
import { withCpAuth } from '@/control_plane_app/testing/auth_decorators';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { CpTenantCreatePage } from '.';

const CREATE_KEY = 'POST /api/v1/cp/tenants';

const meta = {
    title: 'CP/TenantCreate',
    component: CpTenantCreatePage,
    parameters: { layout: 'fullscreen', initial_path: '/cp/tenant-create' },
    decorators: [withCpAuth, withMemoryRouter],
    beforeEach: cpApiBeforeEach,
    render: () => (
        <CpStoryFrame>
            <Route path="tenant-create" element={<CpTenantCreatePage />} />
            <Route path="tenants/:tenant_id" element={<p data-testid="story-detail-page">テナント詳細</p>} />
        </CpStoryFrame>
    ),
} satisfies Meta<typeof CpTenantCreatePage>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * フォームに入力する関数 (play 用)
 * @param {HTMLElement} canvas_element 描画領域
 * @param {string} tenant_code テナントコード
 * @returns {Promise<void>} 入力して送信するまで
*/
const fillAndSubmit = async (canvas_element: HTMLElement, tenant_code: string): Promise<void> => {
    const canvas = within(canvas_element);
    await userEvent.type(await canvas.findByTestId('tenant-create-tenant-code'), tenant_code);
    await userEvent.type(canvas.getByTestId('tenant-create-name'), 'UI Test');
    await userEvent.type(canvas.getByTestId('tenant-create-email'), 'admin@example.com');
    await userEvent.click(canvas.getByTestId('tenant-create-submit'));
};

/** 初期表示 (saas_admin) */
export const SaasAdmin: Story = {};

/** saas_viewer には変更操作の画面を出さない (NotFound) */
export const SaasViewer: Story = {
    parameters: { cp_auth: { user_name: 'cp-viewer', roles: ['saas_viewer'] } },
    play: async ({ canvasElement: canvas_element }) => {
        await expect(await within(canvas_element).findByTestId('not-found-page')).toBeInTheDocument();
    },
};

/** 予約語のテナントコードは、API を呼ぶ前に弾く */
export const ReservedCode: Story = {
    play: async ({ canvasElement: canvas_element }) => {
        await fillAndSubmit(canvas_element, 'admin');
        await expect(await within(canvas_element).findByText(/予約語/)).toBeInTheDocument();
    },
};

/** 作成に成功すると、一時パスワードを一度だけダイアログに表示する */
export const Provisioned: Story = {
    parameters: {
        cp_api: {
            [CREATE_KEY]: {
                status: 201,
                body: { tenant: sampleTenant({ version: 1 }), initial_admin: { username: 'admin@example.com', temporary_password: 'Story-Temp-Pass-1!' }, provisioning_history_id: 'h1' },
                headers: { ETag: '"1"' },
            },
        },
    },
    play: async ({ canvasElement: canvas_element }) => {
        await fillAndSubmit(canvas_element, 'alpha');
        await expect(await within(document.body).findByTestId('credentials-dialog')).toBeInTheDocument();
    },
};

/** テナントコードが重複 (409)。入力欄にエラーを出す */
export const DuplicateCode: Story = {
    parameters: { cp_api: { [CREATE_KEY]: problemStoryReply(409, 'tenant_code_already_exists') } },
    play: async ({ canvasElement: canvas_element }) => {
        await fillAndSubmit(canvas_element, 'alpha');
        await expect(await within(canvas_element).findByTestId('tenant-create-error')).toHaveAttribute('role', 'alert');
    },
};

/** 払い出しの失敗 (502)。テナントは FAILED で残るため、詳細へ誘導して再実行できる */
export const ProvisioningFailed: Story = {
    parameters: { cp_api: { [CREATE_KEY]: problemStoryReply(502, 'tenant_provisioning_failed', { tenant_id: SAMPLE_TENANT_ID, step: 'create_realm' }) } },
    play: async ({ canvasElement: canvas_element }) => {
        await fillAndSubmit(canvas_element, 'alpha');
        await expect(await within(canvas_element).findByTestId('tenant-create-error-detail-link')).toBeInTheDocument();
    },
};
