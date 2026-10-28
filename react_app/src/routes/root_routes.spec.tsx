// トップレベルのルーティングとルートガードの結合テスト (fetch のみモック)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { calledKeys, mockFetch, problemReply, type MockReply } from '@/shared/testing/fetch_mock';
import { createReservedRoutes, createRootRoutes, firstSegmentOf } from './root_routes';

const USER = { sub: 's', preferred_username: 'u', email: null };
const AP_ALPHA: MockReply = { status: 200, body: { authenticated: true, plane: 'app', tenant_code: 'alpha', user: { ...USER, roles: ['tenant_admin'] } } };
const cpStatusOf = (roles: string[]): MockReply => ({ status: 200, body: { authenticated: true, plane: 'cp', user: { ...USER, roles } } });
const UNAUTHENTICATED = problemReply(401, 'unauthenticated');
const tenantReply = (status: string): MockReply => ({ status: 200, body: { tenant_code: 'alpha', status } });

// 各プレーンは遅延読み込みのため、初回の import (テスト実行中の変換を含む) を待てるよう長めに待つ
const FIND_OPTIONS = { timeout: 5000 };
const findTestId = (test_id: string) => screen.findByTestId(test_id, {}, FIND_OPTIONS);

const renderAt = (path: string) => {
    const router = createMemoryRouter(createRootRoutes(), { initialEntries: [path] });
    render(<RouterProvider router={router} />);
    return router;
};

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

describe('静的ルート', () => {
    it('/ はランディング (認証状態を問い合わせない)', async () => {
        const spy = mockFetch({});
        renderAt('/');
        expect(await findTestId('landing-page')).toBeInTheDocument();
        expect(spy).not.toHaveBeenCalled();
    });

    it('/?error=tenant_unavailable はエラーの文言を出す', async () => {
        mockFetch({});
        renderAt('/?error=tenant_unavailable');
        expect(await findTestId('login-error')).toHaveAttribute('data-code', 'tenant_unavailable');
    });

    it.each(['/login', '/api/x', '/assets/a.js', '/settings'])('予約語 %s は NotFound (テナントとして扱わない)', async (path) => {
        const spy = mockFetch({});
        renderAt(path);
        expect(await findTestId('not-found-page')).toBeInTheDocument();
        expect(spy).not.toHaveBeenCalled();
    });

    it('予約語のルートは他の静的ルートと重複しない', () => {
        const segments = createReservedRoutes(new Set(['cp', 'dev-login'])).map(firstSegmentOf);
        expect(segments).not.toContain('cp');
        expect(segments).not.toContain('dev-login');
        expect(segments).toContain('link');
    });
});

