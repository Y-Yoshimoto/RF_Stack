// CP の認証状態フック (ControlPlaneAuthProvider / useCpAuth / useCpPermissions) のテスト
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { mockFetch, problemReply } from '@/shared/testing/fetch_mock';
import { ControlPlaneAuthProvider } from './ControlPlaneAuthProvider';
import { useCpAuth, useCpPermissions } from './useCpAuth';

const statusOf = (roles: string[]) => ({ authenticated: true, plane: 'cp', user: { sub: 's', preferred_username: 'cp-viewer', email: null, roles } });

afterEach(() => {
    vi.restoreAllMocks();
});

const wrapperOf = (assign: (url: string) => void) => ({ children }: { children: ReactNode }) => <ControlPlaneAuthProvider assignLocation={assign}>{children}</ControlPlaneAuthProvider>;

describe('ControlPlaneAuthProvider', () => {
    it('saas_viewer は参照のみ (useCpPermissions)', async () => {
        mockFetch({ 'GET /api/auth/cp/status': { status: 200, body: statusOf(['saas_viewer']) } });
        const { result } = renderHook(() => useCpPermissions(), { wrapper: wrapperOf(vi.fn()) });
        expect(result.current.can_read).toBe(false);
        await waitFor(() => expect(result.current).toEqual({ is_admin: false, is_viewer: true, can_read: true, can_write: false }));
    });

    it('未認証では権限なし、login は CP のログイン開始 API へ遷移する', async () => {
        mockFetch({ 'GET /api/auth/cp/status': problemReply(401, 'unauthenticated') });
        const assign = vi.fn();
        const { result } = renderHook(() => ({ auth: useCpAuth(), permissions: useCpPermissions() }), { wrapper: wrapperOf(assign) });
        await waitFor(() => expect(result.current.auth.state.status).toBe('unauthenticated'));
        expect(result.current.permissions.can_read).toBe(false);
        act(() => result.current.auth.login());
        expect(assign).toHaveBeenCalledWith('/api/auth/cp/login');
    });

    it('logout は応答の logout_url へ遷移する', async () => {
        mockFetch({
            'GET /api/auth/cp/status': { status: 200, body: statusOf(['saas_admin']) },
            'POST /api/auth/cp/logout': { status: 200, body: { logout_url: 'http://localhost:5173/cp/login' } },
        });
        const assign = vi.fn();
        const { result } = renderHook(() => useCpAuth(), { wrapper: wrapperOf(assign) });
        await waitFor(() => expect(result.current.state.status).toBe('authenticated'));
        await act(() => result.current.logout());
        expect(assign).toHaveBeenCalledWith('http://localhost:5173/cp/login');
    });
});
