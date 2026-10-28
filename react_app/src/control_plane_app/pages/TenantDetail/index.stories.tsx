import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { cpApiBeforeEach, CpStoryFrame, problemStoryReply, type CpApiStoryParameters } from '@/control_plane_app/testing/story_api';
import { sampleDetail, sampleTenant, SAMPLE_METRIC_ITEMS, SAMPLE_TENANT_ID } from '@/control_plane_app/testing/story_data';
import { withCpAuth } from '@/control_plane_app/testing/auth_decorators';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import type { TenantRead } from '@/control_plane_app/api/contract';
import { CpTenantDetailPage } from '.';

const DETAIL_KEY = `GET /api/v1/cp/tenants/${SAMPLE_TENANT_ID}`;
const METRICS_KEY = `GET /api/v1/cp/tenants/${SAMPLE_TENANT_ID}/metrics`;
const SUSPEND_KEY = `POST /api/v1/cp/tenants/${SAMPLE_TENANT_ID}/suspend`;
const METRICS_REPLY = { status: 200, body: { tenant_id: SAMPLE_TENANT_ID, from_date: '2026-10-01', to_date: '2026-10-28', items: SAMPLE_METRIC_ITEMS } };

/**
 * 詳細・メトリクスの API の応答を作る関数
 * @param {Partial<TenantRead>} overrides テナントの上書き項目
 * @returns {CpApiStoryParameters} cp_api
*/
const apiOf = (overrides: Partial<TenantRead> = {}): CpApiStoryParameters => ({
    [DETAIL_KEY]: { status: 200, body: sampleDetail(overrides), headers: { ETag: '"3"' } },
    [METRICS_KEY]: METRICS_REPLY,
});

const meta = {
    title: 'CP/TenantDetail',
    component: CpTenantDetailPage,
    parameters: { layout: 'fullscreen', initial_path: `/cp/tenants/${SAMPLE_TENANT_ID}`, cp_api: apiOf() },
    decorators: [withCpAuth, withMemoryRouter],
    beforeEach: cpApiBeforeEach,
    render: () => (
        <CpStoryFrame>
            <Route path="tenants/:tenant_id" element={<CpTenantDetailPage />} />
        </CpStoryFrame>
    ),
} satisfies Meta<typeof CpTenantDetailPage>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * 停止の確認ダイアログまで操作する関数 (play 用)
 * @param {HTMLElement} canvas_element 描画領域
 * @returns {Promise<void>} 「停止する」を押すまで
*/
const clickSuspend = async (canvas_element: HTMLElement): Promise<void> => {
    await userEvent.click(await within(canvas_element).findByTestId('tenant-action-suspend'));
    await userEvent.click(await within(document.body).findByTestId('tenant-suspend-dialog-confirm'));
};

/** 稼働中 (saas_admin。停止・削除要求を出す) */
export const SaasAdminActive: Story = {};

/** saas_viewer (変更操作の UI を一切出さない) */
export const SaasViewer: Story = {
    parameters: { cp_auth: { user_name: 'cp-viewer', roles: ['saas_viewer'] } },
    play: async ({ canvasElement: canvas_element }) => {
        await within(canvas_element).findByTestId('tenant-detail-viewer-notice');
        await expect(within(canvas_element).queryByTestId('tenant-detail-actions')).toBeNull();
    },
};

/** 停止中 (再開・削除要求を出す) */
export const Suspended: Story = { parameters: { cp_api: apiOf({ status: 'SUSPENDED' }) } };

/** 払い出し失敗 (払い出しの再実行・削除要求を出す) */
export const Failed: Story = { parameters: { cp_api: apiOf({ status: 'FAILED' }) } };

/** 削除待ち (実行できる操作は無い) */
export const PendingDeletion: Story = { parameters: { cp_api: apiOf({ status: 'PENDING_DELETION', deletion_requested_at: '2026-10-27T00:00:00Z' }) } };

/** 取得中 */
export const Loading: Story = { parameters: { cp_api: { [DETAIL_KEY]: { status: 200, never_settles: true } } } };

/** テナントが存在しない (404) */
export const NotFound: Story = { parameters: { cp_api: { [DETAIL_KEY]: problemStoryReply(404, 'tenant_not_found') } } };

/** 取得に失敗 (503。再試行できる) */
export const ErrorState: Story = { parameters: { cp_api: { [DETAIL_KEY]: problemStoryReply(503, 'service_unavailable') } } };

/** メトリクスがまだ集計されていない */
export const MetricsEmpty: Story = { parameters: { cp_api: { ...apiOf(), [METRICS_KEY]: { status: 200, body: { tenant_id: SAMPLE_TENANT_ID, from_date: '2026-10-01', to_date: '2026-10-28', items: [] } } } } };

/** 停止に成功すると、状態が更新される */
export const SuspendSucceeds: Story = {
    parameters: { cp_api: { ...apiOf(), [SUSPEND_KEY]: { status: 200, body: sampleTenant({ status: 'SUSPENDED', version: 4 }), headers: { ETag: '"4"' } } } },
    play: async ({ canvasElement: canvas_element }) => {
        await clickSuspend(canvas_element);
        await expect(await within(canvas_element).findByTestId('tenant-action-resume')).toBeInTheDocument();
    },
};

/** 他の操作で更新済み (412)。再読み込みを促す */
export const VersionConflict: Story = {
    parameters: { cp_api: { ...apiOf(), [SUSPEND_KEY]: problemStoryReply(412, 'tenant_version_conflict') } },
    play: async ({ canvasElement: canvas_element }) => {
        await clickSuspend(canvas_element);
        await expect(await within(canvas_element).findByTestId('tenant-detail-action-error-reload')).toBeInTheDocument();
    },
};

/** 状態遷移の不正 (409)。現在の状態を表示する */
export const InvalidTransition: Story = {
    parameters: { cp_api: { ...apiOf(), [SUSPEND_KEY]: problemStoryReply(409, 'invalid_tenant_transition', { operation: 'suspend', current_status: 'PENDING_DELETION' }) } },
    play: async ({ canvasElement: canvas_element }) => {
        await clickSuspend(canvas_element);
        await expect(await within(canvas_element).findByTestId('tenant-detail-action-error-details')).toHaveTextContent('削除待ち');
    },
};
