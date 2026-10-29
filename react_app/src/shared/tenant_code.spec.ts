// テナントコードの形式・予約語のテスト
import { describe, expect, it } from 'vitest';
import { isReservedTenantCode, normalizeTenantCodeInput, RESERVED_TENANT_CODES, tenantCodeViolationOf } from './tenant_code';

describe('tenantCodeViolationOf', () => {
    it.each(['alpha', 'beta', 'a1b', 'abc-def', 'a'.repeat(32), '123'])('受け付ける: %s', (value) => {
        expect(tenantCodeViolationOf(value)).toBeNull();
    });

    it.each([
        ['', 'empty'],
        ['ab', 'format'],
        ['a'.repeat(33), 'format'],
        ['Alpha', 'format'],
        ['-abc', 'format'],
        ['abc-', 'format'],
        ['ab--c', 'format'],
        ['abc_def', 'format'],
        ['favicon.ico', 'format'],
        ['api', 'reserved'],
        ['dev-login', 'reserved'],
        ['settings', 'reserved'],
    ])('受け付けない: %s → %s', (value, violation) => {
        expect(tenantCodeViolationOf(value)).toBe(violation);
    });
});

describe('予約語', () => {
    it('FastAPI の RESERVED_TENANT_CODES と同じ 22 語', () => {
        expect(RESERVED_TENANT_CODES.size).toBe(22);
        expect(RESERVED_TENANT_CODES.has('cp')).toBe(true);
    });

    it('大文字小文字を区別しない', () => {
        expect(isReservedTenantCode('API')).toBe(true);
        expect(isReservedTenantCode('alpha')).toBe(false);
    });
});

describe('normalizeTenantCodeInput', () => {
    it('前後の空白を除き小文字にする', () => {
        expect(normalizeTenantCodeInput('  Alpha ')).toBe('alpha');
    });
});
