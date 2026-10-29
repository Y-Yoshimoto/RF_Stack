import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Route, Routes } from 'react-router-dom';
import { Typography } from '@mui/material';
import { withCpAuth } from '@/control_plane_app/testing/auth_decorators';
import { NotFoundPage } from '@/shared/pages/NotFound';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { CpLayout } from '.';

const meta = {
    title: 'CP/CpLayout',
    component: CpLayout,
    parameters: { layout: 'fullscreen', initial_path: '/cp/' },
    decorators: [withCpAuth, withMemoryRouter],
    // 本番と同じく、レイアウトの Outlet に子の画面を表示する
    render: () => (
        <Routes>
            <Route path="/cp/*" element={<CpLayout />}>
                <Route index element={<Typography variant="h4" component="h1">ページの内容</Typography>} />
                <Route path="*" element={<NotFoundPage embedded home_path="/cp/" home_label="ダッシュボードへ戻る" />} />
            </Route>
        </Routes>
    ),
} satisfies Meta<typeof CpLayout>;

export default meta;
type Story = StoryObj<typeof meta>;

/** saas_admin (変更操作の入口「テナント作成」を表示する) */
export const SaasAdmin: Story = {};

/** saas_viewer (変更操作の入口を表示しない) */
export const SaasViewer: Story = { parameters: { cp_auth: { user_name: 'cp-viewer', roles: ['saas_viewer'] } } };

/** 存在しないパス (レイアウトの中に NotFound を表示する) */
export const NotFoundInLayout: Story = { parameters: { initial_path: '/cp/unknown' } };

/** ログアウトに失敗した場合は、通知 (role="alert") を表示する */
export const LogoutFailed: Story = {
    parameters: { cp_auth: { logout_fails: true } },
    play: async ({ canvasElement: canvas_element }) => {
        await userEvent.click(within(canvas_element).getByTestId('logout-button'));
        await expect(await within(document.body).findByTestId('logout-button-error')).toHaveAttribute('role', 'alert');
    },
};
