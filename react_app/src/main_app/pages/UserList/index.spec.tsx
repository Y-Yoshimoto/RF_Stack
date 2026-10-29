// ユーザー一覧画面のテスト (member に変更の導線が無い・表・絞り込み・さらに読み込む・空・エラー)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { pageOverflowOf, resetViewport, useMobileViewport } from '@/shared/testing/page_overflow';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { SAMPLE_USERS, THIRD_USER_ID, pageOf } from '@/main_app/testing/story_data';
import { AppLayout } from '@/main_app/layouts/AppLayout';
import { AppUserListPage } from '.';

const LIST_KEY = 'GET /api/v1/users';

afterEach(async () => {
    vi.restoreAllMocks();
    await resetViewport();
});

/**
 * 一覧画面を描画する関数
 * @param {MockHandler} reply 一覧 API の応答
 * @param {{ path?: string; roles?: string[] }} options 最初のパス・ロール
 * @returns {ReturnType<typeof mockFetch>} fetch の spy
*/
const renderList = (reply: MockHandler, { path = '/alpha/users', roles }: { path?: string; roles?: string[] } = {}) => {
    const spy = mockFetch({ [LIST_KEY]: reply });
    renderAppScreen(<Route path="/alpha/users" element={<AppUserListPage />} />, { path, roles });
    return spy;
};

const PAGE = { status: 200, body: pageOf(SAMPLE_USERS) };

