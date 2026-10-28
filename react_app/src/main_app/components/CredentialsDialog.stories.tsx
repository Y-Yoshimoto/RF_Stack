import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { CredentialsDialog } from './CredentialsDialog';

const meta = {
    title: 'AP/CredentialsDialog',
    component: CredentialsDialog,
    parameters: { layout: 'fullscreen' },
    args: {
        credentials: { username: 'taro@alpha.example', temporary_password: 'Tmp-Secret-123!', user_id: 'u-1', display_name: 'Taro Yamada' },
        onClose: () => undefined,
    },
} satisfies Meta<typeof CredentialsDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

/** 一時パスワードの表示 (閉じると消える旨の警告、コピー、閉じる) */
export const Issued: Story = {
    play: async () => {
        const dialog = within(document.body);
        await expect(await dialog.findByRole('dialog', { name: '一時パスワード' })).toBeInTheDocument();
        await expect(dialog.getByTestId('credentials-dialog-warning')).toHaveTextContent('再表示できません');
    },
};

/** 破棄後 (何も表示しない) */
export const Dismissed: Story = { args: { credentials: null } };
