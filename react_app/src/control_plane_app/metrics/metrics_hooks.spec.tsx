// useTenantMetrics / useMetricsSummary とメトリクスの純粋関数のテスト
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { calledRequests, mockFetch, problemReply } from '@/shared/testing/fetch_mock';
import { CP_STATUS_KEY, CpTestProvider, cpStatusReply } from '@/control_plane_app/testing/cp_test_support';
import { classifyCpError, hasFieldErrorCode } from '@/control_plane_app/api/errors';
import { groupMetricsByKey, recentMetricsRange } from '@/control_plane_app/api/metrics';
import { useMetricsSummary } from './useMetricsSummary';
import { useTenantMetrics } from './useTenantMetrics';

const TENANT_ID = '01900000-0000-7000-8000-000000000001';
const METRICS_KEY = `GET /api/v1/cp/tenants/${TENANT_ID}/metrics`;
const METRICS_BODY = {
    tenant_id: TENANT_ID,
    from_date: '2026-09-29',
    to_date: '2026-10-28',
    items: [
        { date: '2026-10-28', metric_key: 'users_total', value: '3' },
        { date: '2026-10-27', metric_key: 'users_total', value: '2' },
        { date: '2026-10-27', metric_key: 'todo_count', value: '10' },
    ],
};

afterEach(() => {
    vi.restoreAllMocks();
});

const metricsQueries = (spy: ReturnType<typeof mockFetch>) => calledRequests(spy).filter((request) => request.url.includes('/metrics')).map((request) => new URL(request.url).searchParams);

describe('useTenantMetrics', () => {
    it('期間を省略するとクエリを付けない (サーバーの既定 = 直近 30 日)', async () => {
        const spy = mockFetch({ [CP_STATUS_KEY]: cpStatusReply(['saas_viewer']), [METRICS_KEY]: { status: 200, body: METRICS_BODY } });
        const { result } = renderHook(() => useTenantMetrics(TENANT_ID), { wrapper: CpTestProvider });
        await waitFor(() => expect(result.current.result).toEqual({ status: 'success', value: METRICS_BODY }));
        expect(metricsQueries(spy)[0].toString()).toBe('');
    });

    it('期間を指定すると from / to を付け、期間が変わると取り直す', async () => {
        const spy = mockFetch({ [CP_STATUS_KEY]: cpStatusReply(), [METRICS_KEY]: { status: 200, body: METRICS_BODY } });
        const { result, rerender } = renderHook(({ range }) => useTenantMetrics(TENANT_ID, range), { wrapper: CpTestProvider, initialProps: { range: { from: '2026-10-01', to: '2026-10-07' } } });
        await waitFor(() => expect(result.current.result.status).toBe('success'));
        rerender({ range: { from: '2026-10-01', to: '2026-10-07' } });
        rerender({ range: { from: '2026-09-01', to: '2026-10-07' } });
        await waitFor(() => expect(metricsQueries(spy)).toHaveLength(2));
        expect(metricsQueries(spy).map((params) => [params.get('from'), params.get('to')])).toEqual([['2026-10-01', '2026-10-07'], ['2026-09-01', '2026-10-07']]);
    });

    it('期間の不正 (422) は errors[].code で判別できる', async () => {
        const invalid = problemReply(422, 'validation_error');
        mockFetch({ [CP_STATUS_KEY]: cpStatusReply(), [METRICS_KEY]: { ...invalid, body: { ...(invalid.body as object), errors: [{ field: 'from', code: 'range_too_long', message: 'x' }] } } });
        const { result } = renderHook(() => useTenantMetrics(TENANT_ID, { from: '2024-01-01' }), { wrapper: CpTestProvider });
        await waitFor(() => expect(result.current.result.status).toBe('error'));
        const error = result.current.result.status === 'error' ? result.current.result.error : null;
        expect(classifyCpError(error).kind).toBe('invalid_input');
        expect(hasFieldErrorCode(error, 'range_too_long')).toBe(true);
    });
});

describe('useMetricsSummary', () => {
    it('サマリーを取得する', async () => {
        const body = { tenants_by_status: { ACTIVE: 2, SUSPENDED: 1 }, metrics: [{ metric_key: 'users_total', value: '5' }], as_of: '2026-10-27' };
        mockFetch({ [CP_STATUS_KEY]: cpStatusReply(['saas_viewer']), 'GET /api/v1/cp/metrics/summary': { status: 200, body } });
        const { result } = renderHook(() => useMetricsSummary(), { wrapper: CpTestProvider });
        await waitFor(() => expect(result.current.result).toEqual({ status: 'success', value: body }));
    });
});

describe('メトリクスの純粋関数', () => {
    it('recentMetricsRange は UTC の今日を含む直近 N 日', () => {
        // JST 2026-10-29 08:00 = UTC 2026-10-28 23:00
        const now = new Date('2026-10-28T23:00:00Z');
        expect(recentMetricsRange(30, now)).toEqual({ from: '2026-09-29', to: '2026-10-28' });
        expect(recentMetricsRange(1, now)).toEqual({ from: '2026-10-28', to: '2026-10-28' });
        expect(recentMetricsRange(1000, now).from).toBe('2025-10-28');
    });

    it('groupMetricsByKey は指標ごとに日付の昇順の系列にする (値は文字列のまま)', () => {
        expect(groupMetricsByKey(METRICS_BODY.items)).toEqual({
            users_total: [{ date: '2026-10-27', value: '2' }, { date: '2026-10-28', value: '3' }],
            todo_count: [{ date: '2026-10-27', value: '10' }],
        });
    });
});
