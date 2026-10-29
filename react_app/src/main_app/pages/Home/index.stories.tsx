import type { Meta, StoryObj } from '@storybook/react-vite';
import { Route, Routes } from 'react-router-dom';
import { AppLayout } from '@/main_app/layouts/AppLayout';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppHomePage } from '.';

const meta = {
    title: 'AP/Home',
    component: AppHomePage,
    parameters: { layout: 'fullscreen', initial_path: '/alpha/' },
    decorators: [withAppAuth, withMemoryRouter],
    // ホームは認証後のレイアウトの中に表示される
    render: () => (
        <Routes>
            <Route path="/:tenantCode/*" element={<AppLayout />}>
                <Route index element={<AppHomePage />} />
            </Route>
        </Routes>
    ),
} satisfies Meta<typeof AppHomePage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const TenantAdmin: Story = {};

export const Member: Story = { parameters: { app_auth: { user_name: 'taro', roles: ['member'] } } };
