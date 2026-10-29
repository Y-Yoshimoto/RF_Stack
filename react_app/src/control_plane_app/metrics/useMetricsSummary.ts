/**
 * @description:
 * CP の全テナントのサマリー (ダッシュボード) を取得するカスタムフック
*/
import { useCpApiClient } from '@/control_plane_app/api/client';
import type { MetricsSummaryRead } from '@/control_plane_app/api/contract';
import { fetchMetricsSummary } from '@/control_plane_app/api/metrics';
import { useAsyncValue, type AsyncResult } from '@/shared/hooks/useAsyncValue';

/**
 * CP の全テナントのサマリーを取得するカスタムフック (ControlPlaneAuthProvider の内側で使う)
 * エラーは classifyCpError で分類する。
 * @returns {{ result: AsyncResult<MetricsSummaryRead>, reload: () => void }} 結果と再取得関数
*/
export const useMetricsSummary = (): { result: AsyncResult<MetricsSummaryRead>; reload: () => void } => {
    const client = useCpApiClient();
    return useAsyncValue(() => fetchMetricsSummary(client), 'cp-metrics-summary');
};

export default useMetricsSummary;
