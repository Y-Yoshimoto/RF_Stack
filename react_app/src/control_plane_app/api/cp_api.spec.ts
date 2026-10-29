// CP の API 関数 (URL の組み立て・エラーの分類) のテスト
import { describe, expect, it } from 'vitest';
import { ApiError } from '@/utils/libs/FetchComponents/problem';
import { problemReply } from '@/shared/testing/fetch_mock';
import type { ProblemDetails } from '@/utils/libs/FetchComponents/problem';
import { classifyCpError, CpGuardError } from './errors';
import { buildTenantMetricsUrl } from './metrics';
import { buildTenantListUrl, toTenantListQuery } from './tenants';

const apiErrorOf = (status: number, code: string, extra: Partial<ProblemDetails> = {}) => new ApiError(status, 'x', { ...(problemReply(status, code).body as ProblemDetails), ...extra });

describe('一覧のクエリ', () => {
    it('既定値はクエリに含めない', () => {
        expect(buildTenantListUrl(toTenantListQuery({}))).toBe('/api/v1/cp/tenants');
        expect(buildTenantListUrl(toTenantListQuery({ status: [], include_total: false }))).toBe('/api/v1/cp/tenants');
    });

    it('状態は重複を除いて並べ、同じ絞り込みは同じ URL になる', () => {
        const a = buildTenantListUrl(toTenantListQuery({ status: ['SUSPENDED', 'ACTIVE'], sort: '-name' }));
        const b = buildTenantListUrl(toTenantListQuery({ status: ['ACTIVE', 'SUSPENDED', 'ACTIVE'], sort: '-name' }));
        expect(a).toBe(b);
        expect(new URL(a, 'http://x').searchParams.get('status')).toBe('ACTIVE,SUSPENDED');
    });

    it('メトリクスの URL', () => {
        expect(buildTenantMetricsUrl('t1')).toBe('/api/v1/cp/tenants/t1/metrics');
        expect(buildTenantMetricsUrl('t1', { from: '2026-10-01' })).toBe('/api/v1/cp/tenants/t1/metrics?from=2026-10-01');
    });
});

describe('classifyCpError', () => {
    it.each([
        [412, 'tenant_version_conflict', 'version_conflict', true],
        [428, 'precondition_required', 'precondition_required', true],
        [400, 'invalid_if_match', 'precondition_required', true],
        [403, 'forbidden', 'forbidden', false],
        [404, 'tenant_not_found', 'not_found', false],
        [409, 'tenant_code_already_exists', 'conflict', false],
        [409, 'invalid_tenant_transition', 'conflict', true],
        [422, 'invalid_tenant_code', 'invalid_input', false],
        [502, 'tenant_realm_operation_failed', 'external_failure', false],
        [503, 'service_unavailable', 'unavailable', false],
        [500, 'tenant_service_error', 'unknown', false],
    ])('%i %s → %s', (status, code, kind, requires_reload) => {
        expect(classifyCpError(apiErrorOf(status, code))).toMatchObject({ status, code, kind, requires_reload });
    });

    it('ApiError でない失敗は unknown (元のエラーを保持する)', () => {
        const error = new TypeError('Failed to fetch');
        expect(classifyCpError(error)).toMatchObject({ kind: 'unknown', status: null, code: null, error });
    });

    it('フックが弾いた操作の分類', () => {
        expect(classifyCpError(new CpGuardError('write_not_allowed')).kind).toBe('forbidden');
        expect(classifyCpError(new CpGuardError('missing_etag'))).toMatchObject({ kind: 'precondition_required', requires_reload: true });
        expect(classifyCpError(new CpGuardError('action_in_progress')).kind).toBe('busy');
    });
});
