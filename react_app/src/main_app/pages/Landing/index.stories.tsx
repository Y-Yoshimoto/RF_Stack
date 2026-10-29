import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { LandingPage } from '.';

const meta = {
    title: 'AP/Landing',
    component: LandingPage,
    parameters: { layout: 'fullscreen' },
    decorators: [withMemoryRouter],
} satisfies Meta<typeof LandingPage>;

export default meta;
type Story = StoryObj<typeof meta>;

/** 初期表示 */
export const Default: Story = {};

/** 未入力で送信すると、入力欄のエラーが表示される */
export const EmptyViolation: Story = {
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await userEvent.click(canvas.getByTestId('login-submit'));
        await expect(canvas.getByTestId('tenant-code-violation')).toHaveAttribute('data-violation', 'empty');
    },
};

/** 形式違反の入力 */
export const FormatViolation: Story = {
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await userEvent.type(canvas.getByTestId('login-tenant-code'), 'a');
        await userEvent.click(canvas.getByTestId('login-submit'));
        await expect(canvas.getByTestId('tenant-code-violation')).toHaveAttribute('data-violation', 'format');
    },
};

/** `?error=tenant_unavailable` で遷移してきた場合 */
export const WithErrorCode: Story = {
    parameters: { initial_path: '/?error=tenant_unavailable' },
};
