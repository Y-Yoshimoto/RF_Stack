/**
 * @desc テナント詳細のメトリクス推移 (CP-OPS-02 / CP-MET-05)
 * グラフライブラリが依存に無いため、日付 × 指標の表で表示する。期間は直近 7 / 30 / 90 日から選ぶ。
 */
import { useMemo, useState } from 'react';
import { Box, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import { classifyCpError } from '@/control_plane_app/api/errors';
import { recentMetricsRange } from '@/control_plane_app/api/metrics';
import { CpErrorAlert } from '@/control_plane_app/components/CpErrorAlert';
import { formatMetricValue, metricLabelOf } from '@/control_plane_app/components/tenant_labels';
import { useTenantMetrics } from '@/control_plane_app/metrics/useTenantMetrics';
import { PageLoading } from '@/shared/components/PageLoading';
import { buildMetricsTable } from './metrics_table';

/** 選べる期間 (日数) */
export const METRICS_RANGE_DAYS: readonly number[] = [7, 30, 90];

export const DEFAULT_METRICS_DAYS = 30;

export const MetricsSection = ({ tenant_id }: { tenant_id: string }) => {
    const [days, setDays] = useState<number>(DEFAULT_METRICS_DAYS);
    const range = useMemo(() => recentMetricsRange(days), [days]);
    const { result, reload } = useTenantMetrics(tenant_id, range);
    const table = result.status === 'success' ? buildMetricsTable(result.value.items) : null;
    return (
        <Box component="section" aria-labelledby="tenant-detail-metrics-heading" data-testid="tenant-detail-metrics">
            <Stack direction="row" spacing={2} sx={{ alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', rowGap: 1, mb: 1 }}>
                <Typography id="tenant-detail-metrics-heading" variant="h6" component="h2">メトリクス推移</Typography>
                <ToggleButtonGroup
                    exclusive
                    size="small"
                    value={days}
                    aria-label="表示する期間"
                    onChange={(_event, next: number | null) => {
                        if (next !== null) setDays(next);
                    }}
                    data-testid="tenant-metrics-range"
                >
                    {METRICS_RANGE_DAYS.map((value) => (
                        <ToggleButton key={value} value={value} data-testid={`tenant-metrics-range-${value}`}>直近 {value} 日</ToggleButton>
                    ))}
                </ToggleButtonGroup>
            </Stack>
            {result.status === 'loading' && <PageLoading />}
            {result.status === 'error' && <CpErrorAlert error={classifyCpError(result.error)} test_id="tenant-metrics-error" onReload={reload} always_retry />}
            {result.status === 'success' && table !== null && (table.rows.length === 0 ? (
                <Typography variant="body2" color="text.secondary" data-testid="tenant-metrics-empty">
                    この期間 ({result.value.from_date} 〜 {result.value.to_date}) に集計されたメトリクスはありません。日次の集計後に表示されます。
                </Typography>
            ) : (
                <TableContainer component={Box} tabIndex={0} role="region" aria-label="メトリクス推移の表" sx={{ maxHeight: 360, border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: 'background.paper' }}>
                    <Table size="small" stickyHeader data-testid="tenant-metrics-table">
                        <Typography component="caption" variant="body2" color="text.secondary" sx={{ captionSide: 'top', textAlign: 'left', px: 2, py: 1 }}>
                            {result.value.from_date} 〜 {result.value.to_date} (UTC の日付。新しい日付が上)
                        </Typography>
                        <TableHead>
                            <TableRow>
                                <TableCell scope="col">日付</TableCell>
                                {table.keys.map((key) => <TableCell key={key} scope="col" align="right">{metricLabelOf(key)}</TableCell>)}
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {table.rows.map((row) => (
                                <TableRow key={row.date} data-testid={`tenant-metrics-row-${row.date}`}>
                                    <TableCell component="th" scope="row">{row.date}</TableCell>
                                    {table.keys.map((key) => <TableCell key={key} align="right">{formatMetricValue(row.values[key])}</TableCell>)}
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            ))}
        </Box>
    );
};

export default MetricsSection;
