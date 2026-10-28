/**
 * @desc ユーザー一覧の表 (表示名・メールアドレス・状態・最終ログイン)
 * 一覧 API の応答にロールは含まれない (ロールの取得は認証基盤への問い合わせが必要なため、詳細でのみ取得する)。
 */
import { Link as RouterLink } from 'react-router-dom';
import { Chip, Link, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import type { UserRead } from '@/main_app/api/contract';
import { formatDateTime } from '@/main_app/components/format';
import { appUserPath } from '@/main_app/paths';

export type UserTableProps = {
    tenant_code: string;
    users: UserRead[];
};

export const UserTable = ({ tenant_code, users }: UserTableProps) => (
    <TableContainer component={Paper} variant="outlined">
        <Table size="small" aria-label="ユーザー一覧" data-testid="user-table">
            <TableHead>
                <TableRow>
                    <TableCell>表示名</TableCell>
                    <TableCell>メールアドレス</TableCell>
                    <TableCell>状態</TableCell>
                    <TableCell>最終ログイン</TableCell>
                </TableRow>
            </TableHead>
            <TableBody>
                {users.map((user) => (
                    <TableRow key={user.id} hover data-testid={`user-row-${user.id}`} data-active={user.is_active}>
                        <TableCell component="th" scope="row" sx={{ overflowWrap: 'anywhere' }}>
                            <Link component={RouterLink} to={appUserPath(tenant_code, user.id)} underline="hover" data-testid={`user-link-${user.id}`}>{user.display_name}</Link>
                        </TableCell>
                        <TableCell sx={{ overflowWrap: 'anywhere' }} data-testid={`user-email-${user.id}`}>{user.email ?? '—'}</TableCell>
                        <TableCell data-testid={`user-status-${user.id}`}>
                            {user.is_active ? <Chip size="small" color="success" variant="outlined" label="有効" /> : <Chip size="small" variant="outlined" label="無効" />}
                        </TableCell>
                        <TableCell data-testid={`user-last-login-${user.id}`}>{formatDateTime(user.last_login_at, '未ログイン')}</TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    </TableContainer>
);

export default UserTable;
