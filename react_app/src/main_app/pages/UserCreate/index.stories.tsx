import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { OTHER_USER_ID, userDetailOf } from '@/main_app/testing/app_test_support';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { AppStoryFrame, appApiBeforeEach, problemStoryReply } from '@/main_app/testing/story_api';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppUserCreatePage } from '.';

const CREATE_KEY = 'POST /api/v1/users';

const meta = {
    title: 'AP/UserCreate',
    component: AppUserCreatePage,
    parameters: { layout: 'fullscreen', initial_path: '/alpha/users/new' },
    decorators: [withAppAuth, withMemoryRouter],
    beforeEach: appApiBeforeEach,
    render: () => (
        <AppStoryFrame>
            <Route path="users/new" element={<AppUserCreatePage />} />
        </AppStoryFrame>
    ),
} satisfies Meta<typeof AppUserCreatePage>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * フォームに入力して送信する (play の共通部分)
 * @param {HTMLElement} canvas_element 描画領域
 * @returns {Promise<void>} 完了
*/
const fillAndSubmit = async (canvas_element: HTMLElement) => {
    const canvas = within(canvas_element);
    await userEvent.type(await canvas.findByTestId('user-create-email'), 'taro@alpha.example');
    await userEvent.type(canvas.getByTestId('user-create-last-name'), 'Yamada');
    await userEvent.type(canvas.getByTestId('user-create-first-name'), 'Taro');
    await userEvent.click(canvas.getByTestId('user-create-submit'));
};

/** 入力フォーム */
export const Form: Story = {};

/** 未入力で送信した (項目ごとのエラー) */
export const ValidationErrors: Story = {
    play: async ({ canvasElement: canvas_element }) => {
        await userEvent.click(await within(canvas_element).findByTestId('user-create-submit'));
        await expect(within(canvas_element).getByTestId('user-create-email')).toHaveAttribute('aria-invalid', 'true');
    },
};

/** メンバーがこの URL を開いた (フォームを出さず、権限が必要なことを案内する) */
export const Member: Story = { parameters: { app_auth: { user_name: 'taro', roles: ['member'] } } };

/** メールアドレスが重複した (409) */
export const DuplicateEmail: Story = {
    parameters: { app_api: { [CREATE_KEY]: problemStoryReply(409, 'user_already_exists') } },
    play: async ({ canvasElement: canvas_element }) => {
        await fillAndSubmit(canvas_element);
        await expect(await within(canvas_element).findByTestId('user-create-error')).toHaveAttribute('role', 'alert');
    },
};

/** 作成に成功した (一時パスワードのダイアログを一度だけ表示する) */
export const CredentialsIssued: Story = {
    parameters: {
        app_api: {
            [CREATE_KEY]: {
                status: 201,
                body: { user: userDetailOf({ id: OTHER_USER_ID, display_name: 'Taro Yamada', version: 1, roles: ['member'] }), credentials: { username: 'taro@alpha.example', temporary_password: 'Tmp-Secret-123!' } },
                headers: { ETag: '"1"' },
            },
        },
    },
    play: async ({ canvasElement: canvas_element }) => {
        await fillAndSubmit(canvas_element);
        await expect(await within(document.body).findByRole('dialog', { name: '一時パスワード' })).toBeInTheDocument();
    },
};
