// テナントの存在確認と、ランディングの入力検証のテスト
import { afterEach, describe, expect, it, vi } from 'vitest';
import { calledKeys, mockFetch, problemReply } from '@/shared/testing/fetch_mock';
import { availabilityOf, lookupTenantAvailability } from './lookup';
import { parseTenantCodeEntry } from './useTenantCodeEntry';

afterEach(() => {
    vi.restoreAllMocks();
});

describe('availabilityOf', () => {
    it.each([
        ['ACTIVE', 'active'],
        ['SUSPENDED', 'suspended'],
        ['PENDING_DELETION', 'suspended'],
        ['DELETED', 'not_found'],
        ['PROVISIONING', 'unavailable'],
        ['FAILED', 'unavailable'],
        ['DEPROVISIONING', 'unavailable'],
    ] as const)('%s → %s', (status, availability) => {
        expect(availabilityOf(status)).toBe(availability);
    });
});

describe('lookupTenantAvailability', () => {
    it('公開 API の状態から利用可否を返す', async () => {
        const spy = mockFetch({ 'GET /api/v1/public/tenants/alpha': { status: 200, body: { tenant_code: 'alpha', status: 'SUSPENDED' } } });
        await expect(lookupTenantAvailability('alpha')).resolves.toBe('suspended');
        expect(calledKeys(spy)).toEqual(['GET /api/v1/public/tenants/alpha']);
    });

    it('404 は not_found', async () => {
        mockFetch({ 'GET /api/v1/public/tenants/zzz': problemReply(404, 'not_found') });
        await expect(lookupTenantAvailability('zzz')).resolves.toBe('not_found');
    });

    it('形式違反・予約語は API を呼ばずに not_found', async () => {
        const spy = mockFetch({});
        await expect(lookupTenantAvailability('Alpha')).resolves.toBe('not_found');
        await expect(lookupTenantAvailability('api')).resolves.toBe('not_found');
        expect(spy).not.toHaveBeenCalled();
    });

    it('429 / 503 は握り潰さずに送出する', async () => {
        mockFetch({ 'GET /api/v1/public/tenants/alpha': problemReply(429, 'too_many_requests') });
        await expect(lookupTenantAvailability('alpha')).rejects.toMatchObject({ status: 429 });
    });
});

describe('parseTenantCodeEntry', () => {
    it('整えてから検証する', () => {
        expect(parseTenantCodeEntry(' Alpha ')).toEqual({ ok: true, tenant_code: 'alpha' });
        expect(parseTenantCodeEntry('  ')).toEqual({ ok: false, violation: 'empty' });
        expect(parseTenantCodeEntry('a_b')).toEqual({ ok: false, violation: 'format' });
        expect(parseTenantCodeEntry('cp-')).toEqual({ ok: false, violation: 'format' });
        expect(parseTenantCodeEntry('login')).toEqual({ ok: false, violation: 'reserved' });
    });
});
