/**
 * @desc 組織の作成ダイアログ (組織名の入力)
 * 開くたびに入力を空にするため、呼び出し側は開いているときだけ描画する。失敗はダイアログの中に表示する (背面の画面は読めないため)。
 */
import { useRef, useState, type FormEvent } from 'react';
import { Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, Stack, TextField } from '@mui/material';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import type { AppErrorInfo } from '@/main_app/api/errors';
import { organizationNameErrorOf } from '@/main_app/pages/OrganizationDetail/validation';

export type OrganizationCreateDialogProps = {
    /** 直前の作成の失敗 (無ければ null)。 */
    failure: AppErrorInfo | null;
    pending: boolean;
    /** 作成する (成功したら true。閉じるのは呼び出し側)。 */
    onSubmit: (name: string) => Promise<boolean>;
    onClose: () => void;
};

const TITLE_ID = 'organization-create-title';
const DESCRIPTION_ID = 'organization-create-description';

export const OrganizationCreateDialog = ({ failure, pending, onSubmit, onClose }: OrganizationCreateDialogProps) => {
    const [name, setName] = useState('');
    const [error, setError] = useState<string | undefined>(undefined);
    const input_ref = useRef<HTMLInputElement | null>(null);

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        const found = organizationNameErrorOf(name);
        setError(found);
        if (found) {
            input_ref.current?.focus();
            return;
        }
        await onSubmit(name.trim());
    };

    return (
        <Dialog
            open
            maxWidth="sm"
            fullWidth
            aria-labelledby={TITLE_ID}
            aria-describedby={DESCRIPTION_ID}
            onClose={() => {
                if (!pending) onClose();
            }}
            data-testid="organization-create-dialog"
        >
            <form noValidate onSubmit={(event) => void submit(event)} data-testid="organization-create-form">
                <DialogTitle id={TITLE_ID}>組織を作成</DialogTitle>
                <DialogContent>
                    <Stack spacing={2}>
                        <DialogContentText id={DESCRIPTION_ID}>組織名は、有効な組織の中で一意にしてください (大文字小文字は区別しません)。メンバーは作成後に設定します。</DialogContentText>
                        {failure && <AppErrorAlert error={failure} test_id="organization-create-error" />}
                        <TextField
                            autoFocus
                            required
                            label="組織名"
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                            error={error !== undefined}
                            helperText={error}
                            inputRef={input_ref}
                            slotProps={{ htmlInput: { 'data-testid': 'organization-create-name', autoComplete: 'off' } }}
                        />
                    </Stack>
                </DialogContent>
                <DialogActions>
                    <Button onClick={onClose} disabled={pending} data-testid="organization-create-cancel">キャンセル</Button>
                    <Button
                        type="submit"
                        variant="contained"
                        disabled={pending}
                        startIcon={pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                        data-testid="organization-create-submit"
                    >
                        {pending ? '作成中…' : '作成する'}
                    </Button>
                </DialogActions>
            </form>
        </Dialog>
    );
};

export default OrganizationCreateDialog;
