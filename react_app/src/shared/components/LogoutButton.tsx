/**
 * @desc ログアウトのボタン
 * onLogout は失敗すると reject する (遷移しない)。失敗はボタンの下ではなく画面下部の通知で表示し、閉じるまで残す
 * (role="alert" のためスクリーンリーダーが読み上げる)。成功時はブラウザが遷移するため、実行中はボタンを無効にして二重送信を防ぐ。
 * プレーン固有のロジックは持たない (ログアウト処理は呼び出し側が渡す)。
 */
import { useState, type ReactNode } from 'react';
import { Alert, Button, Snackbar, type ButtonProps } from '@mui/material';
import LogoutIcon from '@mui/icons-material/Logout';

export type LogoutButtonProps = {
    /** ログアウトを実行する。失敗時は reject する。 */
    onLogout: () => Promise<void>;
    /** ボタンの data-testid。失敗の通知は `${test_id}-error`。 */
    test_id?: string;
    /** ボタンの文言。 */
    label?: ReactNode;
    variant?: ButtonProps['variant'];
    color?: ButtonProps['color'];
    size?: ButtonProps['size'];
};

export const LogoutButton = ({ onLogout, test_id = 'logout-button', label = 'ログアウト', variant = 'outlined', color = 'inherit', size = 'medium' }: LogoutButtonProps) => {
    const [pending, setPending] = useState(false);
    const [failed, setFailed] = useState(false);
    const handleClick = () => {
        setPending(true);
        setFailed(false);
        onLogout()
            .catch(() => setFailed(true))
            .finally(() => setPending(false));
    };
    return (
        <>
            <Button type="button" variant={variant} color={color} size={size} startIcon={<LogoutIcon />} onClick={handleClick} disabled={pending} sx={{ whiteSpace: 'nowrap', flexShrink: 0 }} data-testid={test_id}>
                {label}
            </Button>
            <Snackbar open={failed} anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
                <Alert severity="error" variant="filled" onClose={() => setFailed(false)} data-testid={`${test_id}-error`}>
                    ログアウトに失敗しました。時間をおいてもう一度お試しください
                </Alert>
            </Snackbar>
        </>
    );
};

export default LogoutButton;
