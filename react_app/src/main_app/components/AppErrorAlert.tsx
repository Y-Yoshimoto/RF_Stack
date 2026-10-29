/**
 * @desc AP の API エラーの通知 (role="alert" で読み上げられる)
 * 文言は error_text.ts が決める。再読み込みが必要なエラー (412 など) では「再読み込み」を、取得の失敗などでは「再試行」を出す。
 */
import type { ReactNode } from 'react';
import { Alert, AlertTitle, Box, Button, Typography } from '@mui/material';
import type { AppErrorInfo } from '@/main_app/api/errors';
import { appErrorTextOf } from './error_text';

export type AppErrorAlertProps = {
    error: AppErrorInfo;
    /** data-testid。 */
    test_id: string;
    /** 再読み込み (または再試行) の操作。指定すると、requires_reload のとき (または always_retry のとき) ボタンを出す。 */
    onReload?: () => void;
    /** requires_reload でなくても再試行のボタンを出す (取得の失敗など)。 */
    always_retry?: boolean;
    /** 追加の操作や補足。 */
    children?: ReactNode;
};

export const AppErrorAlert = ({ error, test_id, onReload, always_retry = false, children }: AppErrorAlertProps) => {
    const text = appErrorTextOf(error);
    const show_reload = onReload !== undefined && (error.requires_reload || always_retry);
    const request_id = error.problem?.request_id;
    return (
        <Alert
            severity="error"
            role="alert"
            data-testid={test_id}
            data-error-kind={error.kind}
            data-error-code={error.code ?? ''}
            action={show_reload ? <Button color="inherit" size="small" onClick={onReload} data-testid={`${test_id}-reload`}>{error.requires_reload ? '再読み込み' : '再試行'}</Button> : undefined}
        >
            <AlertTitle>{text.title}</AlertTitle>
            {text.message}
            {text.details.length > 0 && (
                <Box component="ul" sx={{ mt: 0.5, mb: 0, pl: 2.5 }} data-testid={`${test_id}-details`}>
                    {text.details.map((line) => <li key={line}>{line}</li>)}
                </Box>
            )}
            {request_id && <Typography variant="caption" component="p" sx={{ mt: 0.5 }}>リクエスト ID: {request_id}</Typography>}
            {children}
        </Alert>
    );
};

export default AppErrorAlert;
