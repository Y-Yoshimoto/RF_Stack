// ログインのエラーコードと文言の対応のテスト
import { describe, expect, it } from 'vitest';
import { DEFAULT_LOGIN_ERROR_MESSAGE, LOGIN_ERROR_MESSAGES, loginErrorMessageOf } from './login_error';
import { LOGIN_ERROR_CODE } from './type';

describe('loginErrorMessageOf', () => {
    it('FastAPI の LoginErrorCode のすべてに文言がある', () => {
        for (const code of Object.values(LOGIN_ERROR_CODE)) expect(LOGIN_ERROR_MESSAGES[code]).toBeTruthy();
    });

    it('既知のコードは対応する文言', () => {
        expect(loginErrorMessageOf('tenant_unavailable')).toBe(LOGIN_ERROR_MESSAGES.tenant_unavailable);
    });

    it('未知のコードは汎用の文言、コードが無ければ null', () => {
        expect(loginErrorMessageOf('unknown_code')).toBe(DEFAULT_LOGIN_ERROR_MESSAGE);
        expect(loginErrorMessageOf('toString')).toBe(DEFAULT_LOGIN_ERROR_MESSAGE);
        expect(loginErrorMessageOf(null)).toBeNull();
        expect(loginErrorMessageOf('')).toBeNull();
    });
});
