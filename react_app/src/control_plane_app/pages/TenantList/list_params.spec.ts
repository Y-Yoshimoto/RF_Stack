// テナント一覧の絞り込み・並び順と URL のクエリの対応のテスト
import { describe, expect, it } from 'vitest';
import { buildTenantListSearch, nextTenantSort, parseTenantListParams, sortColumnOf } from './list_params';

describe('parseTenantListParams', () => {
    it('クエリが無ければ、絞り込み無し・作成日時の降順', () => {
        expect(parseTenantListParams(new URLSearchParams(''))).toEqual({ status: null, sort: '-created_at' });
    });

    it('状態と並び順を取り出す', () => {
        expect(parseTenantListParams(new URLSearchParams('status=SUSPENDED&sort=name'))).toEqual({ status: 'SUSPENDED', sort: 'name' });
    });

    it('不正な値は無視する', () => {
        expect(parseTenantListParams(new URLSearchParams('status=BOGUS&sort=bogus'))).toEqual({ status: null, sort: '-created_at' });
    });
});

describe('buildTenantListSearch', () => {
    it('既定の値は含めない', () => {
        expect(buildTenantListSearch({ status: null, sort: '-created_at' }).toString()).toBe('');
        expect(buildTenantListSearch({ status: 'ACTIVE', sort: 'name' }).toString()).toBe('status=ACTIVE&sort=name');
    });
});

describe('nextTenantSort / sortColumnOf', () => {
    it('同じ列なら昇順と降順を入れ替え、別の列なら昇順から', () => {
        expect(nextTenantSort('name', 'name')).toBe('-name');
        expect(nextTenantSort('-name', 'name')).toBe('name');
        expect(nextTenantSort('-created_at', 'tenant_code')).toBe('tenant_code');
        expect(nextTenantSort('-created_at', 'created_at')).toBe('created_at');
    });

    it('並び順から、列と向きを求める', () => {
        expect(sortColumnOf('-tenant_code')).toEqual({ column: 'tenant_code', direction: 'desc' });
        expect(sortColumnOf('created_at')).toEqual({ column: 'created_at', direction: 'asc' });
    });
});
