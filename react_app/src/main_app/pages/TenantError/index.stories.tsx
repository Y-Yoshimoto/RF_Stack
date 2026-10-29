import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { TenantErrorPage } from '.';

const meta = {
    title: 'AP/TenantError',
    component: TenantErrorPage,
    parameters: { layout: 'fullscreen' },
    decorators: [withMemoryRouter],
    args: { kind: 'not_found', tenant_code: 'unknown-co' },
} satisfies Meta<typeof TenantErrorPage>;

export default meta;
type Story = StoryObj<typeof meta>;

export const NotFound: Story = {};

export const Suspended: Story = { args: { kind: 'suspended', tenant_code: 'alpha' } };

export const Unavailable: Story = { args: { kind: 'unavailable', tenant_code: 'alpha' } };

/** 別テナントでログイン中 (ログアウトして切り替える) */
export const Mismatch: Story = {
    args: { kind: 'mismatch', tenant_code: 'beta', session_tenant_code: 'alpha', onLogout: () => Promise.resolve() },
};

/** ログアウトに失敗した場合は、通知 (role="alert") を表示する */
export const MismatchLogoutFailed: Story = {
    args: { kind: 'mismatch', tenant_code: 'beta', session_tenant_code: 'alpha', onLogout: () => Promise.reject(new Error('failed')) },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await userEvent.click(canvas.getByTestId('tenant-error-logout'));
        // Snackbar は body 直下に描画されるため、canvasElement の外を探す
        await expect(await within(document.body).findByTestId('tenant-error-logout-error')).toHaveAttribute('role', 'alert');
    },
};
