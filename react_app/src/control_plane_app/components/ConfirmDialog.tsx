/**
 * @desc 変更操作の確認ダイアログ (停止・再開・削除要求など)
 * 初期フォーカスは安全側の「キャンセル」(確認の入力欄を children に渡した場合は、その入力欄)。実行中は閉じられず、二重実行もできない。
 */
import type { ReactNode } from 'react';
import { Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle } from '@mui/material';

export type ConfirmDialogProps = {
    open: boolean;
    title: string;
    /** 操作の説明 (影響を書く)。 */
    description: ReactNode;
    confirm_label: string;
    confirm_color?: 'primary' | 'error' | 'warning';
    /** 実行中 (ボタンを無効にして進行を示す)。 */
    pending?: boolean;
    /** 実行ボタンを無効にする (確認の入力が不足しているなど)。 */
    confirm_disabled?: boolean;
    onConfirm: () => void;
    onCancel: () => void;
    /** 確認の入力欄など。 */
    children?: ReactNode;
    /** data-testid の接頭辞。 */
    test_id: string;
};

export const ConfirmDialog = ({ open, title, description, confirm_label, confirm_color = 'primary', pending = false, confirm_disabled = false, onConfirm, onCancel, children, test_id }: ConfirmDialogProps) => {
    const title_id = `${test_id}-title`;
    const description_id = `${test_id}-description`;
    return (
        <Dialog
            open={open}
            maxWidth="sm"
            fullWidth
            aria-labelledby={title_id}
            aria-describedby={description_id}
            onClose={() => {
                if (!pending) onCancel();
            }}
            data-testid={test_id}
        >
            <DialogTitle id={title_id}>{title}</DialogTitle>
            <DialogContent>
                <DialogContentText id={description_id} component="div" sx={{ mb: children ? 2 : 0 }}>{description}</DialogContentText>
                {children}
            </DialogContent>
            <DialogActions>
                <Button autoFocus={!children} onClick={onCancel} disabled={pending} data-testid={`${test_id}-cancel`}>キャンセル</Button>
                <Button
                    variant="contained"
                    color={confirm_color}
                    onClick={onConfirm}
                    disabled={pending || confirm_disabled}
                    startIcon={pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                    data-testid={`${test_id}-confirm`}
                >
                    {pending ? '実行中…' : confirm_label}
                </Button>
            </DialogActions>
        </Dialog>
    );
};

export default ConfirmDialog;
