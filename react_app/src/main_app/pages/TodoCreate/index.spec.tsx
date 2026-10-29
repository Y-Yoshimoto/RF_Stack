// ToDo 作成画面のテスト (既定は private・公開範囲の切り替えと組織の必須・検証・送信内容・失敗の表示)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { ORGANIZATION_ID, OTHER_USER_ID, organizationOf } from '@/main_app/testing/app_test_support';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { SAMPLE_USERS, pageOf } from '@/main_app/testing/story_data';
import { TODO_ID, todoDetailOf } from '@/main_app/testing/todo_test_data';
import { AppTodoCreatePage } from '.';

const CREATE_KEY = 'POST /api/v1/todos';

afterEach(() => {
    vi.restoreAllMocks();
});

/**
 * 作成画面を描画する関数
 * @param {MockHandler} create 作成 API の応答
 * @returns {ReturnType<typeof mockFetch>} fetch の spy
*/
const renderCreate = (create: MockHandler = { status: 201, body: todoDetailOf({ visibility: 'private' }), headers: { ETag: '"1"' } }) => {
    const spy = mockFetch({
        [CREATE_KEY]: create,
        'GET /api/v1/users': { status: 200, body: pageOf(SAMPLE_USERS) },
        'GET /api/v1/organizations': { status: 200, body: pageOf([organizationOf()]) },
    });
    renderAppScreen(<Route path="/alpha/todos/new" element={<AppTodoCreatePage />} />, { path: '/alpha/todos/new', roles: ['member'] });
    return spy;
};

const createRequest = (spy: ReturnType<typeof mockFetch>) => calledRequests(spy).find((request) => request.method === 'POST');

describe('ToDo 作成画面', () => {
    it('閲覧範囲の既定は private で、組織の選択欄は出さない。優先度・ステータスの既定は 中・未着手', async () => {
        renderCreate();
        expect(await screen.findByTestId('todo-create-form')).toBeInTheDocument();
        expect(screen.getByTestId('todo-create-audience-visibility-private')).toBeChecked();
        expect(screen.queryByTestId('todo-create-audience-organizations')).toBeNull();
        expect(screen.getByTestId('todo-create-field-priority')).toHaveTextContent('中');
        expect(screen.getByTestId('todo-create-field-status')).toHaveTextContent('未着手');
    });

    it('入力欄とグループにラベルを付ける (タイトル・説明・期限・優先度・ステータス・閲覧範囲・担当者)', async () => {
        renderCreate();
        await screen.findByTestId('todo-create-form');
        for (const name of ['タイトル', '説明', '期限']) expect(screen.getByLabelText(new RegExp(name))).toBeInTheDocument();
        expect(screen.getByRole('combobox', { name: '優先度' })).toBeInTheDocument();
        expect(screen.getByRole('combobox', { name: 'ステータス' })).toBeInTheDocument();
        expect(screen.getByRole('radiogroup', { name: '閲覧範囲' })).toBeInTheDocument();
        expect(screen.getByRole('combobox', { name: '担当者' })).toBeInTheDocument();
    });

    it('タイトルが空なら、送信せずにエラーを表示してタイトルにフォーカスする', async () => {
        const user = userEvent.setup();
        const spy = renderCreate();
        await screen.findByTestId('todo-create-form');
        await user.click(screen.getByTestId('todo-create-submit'));
        expect(await screen.findByText('タイトルを入力してください。')).toBeInTheDocument();
        expect(screen.getByTestId('todo-create-field-title')).toHaveFocus();
        expect(screen.getByTestId('todo-create-field-title')).toHaveAttribute('aria-invalid', 'true');
        expect(createRequest(spy)).toBeUndefined();
    });

    it('閲覧範囲を organization にすると、組織の選択欄を出し、1 つも選ばずに送信するとエラーにする', async () => {
        const user = userEvent.setup();
        const spy = renderCreate();
        await screen.findByTestId('todo-create-form');
        await user.type(screen.getByTestId('todo-create-field-title'), '見積もりを作る');
        await user.click(screen.getByTestId('todo-create-audience-visibility-organization'));
        expect(await screen.findByTestId('todo-create-audience-organizations')).toBeInTheDocument();
        expect(await screen.findByTestId(`todo-create-audience-organization-${ORGANIZATION_ID}`)).not.toBeChecked();
        await user.click(screen.getByTestId('todo-create-submit'));
        expect(await screen.findByTestId('todo-create-audience-organizations-help')).toHaveTextContent('公開先の組織を 1 つ以上選んでください。');
        expect(createRequest(spy)).toBeUndefined();
    });

    it('private に戻すと、組織の選択欄は消え、組織は送らない', async () => {
        const user = userEvent.setup();
        const spy = renderCreate();
        await screen.findByTestId('todo-create-form');
        await user.type(screen.getByTestId('todo-create-field-title'), 'a');
        await user.click(screen.getByTestId('todo-create-audience-visibility-organization'));
        await user.click(await screen.findByTestId(`todo-create-audience-organization-${ORGANIZATION_ID}`));
        await user.click(screen.getByTestId('todo-create-audience-visibility-tenant'));
        expect(screen.queryByTestId('todo-create-audience-organizations')).toBeNull();
        await user.click(screen.getByTestId('todo-create-submit'));
        await vi.waitFor(() => expect(createRequest(spy)).toBeDefined());
        expect(await createRequest(spy)?.json()).toEqual({ title: 'a', description: null, due_date: null, priority: 'medium', status: 'open', visibility: 'tenant', assignee_ids: [] });
    });

    it('組織を選んで作成すると、organization_ids と担当者を送り、詳細へ遷移する', async () => {
        const user = userEvent.setup();
        const spy = renderCreate();
        await screen.findByTestId('todo-create-form');
        await user.type(screen.getByTestId('todo-create-field-title'), '見積もりを作る');
        await user.click(screen.getByTestId('todo-create-audience-visibility-organization'));
        await user.click(await screen.findByTestId(`todo-create-audience-organization-${ORGANIZATION_ID}`));
        await user.click(screen.getByRole('combobox', { name: '担当者' }));
        await user.click(await screen.findByRole('option', { name: 'Taro Yamada' }));
        await user.click(screen.getByTestId('todo-create-submit'));
        expect(await screen.findByTestId('location-probe')).toHaveTextContent(`/alpha/todos/${TODO_ID}`);
        expect(await createRequest(spy)?.json()).toMatchObject({ title: '見積もりを作る', visibility: 'organization', organization_ids: [ORGANIZATION_ID], assignee_ids: [OTHER_USER_ID] });
    });

    it('API が担当者の不正 (422) を返すと、role="alert" で表示し、画面に留まる', async () => {
        const user = userEvent.setup();
        renderCreate(problemReply(422, 'invalid_todo_assignees'));
        await screen.findByTestId('todo-create-form');
        await user.type(screen.getByTestId('todo-create-field-title'), 'a');
        await user.click(screen.getByTestId('todo-create-submit'));
        const alert = await screen.findByTestId('todo-create-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(alert).toHaveTextContent('担当者に指定できないユーザーが含まれています');
        expect(screen.queryByTestId('location-probe')).toBeNull();
    });
});
