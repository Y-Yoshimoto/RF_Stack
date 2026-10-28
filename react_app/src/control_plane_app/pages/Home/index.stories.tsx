import type { Meta, StoryObj } from '@storybook/react-vite';
import { Route, Routes } from 'react-router-dom';
import { CpLayout } from '@/control_plane_app/layouts/CpLayout';
import { withCpAuth } from '@/control_plane_app/testing/auth_decorators';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { CpHomePage } from '.';

const meta = {
    title: 'CP/Home',
    component: CpHomePage,
    parameters: { layout: 'fullscreen', initial_path: '/cp/' },
    decorators: [withCpAuth, withMemoryRouter],
    // ホームは認証後のレイアウトの中に表示される
    render: () => (
        <Routes>
            <Route path="/cp/*" element={<CpLayout />}>
                <Route index element={<CpHomePage />} />
            </Route>
        </Routes>
    ),
} satisfies Meta<typeof CpHomePage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const SaasAdmin: Story = {};

/** saas_viewer には参照のみであることを知らせ、変更操作の UI を出さない */
export const SaasViewer: Story = { parameters: { cp_auth: { user_name: 'cp-viewer', roles: ['saas_viewer'] } } };
