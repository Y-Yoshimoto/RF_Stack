/**
 * @desc テナント詳細の変更操作 (停止・再開・削除要求・払い出しの再実行。CP-OPS-03〜06 / CP-ONB-04)
 * 変更権限 (saas_admin) が無いときは何も描画しない (01 §11.2)。実行前に確認ダイアログを出す。
 * 結果は useTenantActions の failure (ページ側で表示) と、onUpdated 経由の詳細の更新に反映される。
 */
import { useState } from 'react';
import { Box, Button, Stack, TextField, Typography } from '@mui/material';
import PauseCircleIcon from '@mui/icons-material/PauseCircle';
import PlayCircleIcon from '@mui/icons-material/PlayCircle';
import ReplayIcon from '@mui/icons-material/Replay';
import DeleteIcon from '@mui/icons-material/Delete';
import type { InitialAdminInput, TenantRead, TenantStatus } from '@/control_plane_app/api/contract';
import { ConfirmDialog } from '@/control_plane_app/components/ConfirmDialog';
import type { TenantActionsState } from '@/control_plane_app/tenants/useTenantActions';
import { RetryDialog } from './RetryDialog';

type ActionKind = 'suspend' | 'resume' | 'delete' | 'retry';

/** 状態ごとに実行できる操作 (停止は ACTIVE、再開は SUSPENDED、再実行は FAILED、削除要求は ACTIVE / SUSPENDED / FAILED) */
const AVAILABLE_ACTIONS: Partial<Record<TenantStatus, readonly ActionKind[]>> = {
    ACTIVE: ['suspend', 'delete'],
    SUSPENDED: ['resume', 'delete'],
    FAILED: ['retry', 'delete'],
};

export type ActionPanelProps = {
    tenant: TenantRead;
    /** 詳細を取得したときの ETag (If-Match に渡す)。 */
    etag: string | null;
    actions: TenantActionsState;
};

/** 削除要求の確認 (テナントコードの入力を求める) */
const DeleteDialog = ({ tenant, pending, onConfirm, onCancel }: { tenant: TenantRead; pending: boolean; onConfirm: () => void; onCancel: () => void }) => {
    const [typed, setTyped] = useState('');
    return (
        <ConfirmDialog
            open
            test_id="tenant-delete-dialog"
            title="テナントの削除を要求しますか"
            description={(
                <>
                    テナント「{tenant.name}」({tenant.tenant_code}) を削除待ちにします。認証領域が無効化され、利用者はログインも API の利用もできなくなります。
                    猶予期間 (30 日) の経過後にデータが物理削除され、この画面からは復元できません。テナントコードは再利用できません。
                </>
            )}
            confirm_label="削除を要求する"
            confirm_color="error"
            pending={pending}
            confirm_disabled={typed !== tenant.tenant_code}
            onConfirm={onConfirm}
            onCancel={onCancel}
        >
            <TextField
                label={`確認のため、テナントコード「${tenant.tenant_code}」を入力`}
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                fullWidth
                autoFocus
                autoComplete="off"
                disabled={pending}
                slotProps={{ htmlInput: { 'data-testid': 'tenant-delete-confirm-input' } }}
            />
        </ConfirmDialog>
    );
};

export const ActionPanel = ({ tenant, etag, actions }: ActionPanelProps) => {
    const [dialog, setDialog] = useState<ActionKind | null>(null);
    if (!actions.can_write) return null;

    const available = AVAILABLE_ACTIONS[tenant.status] ?? [];
    const target = { tenant_id: tenant.id, etag };
    const is_pending = actions.pending !== null;

    const close = () => setDialog(null);
    const runConfirmed = async (kind: Exclude<ActionKind, 'retry'>) => {
        const run = { suspend: actions.suspend, resume: actions.resume, delete: actions.requestDeletion }[kind];
        await run(target);
        close();
    };
    const runRetry = async (initial_admin: InitialAdminInput) => {
        await actions.retry(target, initial_admin);
        close();
    };

    return (
        <Box component="section" aria-labelledby="tenant-detail-actions-heading" data-testid="tenant-detail-actions">
            <Typography id="tenant-detail-actions-heading" variant="h6" component="h2" gutterBottom>操作</Typography>
            {available.length === 0 ? (
                <Typography variant="body2" color="text.secondary" data-testid="tenant-detail-no-actions">この状態で実行できる操作はありません。</Typography>
            ) : (
                <Stack direction="row" spacing={1.5} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                    {available.includes('suspend') && <Button variant="outlined" color="warning" startIcon={<PauseCircleIcon />} disabled={is_pending} onClick={() => setDialog('suspend')} data-testid="tenant-action-suspend">停止</Button>}
                    {available.includes('resume') && <Button variant="outlined" startIcon={<PlayCircleIcon />} disabled={is_pending} onClick={() => setDialog('resume')} data-testid="tenant-action-resume">再開</Button>}
                    {available.includes('retry') && <Button variant="outlined" startIcon={<ReplayIcon />} disabled={is_pending} onClick={() => setDialog('retry')} data-testid="tenant-action-retry">払い出しを再実行</Button>}
                    {available.includes('delete') && <Button variant="outlined" color="error" startIcon={<DeleteIcon />} disabled={is_pending} onClick={() => setDialog('delete')} data-testid="tenant-action-delete">削除を要求</Button>}
                </Stack>
            )}

            {dialog === 'suspend' && (
                <ConfirmDialog
                    open
                    test_id="tenant-suspend-dialog"
                    title="テナントを停止しますか"
                    description={`テナント「${tenant.name}」(${tenant.tenant_code}) の認証領域を無効化します。再開するまで、利用者はログインも API の利用もできません。`}
                    confirm_label="停止する"
                    confirm_color="warning"
                    pending={actions.pending === 'suspend'}
                    onConfirm={() => void runConfirmed('suspend')}
                    onCancel={close}
                />
            )}
            {dialog === 'resume' && (
                <ConfirmDialog
                    open
                    test_id="tenant-resume-dialog"
                    title="テナントを再開しますか"
                    description={`テナント「${tenant.name}」(${tenant.tenant_code}) の認証領域を有効化し、利用者が再びログインできるようにします。`}
                    confirm_label="再開する"
                    pending={actions.pending === 'resume'}
                    onConfirm={() => void runConfirmed('resume')}
                    onCancel={close}
                />
            )}
            {dialog === 'delete' && <DeleteDialog tenant={tenant} pending={actions.pending === 'request_deletion'} onConfirm={() => void runConfirmed('delete')} onCancel={close} />}
            {dialog === 'retry' && <RetryDialog tenant_code={tenant.tenant_code} pending={actions.pending === 'retry'} onSubmit={(initial_admin) => void runRetry(initial_admin)} onCancel={close} />}
        </Box>
    );
};

export default ActionPanel;
