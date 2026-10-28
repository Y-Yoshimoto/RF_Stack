/**
 * @desc CP のテナント詳細 (`/cp/tenants/:tenant_id`。CP-OPS-02〜06)
 * 基本情報・メトリクス推移・払い出し履歴を出し、変更権限 (saas_admin) があるときだけ停止・再開・削除要求・払い出しの再実行を出す (01 §11.2)。
 * 変更は保持している ETag を If-Match に付けて行う。412 は再読み込みを促し、409 は現在の状態や削除可能日時を表示する。
 */
import { useCallback } from 'react';
import { Link as RouterLink, useParams } from 'react-router-dom';
import { Alert, Box, Button, Link, Stack, Typography } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import RefreshIcon from '@mui/icons-material/Refresh';
import { useCpPermissions } from '@/control_plane_app/auth/useCpAuth';
import { CpErrorAlert } from '@/control_plane_app/components/CpErrorAlert';
import { CredentialsDialog } from '@/control_plane_app/components/CredentialsDialog';
import { TenantStatusChip } from '@/control_plane_app/components/TenantStatusChip';
import { ACTION_LABEL } from '@/control_plane_app/components/tenant_labels';
import { CP_TENANTS_PATH } from '@/control_plane_app/paths';
import type { TenantVersioned } from '@/control_plane_app/api/tenants';
import { useTenant } from '@/control_plane_app/tenants/useTenant';
import { useTenantActions, type TenantActionFailure, type TenantActionName } from '@/control_plane_app/tenants/useTenantActions';
import { PageLoading } from '@/shared/components/PageLoading';
import { ActionPanel } from './ActionPanel';
import { BasicInfo } from './BasicInfo';
import { HistorySection } from './HistorySection';
import { MetricsSection } from './MetricsSection';

/** 変更操作の失敗の通知 (どの操作かを添える) */
const FailureAlert = ({ failure, onReload }: { failure: TenantActionFailure; onReload: () => void }) => (
    <CpErrorAlert error={failure} test_id="tenant-detail-action-error" onReload={onReload}>
        <Typography variant="caption" component="p" sx={{ mt: 0.5 }}>実行した操作: {ACTION_LABEL[failure.action] ?? failure.action}</Typography>
    </CpErrorAlert>
);

const TenantDetailView = ({ tenant_id }: { tenant_id: string }) => {
    const { can_write } = useCpPermissions();
    const detail = useTenant(tenant_id);
    const { reload, applyUpdate } = detail;
    // 払い出しの再実行は履歴が増えるため取り直す。それ以外は更新後のテナントを反映する
    const handleUpdated = useCallback((update: TenantVersioned & { action: TenantActionName }) => {
        if (update.action === 'retry') reload();
        else applyUpdate({ tenant: update.tenant, etag: update.etag });
    }, [reload, applyUpdate]);
    const actions = useTenantActions({ onUpdated: handleUpdated });

    const reloadAfterFailure = () => {
        actions.clearFailure();
        reload();
    };

    let body;
    if (detail.status === 'loading') {
        body = <PageLoading />;
    } else if (detail.status === 'error' && detail.error) {
        body = detail.error.kind === 'not_found'
            ? (
                <Stack spacing={2} sx={{ alignItems: 'flex-start' }} data-testid="tenant-detail-not-found">
                    <Typography variant="h4" component="h1">テナントが見つかりません</Typography>
                    <Typography variant="body1" color="text.secondary">指定されたテナントは存在しないか、参照する権限がありません。</Typography>
                    <Button component={RouterLink} to={CP_TENANTS_PATH} variant="contained" data-testid="tenant-detail-back-to-list">テナント一覧へ戻る</Button>
                </Stack>
            )
            : <CpErrorAlert error={detail.error} test_id="tenant-detail-error" onReload={reload} always_retry />;
    } else if (detail.tenant) {
        const tenant = detail.tenant;
        body = (
            <Stack spacing={3}>
                <Stack direction="row" spacing={2} sx={{ alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', rowGap: 1 }}>
                    <Box sx={{ minWidth: 0 }}>
                        <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
                            <Typography variant="h4" component="h1" sx={{ overflowWrap: 'anywhere' }} data-testid="tenant-detail-heading">{tenant.name}</Typography>
                            <TenantStatusChip status={tenant.status} test_id="tenant-detail-heading-status" />
                        </Stack>
                        <Typography variant="body1" color="text.secondary" data-testid="tenant-detail-code">{tenant.tenant_code}</Typography>
                    </Box>
                    <Button startIcon={<RefreshIcon />} onClick={reload} data-testid="tenant-detail-reload">再読み込み</Button>
                </Stack>

                {!can_write && (
                    <Alert severity="info" data-testid="tenant-detail-viewer-notice">閲覧専用の権限のため、停止・再開・削除・払い出しの再実行はできません。</Alert>
                )}
                {actions.failure && <FailureAlert failure={actions.failure} onReload={reloadAfterFailure} />}

                <ActionPanel tenant={tenant} etag={detail.etag} actions={actions} />
                <BasicInfo tenant={tenant} />
                <MetricsSection tenant_id={tenant.id} />
                <HistorySection history={tenant.provisioning_history} />
            </Stack>
        );
    }

    return (
        <Stack spacing={2} data-testid="cp-tenant-detail-page" data-can-write={can_write}>
            <Link component={RouterLink} to={CP_TENANTS_PATH} underline="hover" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, alignSelf: 'flex-start' }} data-testid="tenant-detail-back">
                <ArrowBackIcon fontSize="small" aria-hidden />テナント一覧
            </Link>
            {body}
            <CredentialsDialog credentials={actions.issued_credentials} onClose={actions.dismissCredentials} />
        </Stack>
    );
};

export const CpTenantDetailPage = () => {
    const { tenant_id = '' } = useParams();
    // テナントが変わったら、操作・ダイアログの状態を持ち越さない
    return <TenantDetailView key={tenant_id} tenant_id={tenant_id} />;
};

export default CpTenantDetailPage;
