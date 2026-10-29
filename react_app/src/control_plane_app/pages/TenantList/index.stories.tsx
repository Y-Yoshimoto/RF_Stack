import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { cpApiBeforeEach, CpStoryFrame, problemStoryReply } from '@/control_plane_app/testing/story_api';
import { SAMPLE_LIST_ITEMS, sampleListItem } from '@/control_plane_app/testing/story_data';
import { withCpAuth } from '@/control_plane_app/testing/auth_decorators';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { CpTenantListPage } from '.';

const LIST_KEY = 'GET /api/v1/cp/tenants';

const meta = {
    title: 'CP/TenantList',
    component: CpTenantListPage,
    parameters: {
        layout: 'fullscreen',
        initial_path: '/cp/tenants',
        cp_api: { [LIST_KEY]: { status: 200, body: { items: SAMPLE_LIST_ITEMS, next_cursor: null, total: SAMPLE_LIST_ITEMS.length } } },
    },
    decorators: [withCpAuth, withMemoryRouter],
    beforeEach: cpApiBeforeEach,
    render: () => (
        <CpStoryFrame>
            <Route path="tenants" element={<CpTenantListPage />} />
        </CpStoryFrame>
    ),
} satisfies Meta<typeof CpTenantListPage>;

export default meta;
type Story = StoryObj<typeof meta>;

/** saas_admin (テナント作成への導線を表示する) */
export const SaasAdmin: Story = {};

/** saas_viewer (変更操作の入口を表示しない) */
export const SaasViewer: Story = { parameters: { cp_auth: { user_name: 'cp-viewer', roles: ['saas_viewer'] } } };

/** 取得中 */
export const Loading: Story = { parameters: { cp_api: { [LIST_KEY]: { status: 200, never_settles: true } } } };

/** テナントがまだ無い (saas_admin には最初の作成への導線を出す) */
export const Empty: Story = { parameters: { cp_api: { [LIST_KEY]: { status: 200, body: { items: [], next_cursor: null, total: 0 } } } } };

/** 絞り込みの結果が空 */
export const EmptyFiltered: Story = { parameters: { initial_path: '/cp/tenants?status=DELETED', cp_api: { [LIST_KEY]: { status: 200, body: { items: [], next_cursor: null, total: 0 } } } } };

/** 取得に失敗 (role="alert" で通知し、再試行できる) */
export const ErrorState: Story = { parameters: { cp_api: { [LIST_KEY]: problemStoryReply(503, 'service_unavailable') } } };

/** 次のページがある (「さらに読み込む」で連結する) */
export const HasMore: Story = {
    parameters: {
        cp_api: {
            [LIST_KEY]: (request: Request) => (new URL(request.url).searchParams.has('cursor')
                ? { status: 200, body: { items: [sampleListItem({ id: 'more-1', tenant_code: 'delta', name: 'Delta' })], next_cursor: null } }
                : { status: 200, body: { items: SAMPLE_LIST_ITEMS, next_cursor: 'cursor-1', total: SAMPLE_LIST_ITEMS.length + 1 } }),
        },
    },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await userEvent.click(await canvas.findByTestId('tenant-list-load-more'));
        await expect(await canvas.findByTestId('tenant-row-delta')).toBeInTheDocument();
    },
};
