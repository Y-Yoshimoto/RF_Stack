// Storybook と vitest で共有する CP のサンプルデータ (アプリ本体からは import しない)
import type { DailyMetricRead, MetricsSummaryRead, TenantDetail, TenantListItem, TenantRead } from '@/control_plane_app/api/contract';

/** サンプルのテナント ID (詳細のパスに使う) */
export const SAMPLE_TENANT_ID = '01900000-0000-7000-8000-000000000001';

/**
 * テナントのサンプルを作る関数
 * @param {Partial<TenantRead>} overrides 上書きする項目
 * @returns {TenantRead} テナント
*/
export const sampleTenant = (overrides: Partial<TenantRead> = {}): TenantRead => ({
    id: SAMPLE_TENANT_ID,
    tenant_code: 'alpha',
    name: 'Alpha 株式会社',
    status: 'ACTIVE',
    version: 3,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-02T00:00:00Z',
    deletion_requested_at: null,
    deleted_at: null,
    ...overrides,
});

/**
 * 一覧の要素のサンプルを作る関数
 * @param {Partial<TenantListItem>} overrides 上書きする項目
 * @returns {TenantListItem} 要素
*/
export const sampleListItem = (overrides: Partial<TenantListItem> = {}): TenantListItem => ({
    ...sampleTenant(),
    users_total: 12,
    users_active: 9,
    metrics_date: '2026-10-27',
    primary_metrics: [{ metric_key: 'todo_count', value: '1280', date: '2026-10-27' }],
    ...overrides,
});

/** 一覧のサンプル (稼働中・停止中・払い出し失敗) */
export const SAMPLE_LIST_ITEMS: TenantListItem[] = [
    sampleListItem(),
    sampleListItem({ id: '01900000-0000-7000-8000-000000000002', tenant_code: 'beta', name: 'Beta 商事', status: 'SUSPENDED', users_total: 3, users_active: 3, primary_metrics: [{ metric_key: 'todo_count', value: '40', date: '2026-10-27' }], created_at: '2026-10-05T03:00:00Z' }),
    sampleListItem({ id: '01900000-0000-7000-8000-000000000003', tenant_code: 'gamma', name: 'Gamma', status: 'FAILED', users_total: null, users_active: null, metrics_date: null, primary_metrics: [{ metric_key: 'todo_count', value: null, date: null }], created_at: '2026-10-20T09:30:00Z' }),
];

/**
 * 詳細のサンプルを作る関数 (払い出し履歴付き)
 * @param {Partial<TenantRead>} overrides 上書きする項目
 * @returns {TenantDetail} 詳細
*/
export const sampleDetail = (overrides: Partial<TenantRead> = {}): TenantDetail => ({
    ...sampleTenant(overrides),
    provisioning_history: [
        { id: 'h1', type: 'onboard', status: 'SUCCEEDED', step: 'activate', error: null, started_at: '2026-10-01T00:00:00Z', finished_at: '2026-10-01T00:00:10Z' },
        { id: 'h2', type: 'onboard', status: 'FAILED', step: 'create_realm', error: '認証基盤への接続がタイムアウトしました', started_at: '2026-09-30T23:00:00Z', finished_at: '2026-09-30T23:00:30Z' },
    ],
});

/** ダッシュボードのサマリーのサンプル */
export const SAMPLE_SUMMARY: MetricsSummaryRead = {
    tenants_by_status: { ACTIVE: 8, SUSPENDED: 1, FAILED: 1, PENDING_DELETION: 1, DELETED: 3 },
    metrics: [{ metric_key: 'todo_count', value: '12800' }, { metric_key: 'users_total', value: '120' }],
    as_of: '2026-10-27',
};

/** 直近 3 日のメトリクスのサンプル */
export const SAMPLE_METRIC_ITEMS: DailyMetricRead[] = [
    { date: '2026-10-25', metric_key: 'todo_count', value: '1200' },
    { date: '2026-10-26', metric_key: 'todo_count', value: '1250' },
    { date: '2026-10-27', metric_key: 'todo_count', value: '1280' },
    { date: '2026-10-26', metric_key: 'users_total', value: '11' },
    { date: '2026-10-27', metric_key: 'users_total', value: '12' },
];
