/**
 * @desc 払い出しの再実行ダイアログ (FAILED のテナント。CP-ONB-04)
 * 初期管理者を入力し直して再実行する。各ステップは冪等で、成功すると新しい一時パスワードが発行される。
 */
import { useRef, useState } from 'react';
import { Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, Stack, TextField } from '@mui/material';
import type { InitialAdminInput } from '@/control_plane_app/api/contract';
import { toInitialAdminInput, validateInitialAdminForm, type InitialAdminForm, type TenantCreateErrors } from '@/control_plane_app/pages/TenantCreate/validation';

export type RetryDialogProps = {
    tenant_code: string;
    pending: boolean;
    onSubmit: (initial_admin: InitialAdminInput) => void;
    onCancel: () => void;
};

const EMPTY_FORM: InitialAdminForm = { email: '', last_name: '', first_name: '' };

export const RetryDialog = ({ tenant_code, pending, onSubmit, onCancel }: RetryDialogProps) => {
    const [form, setForm] = useState<InitialAdminForm>(EMPTY_FORM);
    const [errors, setErrors] = useState<TenantCreateErrors>({});
    const email_input = useRef<HTMLInputElement | null>(null);

    const handleSubmit = (event: { preventDefault: () => void }) => {
        event.preventDefault();
        if (pending) return;
        const next = validateInitialAdminForm(form);
        setErrors(next);
        if (Object.keys(next).length > 0) {
            if (next.email) email_input.current?.focus();
            return;
        }
        onSubmit(toInitialAdminInput(form));
    };

    const change = (field: keyof InitialAdminForm) => (value: string) => {
        setForm((prev) => ({ ...prev, [field]: value }));
        setErrors((prev) => ({ ...prev, [field]: undefined }));
    };

    return (
        <Dialog
            open
            maxWidth="sm"
            fullWidth
            aria-labelledby="tenant-retry-dialog-title"
            aria-describedby="tenant-retry-dialog-description"
            onClose={() => {
                if (!pending) onCancel();
            }}
            data-testid="tenant-retry-dialog"
        >
            <Box component="form" noValidate onSubmit={handleSubmit}>
                <DialogTitle id="tenant-retry-dialog-title">払い出しを再実行</DialogTitle>
                <DialogContent>
                    <DialogContentText id="tenant-retry-dialog-description" sx={{ mb: 2 }}>
                        テナント「{tenant_code}」の払い出しを、失敗した時点から再実行します。初期管理者を指定してください。成功すると新しい一時パスワードを一度だけ表示します。
                    </DialogContentText>
                    <Stack spacing={2}>
                        <TextField
                            label="初期管理者のメールアドレス"
                            type="email"
                            required
                            autoFocus
                            autoComplete="off"
                            value={form.email}
                            onChange={(event) => change('email')(event.target.value)}
                            error={errors.email !== undefined}
                            helperText={errors.email}
                            disabled={pending}
                            inputRef={email_input}
                            slotProps={{ htmlInput: { 'data-testid': 'tenant-retry-email' } }}
                        />
                        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                            <TextField label="姓" autoComplete="off" fullWidth value={form.last_name} onChange={(event) => change('last_name')(event.target.value)} error={errors.last_name !== undefined} helperText={errors.last_name} disabled={pending} slotProps={{ htmlInput: { 'data-testid': 'tenant-retry-last-name' } }} />
                            <TextField label="名" autoComplete="off" fullWidth value={form.first_name} onChange={(event) => change('first_name')(event.target.value)} error={errors.first_name !== undefined} helperText={errors.first_name} disabled={pending} slotProps={{ htmlInput: { 'data-testid': 'tenant-retry-first-name' } }} />
                        </Stack>
                    </Stack>
                </DialogContent>
                <DialogActions>
                    <Button onClick={onCancel} disabled={pending} data-testid="tenant-retry-dialog-cancel">キャンセル</Button>
                    <Button type="submit" variant="contained" disabled={pending} startIcon={pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined} data-testid="tenant-retry-dialog-confirm">
                        {pending ? '再実行中…' : '再実行する'}
                    </Button>
                </DialogActions>
            </Box>
        </Dialog>
    );
};

export default RetryDialog;
