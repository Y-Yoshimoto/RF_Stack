/**
 * @desc テナント詳細の基本情報 (テナントコード・名前・状態・日時)
 */
import { Alert, Box, Card, CardContent, Stack, Typography } from '@mui/material';
import type { TenantRead } from '@/control_plane_app/api/contract';
import { TenantStatusChip } from '@/control_plane_app/components/TenantStatusChip';
import { formatDateTime, TENANT_STATUS_NOTE } from '@/control_plane_app/components/tenant_labels';

type InfoRow = { id: string; label: string; value: string; monospace?: boolean };

/**
 * 基本情報の行を作る関数 (削除要求・削除の日時は、値があるときだけ出す)
 * @param {TenantRead} tenant テナント
 * @returns {InfoRow[]} 行
*/
const infoRowsOf = (tenant: TenantRead): InfoRow[] => {
    const rows: InfoRow[] = [
        { id: 'tenant-code', label: 'テナントコード', value: tenant.tenant_code },
        { id: 'name', label: 'テナント名', value: tenant.name },
        { id: 'id', label: 'テナント ID', value: tenant.id, monospace: true },
        { id: 'created-at', label: '作成日時', value: formatDateTime(tenant.created_at) },
        { id: 'updated-at', label: '更新日時', value: formatDateTime(tenant.updated_at) },
    ];
    if (tenant.deletion_requested_at) rows.push({ id: 'deletion-requested-at', label: '削除要求日時', value: formatDateTime(tenant.deletion_requested_at) });
    if (tenant.deleted_at) rows.push({ id: 'deleted-at', label: '削除日時', value: formatDateTime(tenant.deleted_at) });
    rows.push({ id: 'version', label: 'バージョン', value: String(tenant.version) });
    return rows;
};

/** 行を dt / dd の組にして並べる (dl の直下に dt / dd を並べるため、フラグメントで返す) */
const infoRows = (tenant: TenantRead) => infoRowsOf(tenant).flatMap((row) => [
    <Typography key={`${row.id}-label`} component="dt" variant="body2" color="text.secondary">{row.label}</Typography>,
    <Typography key={`${row.id}-value`} component="dd" variant="body1" sx={{ m: 0, overflowWrap: 'anywhere', fontFamily: row.monospace ? 'monospace' : undefined }} data-testid={`tenant-detail-${row.id}`}>{row.value}</Typography>,
]);

export const BasicInfo = ({ tenant }: { tenant: TenantRead }) => (
    <Card variant="outlined" component="section" aria-labelledby="tenant-detail-basic-heading" data-testid="tenant-detail-basic">
        <CardContent>
            <Stack spacing={2}>
                <Typography id="tenant-detail-basic-heading" variant="h6" component="h2">基本情報</Typography>
                <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
                    <Typography variant="body2" color="text.secondary" component="span">状態</Typography>
                    <TenantStatusChip status={tenant.status} test_id="tenant-detail-status" />
                </Stack>
                <Alert severity={tenant.status === 'FAILED' ? 'error' : 'info'} icon={false} data-testid="tenant-detail-status-note" role="note">{TENANT_STATUS_NOTE[tenant.status]}</Alert>
                <Box component="dl" sx={{ m: 0, display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'max-content 1fr' }, columnGap: 3, rowGap: 1 }}>
                    {infoRows(tenant)}
                </Box>
            </Stack>
        </CardContent>
    </Card>
);

export default BasicInfo;
