// ユーザー作成画面のテスト (member にフォームが無い・検証・作成・一時パスワードのダイアログが閉じると消える・競合)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { OTHER_USER_ID, userDetailOf } from '@/main_app/testing/app_test_support';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { AppUserCreatePage } from '.';

const CREATE_KEY = 'POST /api/v1/users';
const SECRET = 'Tmp-Secret-456!';
const CREATED: MockHandler = {
    status: 201,
    body: { user: userDetailOf({ id: OTHER_USER_ID, display_name: 'Taro Yamada', version: 1, roles: ['member'] }), credentials: { username: 'taro@alpha.example', temporary_password: SECRET } },
    headers: { ETag: '"1"', 'Cache-Control': 'no-store' },
};

afterEach(() => {
    vi.restoreAllMocks();
});

const renderCreate = (reply: MockHandler = CREATED, roles?: string[]) => {
    const spy = mockFetch({ [CREATE_KEY]: reply });
    renderAppScreen(<Route path="/alpha/users/new" element={<AppUserCreatePage />} />, { path: '/alpha/users/new', roles });
    return spy;
};

/**
 * フォームに入力する関数
 * @param {ReturnType<typeof userEvent.setup>} user ユーザー操作
 * @returns {Promise<void>} 入力の完了
*/
const fillForm = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.type(screen.getByTestId('user-create-email'), 'taro@alpha.example');
    await user.type(screen.getByTestId('user-create-last-name'), 'Yamada');
    await user.type(screen.getByTestId('user-create-first-name'), 'Taro');
};

describe('ユーザー作成画面', () => {
    it('member にはフォームを表示せず、権限が必要なことを案内する (API も呼ばない)', () => {
        const spy = renderCreate(CREATED, ['member']);
        expect(screen.getByTestId('user-create-forbidden')).toBeInTheDocument();
        expect(screen.queryByTestId('user-create-form')).toBeNull();
        expect(spy).not.toHaveBeenCalled();
    });

    it('未入力で送信すると、項目ごとのエラーを表示し、最初のエラーの項目にフォーカスする (API は呼ばない)', async () => {
        const user = userEvent.setup();
        const spy = renderCreate();
        await user.click(screen.getByTestId('user-create-submit'));
        expect(screen.getByTestId('user-create-email')).toHaveAttribute('aria-invalid', 'true');
        expect(screen.getByTestId('user-create-email')).toHaveFocus();
        expect(screen.getByText('メールアドレスを入力してください。')).toBeInTheDocument();
        expect(screen.getByText('姓を入力してください。')).toBeInTheDocument();
        expect(spy).not.toHaveBeenCalled();
    });

    it('ロールを 1 つも選ばないと送信できない', async () => {
        const user = userEvent.setup();
        const spy = renderCreate();
        await fillForm(user);
        await user.click(screen.getByTestId('user-create-role-member'));
        await user.click(screen.getByTestId('user-create-submit'));
        expect(screen.getByText('ロールを 1 つ以上選んでください。')).toBeInTheDocument();
        expect(spy).not.toHaveBeenCalled();
    });

    it('作成すると、一時パスワードをダイアログに表示し、閉じると画面のどこにも残らない', async () => {
        const user = userEvent.setup();
        const spy = renderCreate();
        await fillForm(user);
        await user.click(screen.getByTestId('user-create-role-tenant_admin'));
        await user.click(screen.getByTestId('user-create-submit'));

        expect(await screen.findByRole('dialog', { name: '一時パスワード' })).toBeInTheDocument();
        expect(screen.getByTestId('credentials-dialog-password')).toHaveTextContent(SECRET);
        const request = calledRequests(spy).find((candidate) => candidate.method === 'POST');
        expect(await request?.json()).toEqual({ email: 'taro@alpha.example', last_name: 'Yamada', first_name: 'Taro', roles: ['member', 'tenant_admin'] });

        await user.click(screen.getByTestId('credentials-dialog-close'));
        await waitFor(() => expect(screen.queryByTestId('credentials-dialog')).toBeNull());
        expect(document.body).not.toHaveTextContent(SECRET);
        // 作成後の案内 (一時パスワードの再表示はできない)
        expect(screen.getByTestId('user-create-done')).toHaveTextContent('Taro Yamada を作成しました');
        expect(screen.getByTestId('user-create-done-detail')).toHaveAttribute('href', `/alpha/users/${OTHER_USER_ID}`);
        expect(screen.queryByTestId('user-create-form')).toBeNull();
    });

    it('「続けて作成する」で、空のフォームに戻る', async () => {
        const user = userEvent.setup();
        renderCreate();
        await fillForm(user);
        await user.click(screen.getByTestId('user-create-submit'));
        await user.click(await screen.findByTestId('credentials-dialog-close'));
        await user.click(await screen.findByTestId('user-create-done-again'));
        expect(screen.getByTestId('user-create-email')).toHaveValue('');
    });

    it('メールアドレスが重複すると (409)、role="alert" で理由を表示し、フォームを残す', async () => {
        const user = userEvent.setup();
        renderCreate(problemReply(409, 'user_already_exists'));
        await fillForm(user);
        await user.click(screen.getByTestId('user-create-submit'));
        const alert = await screen.findByTestId('user-create-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(alert).toHaveTextContent('このメールアドレスは既に使われています');
        expect(screen.queryByTestId('credentials-dialog')).toBeNull();
        expect(screen.getByTestId('user-create-email')).toHaveValue('taro@alpha.example');
    });
});
