import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { AppStoryFrame, appApiBeforeEach, problemStoryReply } from '@/main_app/testing/story_api';
import { todoStoryApiOf } from '@/main_app/pages/TodoCommon/story_support';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppTodoCreatePage } from '.';

const meta = {
    title: 'AP/TodoCreate',
    component: AppTodoCreatePage,
    parameters: { layout: 'fullscreen', initial_path: '/alpha/todos/new', app_api: todoStoryApiOf() },
    decorators: [withAppAuth, withMemoryRouter],
    beforeEach: appApiBeforeEach,
    render: () => (
        <AppStoryFrame>
            <Route path="todos/new" element={<AppTodoCreatePage />} />
        </AppStoryFrame>
    ),
} satisfies Meta<typeof AppTodoCreatePage>;

export default meta;
type Story = StoryObj<typeof meta>;

/** 既定 (閲覧範囲は非公開) */
export const Default: Story = {
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-create-audience-visibility-private')).toBeChecked();
        await expect(canvas.queryByTestId('todo-create-audience-organizations')).toBeNull();
    },
};

/** 閲覧範囲を「組織」にした (公開先の組織を 1 つ以上選ぶ) */
export const OrganizationVisibility: Story = {
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await userEvent.click(await canvas.findByTestId('todo-create-audience-visibility-organization'));
        await expect(await canvas.findByTestId('todo-create-audience-organizations')).toBeInTheDocument();
    },
};

/** タイトルが空のまま送信した (エラーの読み上げとフォーカス) */
export const ValidationError: Story = {
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await userEvent.click(await canvas.findByTestId('todo-create-submit'));
        await expect(await canvas.findByText('タイトルを入力してください。')).toBeInTheDocument();
    },
};

/** 作成に失敗した (担当者に指定できないユーザー: 422) */
export const CreateFailed: Story = {
    parameters: { app_api: todoStoryApiOf(['tenant_admin', 'member'], { 'POST /api/v1/todos': problemStoryReply(422, 'invalid_todo_assignees') }) },
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await userEvent.type(await canvas.findByTestId('todo-create-field-title'), '見積もりを作る');
        await userEvent.click(canvas.getByTestId('todo-create-submit'));
        await expect(await canvas.findByTestId('todo-create-error')).toHaveAttribute('role', 'alert');
    },
};
