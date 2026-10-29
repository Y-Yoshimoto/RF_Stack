/**
 * @desc ユーザー一覧の表 (表示名・メールアドレス・ロール・状態・最終ログイン)
 * ロールは AP の DB の写し (最後に同期した時点の値)。未同期のユーザーは roles が空のため「未同期」と文字で表示する。
 * 最新のロールは詳細で確認する。
 */
import { Link as RouterLink } from 'react-router-dom';
import { Chip, Link, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import type { UserRead } from '@/main_app/api/contract';
import { formatDateTime } from '@/main_app/components/format';
import { RoleChips } from '@/main_app/components/RoleChips';
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
                    <TableCell>ロール</TableCell>
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
                        <TableCell data-testid={`user-roles-cell-${user.id}`}>
                            {user.roles.length === 0
                                ? <Chip size="small" variant="outlined" label="未同期" data-testid={`user-roles-${user.id}`} />
                                : <RoleChips roles={user.roles} test_id={`user-roles-${user.id}`} />}
                        </TableCell>
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
