/**
 * @desc CP のホーム (`/cp/`。ログイン成功後の遷移先。ダッシュボード)
 * ヘッダー・ナビゲーション・ログアウトは CpLayout が持つ。この画面は全体サマリー (状態別のテナント数と指標の合計) と、ログイン中のユーザーの権限を出す。
 * saas_viewer (can_write=false) には変更操作の UI を出さず、参照のみであることを知らせる (01 §11.2)。
 */
import { Link as RouterLink } from 'react-router-dom';
import { Alert, Box, Card, CardActionArea, CardContent, Chip, Stack, Typography } from '@mui/material';
import { classifyCpError } from '@/control_plane_app/api/errors';
import type { MetricsSummaryRead, TenantStatus } from '@/control_plane_app/api/contract';
import { useCpPermissions, useCpSession } from '@/control_plane_app/auth/useCpAuth';
import { CpErrorAlert } from '@/control_plane_app/components/CpErrorAlert';
import { formatMetricValue, metricLabelOf, TENANT_STATUS_LABEL, TENANT_STATUSES } from '@/control_plane_app/components/tenant_labels';
import { cpPermissionLabelOf } from '@/control_plane_app/layouts/CpLayout/labels';
import { useMetricsSummary } from '@/control_plane_app/metrics/useMetricsSummary';
import { CP_TENANTS_PATH } from '@/control_plane_app/paths';
import { PageLoading } from '@/shared/components/PageLoading';

/**
 * 状態別のテナント数から、削除済みを除く合計を求める関数
 * @param {MetricsSummaryRead['tenants_by_status']} by_status 状態別のテナント数
 * @returns {number} 合計
*/
export const countActiveTenants = (by_status: MetricsSummaryRead['tenants_by_status']): number => {
    return TENANT_STATUSES.filter((status) => status !== 'DELETED').reduce((sum, status) => sum + (by_status[status] ?? 0), 0);
};

/** 件数のカード (押すと、その状態で絞り込んだ一覧へ移る) */
const CountCard = ({ id, label, count, to }: { id: string; label: string; count: number; to: string }) => (
    <Card variant="outlined" data-testid={`cp-home-summary-${id}`}>
        <CardActionArea component={RouterLink} to={to} aria-label={`${label}のテナント: ${count} 件。一覧を開く`} sx={{ height: '100%' }}>
            <CardContent>
                <Typography variant="body2" color="text.secondary">{label}</Typography>
                <Typography variant="h4" component="p" aria-hidden data-testid={`cp-home-summary-${id}-count`}>{count}</Typography>
            </CardContent>
        </CardActionArea>
    </Card>
);

const SummarySection = ({ summary }: { summary: MetricsSummaryRead }) => {
    const total = countActiveTenants(summary.tenants_by_status);
    return (
        <Stack spacing={3}>
            <Box component="section" aria-labelledby="cp-home-status-heading">
                <Typography id="cp-home-status-heading" variant="h6" component="h2" gutterBottom>状態別のテナント数</Typography>
                <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' } }}>
                    <CountCard id="total" label="テナント数 (削除済みを除く)" count={total} to={CP_TENANTS_PATH} />
                    {TENANT_STATUSES.map((status: TenantStatus) => (
                        <CountCard key={status} id={status.toLowerCase()} label={TENANT_STATUS_LABEL[status]} count={summary.tenants_by_status[status] ?? 0} to={`${CP_TENANTS_PATH}?status=${status}`} />
                    ))}
                </Box>
            </Box>
            <Box component="section" aria-labelledby="cp-home-metrics-heading">
                <Typography id="cp-home-metrics-heading" variant="h6" component="h2" gutterBottom>指標の合計</Typography>
                {summary.metrics.length === 0 ? (
                    <Typography variant="body2" color="text.secondary" data-testid="cp-home-metrics-empty">集計された指標はまだありません。日次の集計後に表示されます。</Typography>
                ) : (
                    <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' } }}>
                        {summary.metrics.map((metric) => (
                            <Card key={metric.metric_key} variant="outlined" data-testid={`cp-home-metric-${metric.metric_key}`}>
                                <CardContent>
                                    <Typography variant="body2" color="text.secondary">{metricLabelOf(metric.metric_key)}</Typography>
                                    <Typography variant="h4" component="p" data-testid={`cp-home-metric-${metric.metric_key}-value`}>{formatMetricValue(metric.value)}</Typography>
                                </CardContent>
                            </Card>
                        ))}
                    </Box>
                )}
                <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 1 }} data-testid="cp-home-as-of">
                    {summary.as_of ? `集計日: ${summary.as_of} (UTC)。削除済みのテナントを除いた、各テナントの最新値の合計です。` : '集計日: まだ集計されていません。'}
                </Typography>
            </Box>
        </Stack>
    );
};

export const CpHomePage = () => {
    const { user } = useCpSession();
    const permissions = useCpPermissions();
    const { result, reload } = useMetricsSummary();
    const display_name = user.preferred_username ?? user.email ?? user.sub;
    return (
        <Stack spacing={3} data-testid="cp-home-page" data-can-write={permissions.can_write}>
            <Box>
                <Typography variant="h4" component="h1" gutterBottom>ダッシュボード</Typography>
                <Typography variant="body1" color="text.secondary">全テナントの状況の概要です。</Typography>
            </Box>

            {!permissions.can_write && (
                <Alert severity="info" data-testid="cp-home-viewer-notice">
                    閲覧専用の権限でログインしています。テナントの参照はできますが、作成・停止・再開・削除はできません。
                </Alert>
            )}

            {result.status === 'loading' && <PageLoading />}
            {result.status === 'error' && <CpErrorAlert error={classifyCpError(result.error)} test_id="cp-home-error" onReload={reload} always_retry />}
            {result.status === 'success' && <SummarySection summary={result.value} />}

            <Card variant="outlined" component="section" aria-labelledby="cp-home-user-heading">
                <CardContent>
                    <Typography id="cp-home-user-heading" variant="h6" component="h2" gutterBottom>ログイン中のユーザー</Typography>
                    <Stack spacing={1}>
                        <Typography variant="body1" data-testid="cp-home-user">{display_name}</Typography>
                        {user.email && <Typography variant="body2" color="text.secondary" data-testid="cp-home-email">{user.email}</Typography>}
                        <Stack direction="row" spacing={1}>
                            <Chip size="small" color="primary" label={cpPermissionLabelOf(permissions)} data-testid="cp-home-permission" />
                        </Stack>
                    </Stack>
                </CardContent>
            </Card>
        </Stack>
    );
};

export default CpHomePage;
