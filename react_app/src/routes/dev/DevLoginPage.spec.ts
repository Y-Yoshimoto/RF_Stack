// 開発用ログインの URL 組み立てのテスト
import { describe, expect, it } from 'vitest';
import { buildDevLoginUrl } from './DevLoginPage';

describe('buildDevLoginUrl', () => {
    it('as の既定は alpha-admin、next は省略 (遷移先は FastAPI が決める)', () => {
        expect(buildDevLoginUrl(new URLSearchParams())).toBe('/api/auth/dev-login?as=alpha-admin');
    });

    it('as / next を引き渡す', () => {
        expect(buildDevLoginUrl(new URLSearchParams({ as: 'cp-admin', next: '/cp/' }))).toBe('/api/auth/dev-login?as=cp-admin&next=%2Fcp%2F');
    });

    it('パスでない next は渡さない', () => {
        expect(buildDevLoginUrl(new URLSearchParams({ next: '//evil.example/' }))).toBe('/api/auth/dev-login?as=alpha-admin');
        expect(buildDevLoginUrl(new URLSearchParams({ next: 'https://evil.example/' }))).toBe('/api/auth/dev-login?as=alpha-admin');
    });
});
