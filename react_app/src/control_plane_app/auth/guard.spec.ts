// CP のルートガードの判定と権限のテスト
import { describe, expect, it } from 'vitest';
import type { SessionState } from '@/shared/auth/type';
import { cpPermissionsOf, decideCpAccess, decideCpLoginAccess } from './guard';
import type { CpSession } from './session';

const sessionOf = (roles: string[]): SessionState<CpSession> => ({
    status: 'authenticated',
    session: { user: { sub: 's', preferred_username: 'cp', email: null, roles } },
});

describe('cpPermissionsOf', () => {
    it('saas_admin は参照・変更ができる', () => {
        expect(cpPermissionsOf(['saas_admin'])).toEqual({ is_admin: true, is_viewer: false, can_read: true, can_write: true });
    });

    it('saas_viewer は参照のみ', () => {
        expect(cpPermissionsOf(['saas_viewer'])).toEqual({ is_admin: false, is_viewer: true, can_read: true, can_write: false });
    });

    it('両方を持つ場合は admin として扱う', () => {
        expect(cpPermissionsOf(['saas_viewer', 'saas_admin'])).toMatchObject({ is_admin: true, is_viewer: false, can_write: true });
    });

    it('CP のロールが無ければ何もできない', () => {
        expect(cpPermissionsOf(['tenant_admin'])).toEqual({ is_admin: false, is_viewer: false, can_read: false, can_write: false });
    });
});

describe('decideCpAccess', () => {
    it('saas_admin / saas_viewer は allow', () => {
        expect(decideCpAccess(sessionOf(['saas_admin'])).type).toBe('allow');
        expect(decideCpAccess(sessionOf(['saas_viewer'])).type).toBe('allow');
    });

    it('ロール不足は forbidden', () => {
        expect(decideCpAccess(sessionOf([]))).toEqual({ type: 'forbidden' });
    });

    it('未認証はログインへ、失敗は error', () => {
        expect(decideCpAccess({ status: 'unauthenticated' })).toEqual({ type: 'redirect_login' });
        expect(decideCpAccess({ status: 'error', error: 'e' })).toEqual({ type: 'error', error: 'e' });
        expect(decideCpAccess({ status: 'loading' })).toEqual({ type: 'loading' });
    });
});

describe('decideCpLoginAccess', () => {
    it('権限のあるセッションはホームへ', () => {
        expect(decideCpLoginAccess(sessionOf(['saas_viewer']))).toEqual({ type: 'redirect_home' });
    });

    it('未認証・ロール不足はログイン画面 (ホームとの往復を防ぐ)', () => {
        expect(decideCpLoginAccess({ status: 'unauthenticated' })).toEqual({ type: 'show_login' });
        expect(decideCpLoginAccess(sessionOf([]))).toEqual({ type: 'show_login' });
    });
});