describe('AP (/:tenantCode/*)', () => {
    it('同じテナントで認証済みならホーム。CP の状態は問い合わせない', async () => {
        const spy = mockFetch({ 'GET /api/auth/app/status': AP_ALPHA });
        renderAt('/alpha/');
        expect(await findTestId('app-home-page')).toBeInTheDocument();
        expect(calledKeys(spy)).not.toContain('GET /api/auth/cp/status');
    });

    it('別テナントで認証済みなら「別テナントでログイン中」', async () => {
        mockFetch({ 'GET /api/auth/app/status': AP_ALPHA });
        renderAt('/beta/');
        expect(await findTestId('tenant-error-page')).toHaveAttribute('data-kind', 'mismatch');
    });

    it('未認証ならログイン画面へ遷移し、テナントが ACTIVE ならログインを出す', async () => {
        mockFetch({ 'GET /api/auth/app/status': UNAUTHENTICATED, 'GET /api/v1/public/tenants/alpha': tenantReply('ACTIVE') });
        const router = renderAt('/alpha/sample/button');
        expect(await findTestId('app-login-page')).toBeInTheDocument();
        expect(router.state.location.pathname).toBe('/alpha/login');
    });

    it('ログイン画面: 存在しないテナントは not_found、停止中は suspended', async () => {
        mockFetch({ 'GET /api/auth/app/status': UNAUTHENTICATED, 'GET /api/v1/public/tenants/alpha': problemReply(404, 'not_found') });
        renderAt('/alpha/login');
        expect(await findTestId('tenant-error-page')).toHaveAttribute('data-kind', 'not_found');
        cleanup();
        vi.restoreAllMocks();
        mockFetch({ 'GET /api/auth/app/status': UNAUTHENTICATED, 'GET /api/v1/public/tenants/alpha': tenantReply('SUSPENDED') });
        renderAt('/alpha/login');
        expect(await findTestId('tenant-error-page')).toHaveAttribute('data-kind', 'suspended');
    });

    it('ログイン画面: 認証済みならホームへ (存在確認 API は呼ばない)', async () => {
        const spy = mockFetch({ 'GET /api/auth/app/status': AP_ALPHA });
        const router = renderAt('/alpha/login');
        expect(await findTestId('app-home-page')).toBeInTheDocument();
        expect(router.state.location.pathname).toBe('/alpha/');
        expect(calledKeys(spy)).not.toContain('GET /api/v1/public/tenants/alpha');
    });

    it('ログイン画面: ?error= の文言を出す', async () => {
        mockFetch({ 'GET /api/auth/app/status': UNAUTHENTICATED, 'GET /api/v1/public/tenants/alpha': tenantReply('ACTIVE') });
        renderAt('/alpha/login?error=invalid_auth_state');
        expect(await findTestId('login-error')).toHaveAttribute('data-code', 'invalid_auth_state');
    });

    it('形式違反のテナントコードは API を呼ばずに not_found', async () => {
        const spy = mockFetch({});
        renderAt('/Alpha/');
        expect(await findTestId('tenant-error-page')).toHaveAttribute('data-kind', 'not_found');
        expect(spy).not.toHaveBeenCalled();
    });

    it('状態 API の 401 以外の失敗はエラー画面 (ルートのエラーバウンダリー)', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => { });
        vi.spyOn(console, 'warn').mockImplementation(() => { });
        mockFetch({ 'GET /api/auth/app/status': problemReply(503, 'service_unavailable') });
        renderAt('/alpha/');
        expect(await screen.findByRole('alert', {}, FIND_OPTIONS)).toBeInTheDocument();
        expect(screen.queryByTestId('app-login-page')).toBeNull();
    });
});

describe('CP (/cp/*)', () => {
    it('saas_viewer はホームに入れる。AP の状態は問い合わせない', async () => {
        const spy = mockFetch({ 'GET /api/auth/cp/status': cpStatusOf(['saas_viewer']) });
        renderAt('/cp/');
        expect(await findTestId('cp-home-page')).toHaveAttribute('data-can-write', 'false');
        expect(calledKeys(spy)).not.toContain('GET /api/auth/app/status');
    });

    it('未認証は /cp/login へ', async () => {
        mockFetch({ 'GET /api/auth/cp/status': UNAUTHENTICATED });
        const router = renderAt('/cp/');
        expect(await findTestId('cp-login-page')).toBeInTheDocument();
        expect(router.state.location.pathname).toBe('/cp/login');
    });

    it('CP のロールが無いセッションは /cp/login?error=login_rejected へ', async () => {
        mockFetch({ 'GET /api/auth/cp/status': cpStatusOf([]) });
        const router = renderAt('/cp/');
        expect(await findTestId('login-error')).toHaveAttribute('data-code', 'login_rejected');
        expect(router.state.location.search).toBe('?error=login_rejected');
    });

    it('/cp/login: 認証済みならホームへ', async () => {
        mockFetch({ 'GET /api/auth/cp/status': cpStatusOf(['saas_admin']) });
        const router = renderAt('/cp/login');
        await waitFor(() => expect(router.state.location.pathname).toBe('/cp/'), FIND_OPTIONS);
        expect(await findTestId('cp-home-page')).toHaveAttribute('data-can-write', 'true');
    });
});
