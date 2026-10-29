// テスト用: CP のフックを ControlPlaneAuthProvider の内側で動かす補助 (アプリのコードからは import しない)
import type { ReactNode } from 'react';
import { ControlPlaneAuthProvider } from '@/control_plane_app/auth/ControlPlaneAuthProvider';
import type { TenantDetail, TenantListItem, TenantRead } from '@/control_plane_app/api/contract';
import type { MockReply } from '@/shared/testing/fetch_mock';

/** CP の認証ステータス API のキー (mockFetch に渡す) */
export const CP_STATUS_KEY = 'GET /api/auth/cp/status';

/**
 * CP の認証ステータス API の応答を作る関数
 * @param {string[]} roles ロール (saas_admin / saas_viewer)
 * @returns {MockReply} 応答
*/
export const cpStatusReply = (roles: string[] = ['saas_admin']): MockReply => ({
    status: 200,
    body: { authenticated: true, plane: 'cp', user: { sub: 's', preferred_username: 'cp-user', email: null, roles } },
});

/**
 * renderHook の wrapper (ControlPlaneAuthProvider。遷移は何もしない)
 * @param {{ children: ReactNode }} props 子要素
 * @returns {JSX.Element} プロバイダー
*/
export const CpTestProvider = ({ children }: { children: ReactNode }) => <ControlPlaneAuthProvider assignLocation={() => undefined}>{children}</ControlPlaneAuthProvider>;

/**
 * テナントのテストデータを作る関数
 * @param {Partial<TenantRead>} overrides 上書きする項目
 * @returns {TenantRead} テナント
*/
export const tenantOf = (overrides: Partial<TenantRead> = {}): TenantRead => ({
    id: '01900000-0000-7000-8000-000000000001',
    tenant_code: 'acme',
    name: 'ACME',
    status: 'ACTIVE',
    version: 3,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    deletion_requested_at: null,
    deleted_at: null,
    ...overrides,
});

/**
 * 一覧の要素のテストデータを作る関数
 * @param {string} id テナント ID
 * @returns {TenantListItem} 要素
*/
export const tenantItemOf = (id: string): TenantListItem => ({ ...tenantOf({ id, tenant_code: `t-${id}`, name: `T ${id}` }), users_total: 2, users_active: 1, metrics_date: '2026-10-27', primary_metrics: [{ metric_key: 'todo_count', value: '10', date: '2026-10-27' }] });

/**
 * 詳細のテストデータを作る関数
 * @param {Partial<TenantRead>} overrides 上書きする項目
 * @returns {TenantDetail} 詳細
*/
export const tenantDetailOf = (overrides: Partial<TenantRead> = {}): TenantDetail => ({
    ...tenantOf(overrides),
    provisioning_history: [{ id: 'h1', type: 'onboard', status: 'SUCCEEDED', step: 'activate', error: null, started_at: '2026-10-01T00:00:00Z', finished_at: '2026-10-01T00:00:10Z' }],
});
