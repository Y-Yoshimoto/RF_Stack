import type { Meta, StoryObj } from '@storybook/react-vite';
import { fn } from 'storybook/test';
import { Typography } from '@mui/material';
import HomeIcon from '@mui/icons-material/Home';
import PeopleIcon from '@mui/icons-material/People';
import BusinessIcon from '@mui/icons-material/Business';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppShell } from '.';

const meta = {
    title: 'Shared/AppShell',
    component: AppShell,
    parameters: { layout: 'fullscreen', initial_path: '/acme/' },
    decorators: [withMemoryRouter],
    args: {
        title: 'acme',
        caption: 'テナント',
        title_to: '/acme/',
        icon: <BusinessIcon />,
        user_name: 'taro',
        user_note: 'メンバー',
        nav_items: [
            { id: 'home', label: 'ホーム', to: '/acme/', end: true, icon: <HomeIcon /> },
            { id: 'users', label: '準備中の項目', to: null, icon: <PeopleIcon /> },
        ],
        onLogout: fn(() => Promise.resolve()),
        children: <Typography variant="h4" component="h1">ページの内容</Typography>,
    },
} satisfies Meta<typeof AppShell>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

/** バッジ付き (管理画面など) */
export const WithBadge: Story = { args: { badge_label: '管理画面' } };
