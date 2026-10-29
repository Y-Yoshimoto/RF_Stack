// プロフィール画面のテスト (表示名・メール・ロール・所属組織・パスワード変更の案内・エラー)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { MeOrganization } from '@/main_app/api/contract';
import { Route } from 'react-router-dom';
import { calledKeys, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { ORGANIZATION_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { SAMPLE_USER_DETAILS, SECOND_ORGANIZATION_ID, meBodyOf } from '@/main_app/testing/story_data';
import { AppProfilePage } from '.';

afterEach(() => {
    vi.restoreAllMocks();
});

const renderProfile = (replies: Record<string, MockHandler> = {}, roles: string[] = ['tenant_admin', 'member'], organizations?: MeOrganization[]) => {
    const spy = mockFetch({
        'GET /api/v1/me': { status: 200, body: meBodyOf(SELF_USER_ID, roles, organizations) },
        [`GET /api/v1/users/${SELF_USER_ID}`]: { status: 200, body: SAMPLE_USER_DETAILS[SELF_USER_ID], headers: { ETag: '"7"' } },
        ...replies,
    });
    renderAppScreen(<Route path="/alpha/profile" element={<AppProfilePage />} />, { path: '/alpha/profile', roles });
    return spy;
};

describe('プロフィール画面', () => {
    it('表示名・ユーザー名・メール・ロール・テナントと、自分が所属する組織だけを表示する', async () => {
        renderProfile({}, ['tenant_admin', 'member'], [{ id: ORGANIZATION_ID, name: '営業部' }]);
        expect(await screen.findByTestId('profile-organizations-list')).toBeInTheDocument();
        // 所属組織は /api/v1/me の応答で先に表示され、表示名はユーザー詳細の取得後に表示される
        await vi.waitFor(() => expect(screen.getByTestId('profile-display-name')).toHaveTextContent('Hanako Admin'));
        expect(screen.getByTestId('profile-username')).toHaveTextContent('alpha-admin');
        expect(screen.getByTestId('profile-email')).toHaveTextContent('alpha-admin@alpha.example');
        expect(screen.getByTestId('profile-roles')).toHaveTextContent('テナント管理者');
        expect(screen.getByTestId('profile-tenant')).toHaveTextContent('alpha');
        expect(screen.getByTestId(`profile-organization-${ORGANIZATION_ID}`)).toHaveTextContent('営業部');
        expect(screen.getByTestId(`profile-organization-${ORGANIZATION_ID}`)).toHaveAttribute('href', `/alpha/organizations/${ORGANIZATION_ID}`);
        expect(screen.queryByTestId(`profile-organization-${SECOND_ORGANIZATION_ID}`)).toBeNull();
    });

    it('所属組織は /api/v1/me の応答から表示し、組織の一覧・詳細は取得しない', async () => {
        const spy = renderProfile({}, ['member'], [{ id: ORGANIZATION_ID, name: '営業部' }, { id: SECOND_ORGANIZATION_ID, name: '開発部' }]);
        await screen.findByTestId('profile-organizations-list');
        const names = screen.getByTestId('profile-organizations-list').querySelectorAll('li');
        expect([...names].map((item) => item.textContent)).toEqual(['営業部', '開発部']);
        expect(calledKeys(spy).filter((key) => key.includes('/api/v1/organizations'))).toEqual([]);
    });

    it('member でも表示できる (変更の UI は無い)', async () => {
        renderProfile({}, ['member'], [{ id: ORGANIZATION_ID, name: '営業部' }]);
        await screen.findByTestId('profile-organizations-list');
        expect(screen.getByTestId('profile-roles')).toHaveTextContent('メンバー');
    });

    it('どの組織にも所属していなければ、その旨を表示する', async () => {
        renderProfile({}, ['member'], []);
        expect(await screen.findByTestId('profile-organizations-empty')).toBeInTheDocument();
    });

    it('パスワードの変更は Keycloak 側で行う旨を案内する', () => {
        renderProfile();
        expect(screen.getByTestId('profile-password')).toHaveTextContent('認証基盤 (Keycloak) のアカウント管理画面');
    });

    it('自分の情報の取得に失敗すると、role="alert" のエラーと再試行を表示する', async () => {
        const user = userEvent.setup();
        let calls = 0;
        renderProfile({ 'GET /api/v1/me': () => {
            calls += 1;
            return calls === 1 ? problemReply(500, 'internal_error') : { status: 200, body: meBodyOf() };
        } });
        const alert = await screen.findByTestId('profile-error');
        expect(alert).toHaveAttribute('role', 'alert');
        await user.click(screen.getByTestId('profile-error-reload'));
        expect(await screen.findByTestId('profile-info')).toBeInTheDocument();
    });

    it('ユーザー詳細の取得に失敗しても、所属組織は表示する', async () => {
        renderProfile({ [`GET /api/v1/users/${SELF_USER_ID}`]: problemReply(500, 'internal_error') }, ['member'], [{ id: ORGANIZATION_ID, name: '営業部' }]);
        expect(await screen.findByTestId('profile-user-error')).toHaveAttribute('role', 'alert');
        expect(screen.getByTestId(`profile-organization-${ORGANIZATION_ID}`)).toHaveTextContent('営業部');
    });
});
