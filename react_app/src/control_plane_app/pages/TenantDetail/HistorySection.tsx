/**
 * @desc テナント詳細の払い出し履歴 (CP-ONB-03 / 04。新しいものが先頭)
 */
import { Box, Chip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material';
import type { ProvisioningHistoryRead } from '@/control_plane_app/api/contract';
import { formatDateTime, PROVISIONING_TYPE_LABEL, RUN_STATUS_COLOR, RUN_STATUS_LABEL } from '@/control_plane_app/components/tenant_labels';

export const HistorySection = ({ history }: { history: readonly ProvisioningHistoryRead[] }) => {
    const rows = [...history].sort((a, b) => b.started_at.localeCompare(a.started_at));
    return (
        <Box component="section" aria-labelledby="tenant-detail-history-heading" data-testid="tenant-detail-history">
            <Typography id="tenant-detail-history-heading" variant="h6" component="h2" gutterBottom>払い出し履歴</Typography>
            {rows.length === 0 ? (
                <Typography variant="body2" color="text.secondary" data-testid="tenant-detail-history-empty">払い出しの履歴はありません。</Typography>
            ) : (
                <TableContainer component={Box} tabIndex={0} role="region" aria-label="払い出し履歴の表" sx={{ border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: 'background.paper', overflowX: 'auto' }}>
                    <Table size="small" aria-label="払い出し履歴">
                        <TableHead>
                            <TableRow>
                                <TableCell scope="col">開始日時</TableCell>
                                <TableCell scope="col">種類</TableCell>
                                <TableCell scope="col">結果</TableCell>
                                <TableCell scope="col">ステップ</TableCell>
                                <TableCell scope="col">エラー</TableCell>
                                <TableCell scope="col">終了日時</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {rows.map((row) => (
                                <TableRow key={row.id} data-testid={`tenant-history-row-${row.id}`}>
                                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatDateTime(row.started_at)}</TableCell>
                                    <TableCell>{PROVISIONING_TYPE_LABEL[row.type] ?? row.type}</TableCell>
                                    <TableCell><Chip size="small" color={RUN_STATUS_COLOR[row.status] ?? 'default'} label={RUN_STATUS_LABEL[row.status] ?? row.status} /></TableCell>
                                    <TableCell>{row.step ?? '—'}</TableCell>
                                    <TableCell sx={{ overflowWrap: 'anywhere' }}>{row.error ?? '—'}</TableCell>
                                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatDateTime(row.finished_at)}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            )}
        </Box>
    );
};

export default HistorySection;
