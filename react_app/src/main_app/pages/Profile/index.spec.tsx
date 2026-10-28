// プロフィール画面のテスト (表示名・メール・ロール・所属組織・パスワード変更の案内・エラー)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { ORGANIZATION_ID, SELF_USER_ID, organizationDetailOf } from '@/main_app/testing/app_test_support';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { SAMPLE_ORGANIZATIONS, SAMPLE_USER_DETAILS, SECOND_ORGANIZATION_ID, meBodyOf, pageOf } from '@/main_app/testing/story_data';
import { AppProfilePage } from '.';

afterEach(() => {
    vi.restoreAllMocks();
});

const renderProfile = (replies: Record<string, MockHandler> = {}, roles: string[] = ['tenant_admin', 'member']) => {
    const spy = mockFetch({
        'GET /api/v1/me': { status: 200, body: meBodyOf(SELF_USER_ID, roles) },
        [`GET /api/v1/users/${SELF_USER_ID}`]: { status: 200, body: SAMPLE_USER_DETAILS[SELF_USER_ID], headers: { ETag: '"7"' } },
        'GET /api/v1/organizations': { status: 200, body: pageOf(SAMPLE_ORGANIZATIONS) },
        [`GET /api/v1/organizations/${ORGANIZATION_ID}`]: { status: 200, body: organizationDetailOf({ member_ids: [SELF_USER_ID] }), headers: { ETag: '"3"' } },
        [`GET /api/v1/organizations/${SECOND_ORGANIZATION_ID}`]: { status: 200, body: organizationDetailOf({ id: SECOND_ORGANIZATION_ID, name: '開発部', member_ids: [] }), headers: { ETag: '"1"' } },
        ...replies,
    });
    renderAppScreen(<Route path="/alpha/profile" element={<AppProfilePage />} />, { path: '/alpha/profile', roles });
    return spy;
};

describe('プロフィール画面', () => {
    it('表示名・ユーザー名・メール・ロール・テナントと、自分が所属する組織だけを表示する', async () => {
        renderProfile();
        expect(await screen.findByTestId('profile-organizations-list')).toBeInTheDocument();
        expect(screen.getByTestId('profile-display-name')).toHaveTextContent('Hanako Admin');
        expect(screen.getByTestId('profile-username')).toHaveTextContent('alpha-admin');
        expect(screen.getByTestId('profile-email')).toHaveTextContent('alpha-admin@alpha.example');
        expect(screen.getByTestId('profile-roles')).toHaveTextContent('テナント管理者');
        expect(screen.getByTestId('profile-tenant')).toHaveTextContent('alpha');
        expect(screen.getByTestId(`profile-organization-${ORGANIZATION_ID}`)).toHaveTextContent('営業部');
        expect(screen.getByTestId(`profile-organization-${ORGANIZATION_ID}`)).toHaveAttribute('href', `/alpha/organizations/${ORGANIZATION_ID}`);
        expect(screen.queryByTestId(`profile-organization-${SECOND_ORGANIZATION_ID}`)).toBeNull();
    });

    it('member でも表示できる (変更の UI は無い)', async () => {
        renderProfile({}, ['member']);
        await screen.findByTestId('profile-organizations-list');
        expect(screen.getByTestId('profile-roles')).toHaveTextContent('メンバー');
    });

    it('どの組織にも所属していなければ、その旨を表示する', async () => {
        renderProfile({ [`GET /api/v1/organizations/${ORGANIZATION_ID}`]: { status: 200, body: organizationDetailOf({ member_ids: [] }), headers: { ETag: '"3"' } } });
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

    it('所属組織の取得に失敗しても、基本情報は表示する', async () => {
        renderProfile({ 'GET /api/v1/organizations': problemReply(500, 'internal_error') });
        expect(await screen.findByTestId('profile-organizations-error')).toHaveAttribute('role', 'alert');
        expect(screen.getByTestId('profile-display-name')).toHaveTextContent('Hanako Admin');
    });
});
