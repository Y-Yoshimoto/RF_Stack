/**
 * @desc ユーザーの有効/無効の切り替え (tenant_admin のみ)
 * 無効化は確認ダイアログを挟む。自分自身は無効化できないため、ボタンを無効にして理由を表示する (API を呼ばない)。
 */
import { useState } from 'react';
import { Box, Button, Paper, Typography } from '@mui/material';
import type { UserDetail } from '@/main_app/api/contract';
import { selfModificationOf } from '@/main_app/api/users';
import { ConfirmDialog } from '@/main_app/components/ConfirmDialog';

const SELF_DEACTIVATE_ID = 'user-status-self-reason';

export type UserStatusPanelProps = {
    user: UserDetail;
    self_user_id: string | null;
    /** 有効/無効を切り替える (成功したら true)。 */
    onChange: (is_active: boolean) => Promise<boolean>;
    pending: boolean;
};

export const UserStatusPanel = ({ user, self_user_id, onChange, pending }: UserStatusPanelProps) => {
    const [is_confirming, setIsConfirming] = useState(false);
    const is_self_blocked = selfModificationOf(user.id, self_user_id, { is_active: false }) === 'deactivate';

    const deactivate = async () => {
        await onChange(false);
        setIsConfirming(false);
    };

    return (
        <Paper variant="outlined" component="section" aria-labelledby="user-status-heading" sx={{ p: 2 }} data-testid="user-status-panel">
            <Typography id="user-status-heading" variant="h6" component="h2" gutterBottom>有効 / 無効</Typography>
            {user.is_active ? (
                <>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                        無効にすると、このユーザーはログインできなくなり、ログイン中のセッションも次回のリクエスト時に失効します。後から再度有効にできます。
                    </Typography>
                    <Button
                        variant="outlined"
                        color="error"
                        disabled={is_self_blocked || pending}
                        onClick={() => setIsConfirming(true)}
                        aria-describedby={is_self_blocked ? SELF_DEACTIVATE_ID : undefined}
                        data-testid="user-deactivate"
                    >
                        無効にする
                    </Button>
                    {is_self_blocked && (
                        <Typography id={SELF_DEACTIVATE_ID} variant="body2" color="text.secondary" sx={{ mt: 1 }} data-testid="user-deactivate-self-reason">
                            自分自身は無効にできません。別のテナント管理者に依頼してください。
                        </Typography>
                    )}
                </>
            ) : (
                <>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>このユーザーは無効です。再度有効にすると、ログインできるようになります。</Typography>
                    <Box>
                        <Button variant="outlined" disabled={pending} onClick={() => void onChange(true)} data-testid="user-reactivate">有効にする</Button>
                    </Box>
                </>
            )}
            <ConfirmDialog
                open={is_confirming}
                title="ユーザーを無効にしますか？"
                description={`${user.display_name} はログインできなくなり、ログイン中のセッションは次回のリクエスト時に失効します。`}
                confirm_label="無効にする"
                confirm_color="error"
                pending={pending}
                onConfirm={() => void deactivate()}
                onCancel={() => setIsConfirming(false)}
                test_id="user-deactivate-dialog"
            />
        </Paper>
    );
};

export default UserStatusPanel;
