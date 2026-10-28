import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, fn, userEvent, within } from 'storybook/test';
import { CredentialsDialog } from './CredentialsDialog';

const meta = {
    title: 'CP/CredentialsDialog',
    component: CredentialsDialog,
    parameters: { layout: 'fullscreen' },
    args: {
        credentials: { tenant_id: 'tenant-1', tenant_code: 'alpha', username: 'admin@example.com', temporary_password: 'Story-Temp-Pass-1!' },
        onClose: fn(),
    },
} satisfies Meta<typeof CredentialsDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

/** 一時パスワードを一度だけ表示する (閉じると消えることを明示する) */
export const Default: Story = {};

/** 「閉じる」で onClose を呼ぶ */
export const Close: Story = {
    play: async ({ args }) => {
        await userEvent.click(await within(document.body).findByTestId('credentials-dialog-close'));
        await expect(args.onClose).toHaveBeenCalled();
    },
};
