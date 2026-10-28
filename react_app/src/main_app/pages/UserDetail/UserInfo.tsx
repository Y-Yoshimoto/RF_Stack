/**
 * @desc ユーザーの基本情報 (読み取り専用の定義リスト)
 */
import { Box, Chip, Paper, Typography } from '@mui/material';
import type { UserDetail } from '@/main_app/api/contract';
import { formatDateTime } from '@/main_app/components/format';
import { RoleChips } from '@/main_app/components/RoleChips';

export type UserInfoProps = {
    user: UserDetail;
};

export const UserInfo = ({ user }: UserInfoProps) => (
    <Paper variant="outlined" component="section" aria-labelledby="user-info-heading" sx={{ p: 2 }} data-testid="user-info">
        <Typography id="user-info-heading" variant="h6" component="h2" gutterBottom>基本情報</Typography>
        <Box component="dl" sx={{ m: 0, display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: 3, rowGap: 1.5, alignItems: 'baseline' }}>
            <Typography component="dt" variant="body2" color="text.secondary">表示名</Typography>
            <Typography component="dd" variant="body1" sx={{ m: 0, overflowWrap: 'anywhere' }} data-testid="user-info-display-name">{user.display_name}</Typography>
            <Typography component="dt" variant="body2" color="text.secondary">メールアドレス</Typography>
            <Typography component="dd" variant="body1" sx={{ m: 0, overflowWrap: 'anywhere' }} data-testid="user-info-email">{user.email ?? '—'}</Typography>
            <Typography component="dt" variant="body2" color="text.secondary">ロール</Typography>
            <Box component="dd" sx={{ m: 0 }}><RoleChips roles={user.roles} test_id="user-info-roles" /></Box>
            <Typography component="dt" variant="body2" color="text.secondary">状態</Typography>
            <Box component="dd" sx={{ m: 0 }} data-testid="user-info-status">
                {user.is_active ? <Chip size="small" color="success" variant="outlined" label="有効" /> : <Chip size="small" variant="outlined" label="無効 (ログインできません)" />}
            </Box>
            <Typography component="dt" variant="body2" color="text.secondary">最終ログイン</Typography>
            <Typography component="dd" variant="body1" sx={{ m: 0 }} data-testid="user-info-last-login">{formatDateTime(user.last_login_at, '未ログイン')}</Typography>
            <Typography component="dt" variant="body2" color="text.secondary">作成日時</Typography>
            <Typography component="dd" variant="body1" sx={{ m: 0 }} data-testid="user-info-created-at">{formatDateTime(user.created_at)}</Typography>
        </Box>
    </Paper>
);

export default UserInfo;
