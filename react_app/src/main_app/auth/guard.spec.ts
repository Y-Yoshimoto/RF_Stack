// AP のルートガードの判定と API エラーの分類のテスト
import { describe, expect, it } from 'vitest';
import { classifyAppApiError } from '@/main_app/api/errors';
import type { SessionState } from '@/shared/auth/type';
import { ApiError } from '@/utils/libs/FetchComponents/problem';
import { decideAppAccess, decideAppLoginAccess } from './guard';
import type { AppSession } from './session';

const SESSION: AppSession = { tenant_code: 'alpha', user: { sub: 's', preferred_username: 'alpha-admin', email: null, roles: ['tenant_admin'] } };
const AUTHED: SessionState<AppSession> = { status: 'authenticated', session: SESSION };

describe('decideAppAccess', () => {
    it('同じテナントで認証済みなら allow', () => {
        expect(decideAppAccess(AUTHED, 'alpha')).toEqual({ type: 'allow', session: SESSION });
    });

    it('別テナントで認証済みなら tenant_mismatch', () => {
        expect(decideAppAccess(AUTHED, 'beta')).toEqual({ type: 'tenant_mismatch', session_tenant_code: 'alpha' });
    });

    it('未認証はログインへ、読み込み中は loading', () => {
        expect(decideAppAccess({ status: 'unauthenticated' }, 'alpha')).toEqual({ type: 'redirect_login' });
        expect(decideAppAccess({ status: 'loading' }, 'alpha')).toEqual({ type: 'loading' });
    });

    it('状態の取得失敗は error (未認証として扱わない)', () => {
        const error = new ApiError(503, 'Service Unavailable');
        expect(decideAppAccess({ status: 'error', error }, 'alpha')).toEqual({ type: 'error', error });
    });

    it('API の 403 で分かった利用不可は tenant_blocked (テナント不一致を優先)', () => {
        expect(decideAppAccess(AUTHED, 'alpha', 'suspended')).toEqual({ type: 'tenant_blocked', reason: 'suspended' });
        expect(decideAppAccess(AUTHED, 'beta', 'suspended').type).toBe('tenant_mismatch');
    });
});

describe('decideAppLoginAccess', () => {
    it('同じテナントで認証済みならホームへ', () => {
        expect(decideAppLoginAccess(AUTHED, 'alpha')).toEqual({ type: 'redirect_home' });
    });

    it('別テナントで認証済みなら tenant_mismatch', () => {
        expect(decideAppLoginAccess(AUTHED, 'beta')).toEqual({ type: 'tenant_mismatch', session_tenant_code: 'alpha' });
    });

    it('未認証はテナントの存在確認へ', () => {
        expect(decideAppLoginAccess({ status: 'unauthenticated' }, 'alpha')).toEqual({ type: 'check_tenant' });
    });

    it('状態の取得失敗は error', () => {
        expect(decideAppLoginAccess({ status: 'error', error: 'e' }, 'alpha')).toEqual({ type: 'error', error: 'e' });
    });
});

describe('classifyAppApiError', () => {
    const problemError = (status: number, code: string) => new ApiError(status, '', { type: '', title: '', status, detail: '', instance: '', code });

    it('401 は unauthenticated', () => {
        expect(classifyAppApiError(new ApiError(401, 'Unauthorized'))).toBe('unauthenticated');
    });

    it('403 tenant_inactive / tenant_unavailable はテナントの利用不可', () => {
        expect(classifyAppApiError(problemError(403, 'tenant_inactive'))).toBe('tenant_suspended');
        expect(classifyAppApiError(problemError(403, 'tenant_unavailable'))).toBe('tenant_unavailable');
    });

    it('それ以外は呼び出し元で扱う (null)', () => {
        expect(classifyAppApiError(problemError(403, 'forbidden'))).toBeNull();
        expect(classifyAppApiError(problemError(403, 'csrf_validation_failed'))).toBeNull();
        expect(classifyAppApiError(new ApiError(500, ''))).toBeNull();
        expect(classifyAppApiError(new TypeError('network'))).toBeNull();
    });
});