describe('ユーザー一覧画面', () => {
    it('表に、表示名・メールアドレス・ロール・状態・最終ログインを表示し、見出しを th にする', async () => {
        renderList(PAGE);
        const table = await screen.findByTestId('user-table');
        expect(within(table).getAllByRole('columnheader').map((header) => header.textContent)).toEqual(['表示名', 'メールアドレス', 'ロール', '状態', '最終ログイン']);
        expect(screen.getByTestId(`user-link-${OTHER_USER_ID}`)).toHaveTextContent('Taro Yamada');
        expect(screen.getByTestId(`user-link-${OTHER_USER_ID}`)).toHaveAttribute('href', `/alpha/users/${OTHER_USER_ID}`);
        expect(screen.getByTestId(`user-email-${OTHER_USER_ID}`)).toHaveTextContent('taro@alpha.example');
        expect(screen.getByTestId(`user-roles-${SELF_USER_ID}`)).toHaveTextContent(/テナント管理者.*メンバー/);
        expect(screen.getByTestId(`user-roles-${OTHER_USER_ID}`)).toHaveTextContent('メンバー');
        expect(screen.getByTestId(`user-roles-${OTHER_USER_ID}`)).not.toHaveTextContent('テナント管理者');
        expect(screen.getByTestId(`user-status-${SELF_USER_ID}`)).toHaveTextContent('有効');
        expect(screen.getByTestId(`user-status-${THIRD_USER_ID}`)).toHaveTextContent('無効');
        expect(screen.getByTestId(`user-last-login-${OTHER_USER_ID}`)).toHaveTextContent('未ログイン');
        expect(screen.getByTestId('user-list-count')).toHaveTextContent('3 人を表示');
    });

    it('ロールが未同期 (roles が空) のユーザーは、色に頼らず「未同期」と文字で表示する', async () => {
        renderList({ status: 200, body: pageOf([SAMPLE_USERS[1], { ...SAMPLE_USERS[2], first_name: null, last_name: null, roles: [] }]) });
        await screen.findByTestId('user-table');
        expect(screen.getByTestId(`user-roles-${THIRD_USER_ID}`)).toHaveTextContent('未同期');
        expect(screen.getByTestId(`user-roles-${OTHER_USER_ID}`)).not.toHaveTextContent('未同期');
    });

    it('tenant_admin にだけ、ユーザー作成の導線を表示する', async () => {
        renderList(PAGE);
        expect(await screen.findByTestId('user-list-create')).toHaveAttribute('href', '/alpha/users/new');
        expect(screen.queryByTestId('user-list-readonly')).toBeNull();
    });

    it('member には、ユーザー作成の導線を表示せず、閲覧のみであることを案内する', async () => {
        renderList(PAGE, { roles: ['member'] });
        await screen.findByTestId('user-table');
        expect(screen.queryByTestId('user-list-create')).toBeNull();
        expect(screen.getByTestId('user-list-readonly')).toBeInTheDocument();
        expect(screen.getByTestId('app-user-list-page')).toHaveAttribute('data-can-write', 'false');
    });

    it('状態の絞り込みを API に渡し、URL に残す', async () => {
        const user = userEvent.setup();
        const spy = renderList(PAGE);
        await screen.findByTestId('user-table');
        await user.click(screen.getByRole('combobox', { name: '状態' }));
        await user.click(screen.getByRole('option', { name: '無効' }));
        await vi.waitFor(() => expect(calledRequests(spy).some((request) => new URL(request.url).searchParams.get('is_active') === 'false')).toBe(true));
    });

    it('URL の status を絞り込みに使う', async () => {
        const spy = renderList(PAGE, { path: '/alpha/users?status=active' });
        await screen.findByTestId('user-table');
        expect(new URL(calledRequests(spy)[0].url).searchParams.get('is_active')).toBe('true');
        expect(screen.getByRole('combobox', { name: '状態' })).toHaveTextContent('有効');
    });

    it('「さらに読み込む」で続きのページを連結する', async () => {
        const user = userEvent.setup();
        const spy = renderList((request) => {
            const cursor = new URL(request.url).searchParams.get('cursor');
            return cursor === null ? { status: 200, body: pageOf(SAMPLE_USERS.slice(0, 2), 'next-1') } : { status: 200, body: pageOf(SAMPLE_USERS.slice(2), null) };
        });
        await screen.findByTestId('user-table');
        expect(screen.getByTestId('user-list-count')).toHaveTextContent('2 人を表示 (続きがあります)');
        await user.click(screen.getByTestId('user-list-load-more'));
        await vi.waitFor(() => expect(screen.getByTestId('user-list-count')).toHaveTextContent('3 人を表示'));
        expect(screen.queryByTestId('user-list-load-more')).toBeNull();
        expect(new URL(calledRequests(spy)[1].url).searchParams.get('cursor')).toBe('next-1');
    });

    it('ユーザーがいなければ、空の案内を表示する', async () => {
        renderList({ status: 200, body: pageOf([]) });
        expect(await screen.findByTestId('user-list-empty')).toHaveTextContent('ユーザーがいません');
        expect(screen.queryByTestId('user-table')).toBeNull();
    });

    it('取得に失敗すると、role="alert" のエラーと再試行を表示し、再試行で取り直す', async () => {
        const user = userEvent.setup();
        let calls = 0;
        renderList(() => {
            calls += 1;
            return calls === 1 ? problemReply(500, 'internal_error') : { status: 200, body: pageOf(SAMPLE_USERS) };
        });
        const alert = await screen.findByTestId('user-list-error');
        expect(alert).toHaveAttribute('role', 'alert');
        await user.click(screen.getByTestId('user-list-error-reload'));
        expect(await screen.findByTestId('user-table')).toBeInTheDocument();
    });

    it('狭い幅 (Pixel 5 相当) でも、表は表のコンテナの中でスクロールし、ページ全体は横にはみ出さない', async () => {
        await useMobileViewport();
        mockFetch({ [LIST_KEY]: { status: 200, body: pageOf(SAMPLE_USERS, 'next-1') } });
        // 本番と同じく、認証後のレイアウト (本文の余白) の中に表示する
        renderAppScreen(<Route path="/:tenantCode/*" element={<AppLayout />}><Route path="users" element={<AppUserListPage />} /></Route>, { path: '/alpha/users' });
        await screen.findByTestId('user-table');
        expect(pageOverflowOf()).toMatchObject({ ok: true });
    });
});
