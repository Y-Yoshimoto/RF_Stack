import type { Meta, StoryObj } from '@storybook/react-vite';
import { fn } from 'storybook/test';
import { AuthContainer } from '@/shared/layouts/AuthLayout';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppLoginPage } from '.';

const meta = {
    title: 'AP/Login',
    component: AppLoginPage,
    parameters: { layout: 'fullscreen' },
    // 本番は AuthLayout (Outlet) の中に表示される
    // eslint-disable-next-line @typescript-eslint/naming-convention -- Storybook のデコレーターは第 1 引数をコンポーネント (<Story />) として描画する慣習のため
    decorators: [(Story) => <AuthContainer><Story /></AuthContainer>, withMemoryRouter],
    args: { tenant_code: 'alpha', error_code: null, onLogin: fn() },
} satisfies Meta<typeof AppLoginPage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

/** `?error=invalid_auth_state` (ログインの有効期限切れ) */
export const WithError: Story = { args: { error_code: 'invalid_auth_state' } };

/** 一覧に無いコードは汎用の文言になる */
export const WithUnknownError: Story = { args: { error_code: 'something_else' } };

/** 長いテナントコード */
export const LongTenantCode: Story = { args: { tenant_code: 'a-very-long-tenant-code-example-1234' } };
