import type { Meta, StoryObj } from '@storybook/react-vite';
import { fn } from 'storybook/test';
import { AuthContainer } from '@/shared/layouts/AuthLayout';
import { CpLoginPage } from '.';

const meta = {
    title: 'CP/Login',
    component: CpLoginPage,
    parameters: { layout: 'fullscreen' },
    // 本番は AuthLayout (Outlet) の中に表示される
    // eslint-disable-next-line @typescript-eslint/naming-convention -- Storybook のデコレーターは第 1 引数をコンポーネント (<Story />) として描画する慣習のため
    decorators: [(Story) => <AuthContainer><Story /></AuthContainer>],
    args: { error_code: null, onLogin: fn() },
} satisfies Meta<typeof CpLoginPage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

/** `?error=login_rejected` (権限の無いアカウント) */
export const WithError: Story = { args: { error_code: 'login_rejected' } };
