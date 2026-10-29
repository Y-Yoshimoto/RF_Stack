/**
 * @desc テナントの状態の表示 (色だけに頼らず、文言を必ず出す)
 */
import { Chip } from '@mui/material';
import type { TenantStatus } from '@/control_plane_app/api/contract';
import { TENANT_STATUS_COLOR, tenantStatusLabelOf } from './tenant_labels';

export const TenantStatusChip = ({ status, test_id = 'tenant-status' }: { status: TenantStatus; test_id?: string }) => (
    <Chip size="small" color={TENANT_STATUS_COLOR[status] ?? 'default'} label={tenantStatusLabelOf(status)} data-testid={test_id} data-status={status} />
);

export default TenantStatusChip;
