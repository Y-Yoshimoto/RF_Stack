import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Route, Routes } from 'react-router-dom';
import { Typography } from '@mui/material';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { NotFoundPage } from '@/shared/pages/NotFound';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppLayout } from '.';

const meta = {
    title: 'AP/AppLayout',
    component: AppLayout,
    parameters: { layout: 'fullscreen', initial_path: '/alpha/' },
    decorators: [withAppAuth, withMemoryRouter],
    // 本番と同じく、レイアウトの Outlet に子の画面を表示する
    render: () => (
        <Routes>
            <Route path="/:tenantCode/*" element={<AppLayout />}>
                <Route index element={<Typography variant="h4" component="h1">ページの内容</Typography>} />
                <Route path="*" element={<NotFoundPage embedded home_path="/alpha/" home_label="ホームへ戻る" />} />
            </Route>
        </Routes>
    ),
} satisfies Meta<typeof AppLayout>;

export default meta;
type Story = StoryObj<typeof meta>;

/** テナント管理者 */
export const TenantAdmin: Story = {};

/** メンバー */
export const Member: Story = { parameters: { app_auth: { user_name: 'taro', roles: ['member'] } } };

/** 長いユーザー名・テナントコード (ヘッダーで溢れないこと) */
export const LongNames: Story = {
    parameters: { app_auth: { tenant_code: 'a-very-long-tenant-code-example-1234', user_name: 'a-very-long-user-name-that-keeps-going' } },
};

/** 存在しないパス (レイアウトの中に NotFound を表示する) */
export const NotFoundInLayout: Story = { parameters: { initial_path: '/alpha/unknown' } };

/** ログアウトに失敗した場合は、通知 (role="alert") を表示する */
export const LogoutFailed: Story = {
    parameters: { app_auth: { logout_fails: true } },
    play: async ({ canvasElement: canvas_element }) => {
        await userEvent.click(within(canvas_element).getByTestId('logout-button'));
        await expect(await within(document.body).findByTestId('logout-button-error')).toHaveAttribute('role', 'alert');
    },
};
