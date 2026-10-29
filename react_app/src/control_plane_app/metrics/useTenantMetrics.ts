/**
 * @description:
 * CP のテナントの日次メトリクスの推移を取得するカスタムフック (テナント詳細のメトリクス推移)
*/
import { useCpApiClient } from '@/control_plane_app/api/client';
import type { TenantMetricsQuery, TenantMetricsRead } from '@/control_plane_app/api/contract';
import { buildTenantMetricsUrl, fetchTenantMetrics } from '@/control_plane_app/api/metrics';
import { useAsyncValue, type AsyncResult } from '@/shared/hooks/useAsyncValue';

/**
 * CP のテナントのメトリクスの推移を取得するカスタムフック (ControlPlaneAuthProvider の内側で使う)
 * テナント・期間が変わると取り直す。期間を省略すると直近 30 日 (サーバーの既定。UTC の今日を含む)。
 * 任意の日数の期間は recentMetricsRange(days) で作る。実際の期間はレスポンスの from_date / to_date を表示に使うこと。
 * エラーは classifyCpError で分類する (期間の不正は 422 で、errors[].code が invalid_range / range_too_long)。
 * @param {string} tenant_id テナント ID
 * @param {TenantMetricsQuery} range 期間 (from / to は `YYYY-MM-DD`。いずれも含む)
 * @returns {{ result: AsyncResult<TenantMetricsRead>, reload: () => void }} 結果と再取得関数
*/
export const useTenantMetrics = (tenant_id: string, range: TenantMetricsQuery = {}): { result: AsyncResult<TenantMetricsRead>; reload: () => void } => {
    const client = useCpApiClient();
    return useAsyncValue(() => fetchTenantMetrics(client, tenant_id, range), `cp-tenant-metrics:${buildTenantMetricsUrl(tenant_id, range)}`);
};

export default useTenantMetrics;
