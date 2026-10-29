/**
 * @desc ユーザー作成で発行された一時パスワードを、一度だけ表示するダイアログ
 * 一時パスワードはこのダイアログだけに出す (フックの issued_credentials)。閉じると破棄され、再表示できない。
 * 背景のクリックでは閉じない (誤って閉じて失わないため)。Esc・「閉じる」で閉じる。初期フォーカスは警告文 (読み上げ) ではなく「コピー」ボタン。
 */
import { useState } from 'react';
import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import type { IssuedUserCredentials } from '@/main_app/users/useUserActions';

export type CredentialsDialogProps = {
    /** 発行されたログイン情報。null のとき (未発行・破棄後) は何も表示しない。 */
    credentials: IssuedUserCredentials | null;
    /** 閉じる。呼び出し側で dismissCredentials を呼ぶこと。 */
    onClose: () => void;
};

type CopyState = 'idle' | 'copied' | 'failed';

const COPY_MESSAGE: Record<CopyState, string> = {
    idle: '',
    copied: '一時パスワードをクリップボードにコピーしました。',
    failed: 'コピーできませんでした。一時パスワードを選択して、手動でコピーしてください。',
};

const TITLE_ID = 'app-credentials-title';
const DESCRIPTION_ID = 'app-credentials-description';

export const CredentialsDialog = ({ credentials, onClose }: CredentialsDialogProps) => {
    const [copy_state, setCopyState] = useState<CopyState>('idle');
    if (credentials === null) return null;

    const copyPassword = async () => {
        try {
            await navigator.clipboard.writeText(credentials.temporary_password);
            setCopyState('copied');
        } catch {
            setCopyState('failed');
        }
    };

    return (
        <Dialog
            open
            maxWidth="sm"
            fullWidth
            aria-labelledby={TITLE_ID}
            aria-describedby={DESCRIPTION_ID}
            onClose={(_event, reason) => {
                if (reason !== 'backdropClick') onClose();
            }}
            data-testid="credentials-dialog"
        >
            <DialogTitle id={TITLE_ID}>一時パスワード</DialogTitle>
            <DialogContent>
                <Stack spacing={2}>
                    <Alert severity="warning" role="note" id={DESCRIPTION_ID} data-testid="credentials-dialog-warning">
                        この一時パスワードは今回だけ表示されます。ダイアログを閉じると消え、再表示できません。閉じる前にコピーして、安全な方法で本人に伝えてください。本人は初回ログイン時にパスワードの変更を求められます。
                    </Alert>
                    <Box component="dl" sx={{ m: 0, display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: 2, rowGap: 1, alignItems: 'baseline' }}>
                        <Typography component="dt" variant="body2" color="text.secondary">表示名</Typography>
                        <Typography component="dd" variant="body1" sx={{ m: 0, overflowWrap: 'anywhere' }} data-testid="credentials-dialog-display-name">{credentials.display_name}</Typography>
                        <Typography component="dt" variant="body2" color="text.secondary">ユーザー名</Typography>
                        <Typography component="dd" variant="body1" sx={{ m: 0, overflowWrap: 'anywhere' }} data-testid="credentials-dialog-username">{credentials.username}</Typography>
                        <Typography component="dt" variant="body2" color="text.secondary">一時パスワード</Typography>
                        <Typography
                            component="dd"
                            variant="body1"
                            sx={{ m: 0, fontFamily: 'monospace', fontSize: '1.1rem', overflowWrap: 'anywhere', userSelect: 'all' }}
                            data-testid="credentials-dialog-password"
                        >
                            {credentials.temporary_password}
                        </Typography>
                    </Box>
                    <Box>
                        <Button variant="outlined" autoFocus startIcon={<ContentCopyIcon />} onClick={() => void copyPassword()} data-testid="credentials-dialog-copy">
                            一時パスワードをコピー
                        </Button>
                    </Box>
                    {/* コピーの結果を読み上げる (常に DOM に置き、内容だけ変える) */}
                    <Typography role="status" variant="body2" color={copy_state === 'failed' ? 'error' : 'text.secondary'} data-testid="credentials-dialog-copy-status">
                        {COPY_MESSAGE[copy_state]}
                    </Typography>
                </Stack>
            </DialogContent>
            <DialogActions>
                <Button variant="contained" onClick={onClose} data-testid="credentials-dialog-close">閉じる (パスワードは消えます)</Button>
            </DialogActions>
        </Dialog>
    );
};

export default CredentialsDialog;
