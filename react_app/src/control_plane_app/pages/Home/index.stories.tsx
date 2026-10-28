import type { Meta, StoryObj } from '@storybook/react-vite';
import { Route } from 'react-router-dom';
import { cpApiBeforeEach, CpStoryFrame, problemStoryReply } from '@/control_plane_app/testing/story_api';
import { SAMPLE_SUMMARY } from '@/control_plane_app/testing/story_data';
import { withCpAuth } from '@/control_plane_app/testing/auth_decorators';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { CpHomePage } from '.';

const SUMMARY_KEY = 'GET /api/v1/cp/metrics/summary';

const meta = {
    title: 'CP/Home',
    component: CpHomePage,
    parameters: { layout: 'fullscreen', initial_path: '/cp/', cp_api: { [SUMMARY_KEY]: { status: 200, body: SAMPLE_SUMMARY } } },
    decorators: [withCpAuth, withMemoryRouter],
    beforeEach: cpApiBeforeEach,
    // ホームは認証後のレイアウトの中に表示される
    render: () => (
        <CpStoryFrame>
            <Route index element={<CpHomePage />} />
        </CpStoryFrame>
    ),
} satisfies Meta<typeof CpHomePage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const SaasAdmin: Story = {};

/** saas_viewer には参照のみであることを知らせ、変更操作の UI を出さない */
export const SaasViewer: Story = { parameters: { cp_auth: { user_name: 'cp-viewer', roles: ['saas_viewer'] } } };

/** 取得中 */
export const Loading: Story = { parameters: { cp_api: { [SUMMARY_KEY]: { status: 200, never_settles: true } } } };

/** まだ集計されていない (テナントも指標も無い) */
export const Empty: Story = { parameters: { cp_api: { [SUMMARY_KEY]: { status: 200, body: { tenants_by_status: {}, metrics: [], as_of: null } } } } };

/** 取得に失敗 (role="alert" で通知し、再試行できる) */
export const ErrorState: Story = { parameters: { cp_api: { [SUMMARY_KEY]: problemStoryReply(503, 'service_unavailable') } } };
