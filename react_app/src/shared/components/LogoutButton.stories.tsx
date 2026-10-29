import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, fn, userEvent, within } from 'storybook/test';
import { LogoutButton } from './LogoutButton';

const meta = {
    title: 'Shared/LogoutButton',
    component: LogoutButton,
    args: { onLogout: fn(() => Promise.resolve()) },
} satisfies Meta<typeof LogoutButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = { args: { variant: 'contained', color: 'primary' } };

/** 失敗時は、通知 (role="alert") を表示し、閉じるまで残す */
export const Failed: Story = {
    args: { variant: 'contained', color: 'primary', onLogout: fn(() => Promise.reject(new Error('failed'))) },
    play: async ({ canvasElement: canvas_element }) => {
        await userEvent.click(within(canvas_element).getByTestId('logout-button'));
        await expect(await within(document.body).findByTestId('logout-button-error')).toHaveAttribute('role', 'alert');
    },
};
