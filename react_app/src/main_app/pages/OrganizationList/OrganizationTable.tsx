/**
 * @desc 組織一覧の表 (組織名・作成日時・更新日時、tenant_admin には削除ボタン)
 * 一覧 API の応答にメンバーは含まれない (詳細で表示する)。
 */
import { Link as RouterLink } from 'react-router-dom';
import { Button, Link, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow } from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import type { OrganizationRead } from '@/main_app/api/contract';
import { formatDateTime } from '@/main_app/components/format';
import { appOrganizationPath } from '@/main_app/paths';

export type OrganizationTableProps = {
    tenant_code: string;
    organizations: OrganizationRead[];
    /** 変更操作 (削除) を出す。member は false。 */
    can_write: boolean;
    /** 削除ボタンを押した。 */
    onDelete: (organization: OrganizationRead) => void;
    /** 操作中 (削除ボタンを無効にする)。 */
    pending: boolean;
};

export const OrganizationTable = ({ tenant_code, organizations, can_write, onDelete, pending }: OrganizationTableProps) => (
    <TableContainer component={Paper} variant="outlined">
        <Table size="small" aria-label="組織一覧" data-testid="organization-table">
            <TableHead>
                <TableRow>
                    <TableCell>組織名</TableCell>
                    <TableCell>作成日時</TableCell>
                    <TableCell>更新日時</TableCell>
                    {can_write && <TableCell align="right">操作</TableCell>}
                </TableRow>
            </TableHead>
            <TableBody>
                {organizations.map((organization) => (
                    <TableRow key={organization.id} hover data-testid={`organization-row-${organization.id}`}>
                        <TableCell component="th" scope="row" sx={{ overflowWrap: 'anywhere' }}>
                            <Link component={RouterLink} to={appOrganizationPath(tenant_code, organization.id)} underline="hover" data-testid={`organization-link-${organization.id}`}>{organization.name}</Link>
                        </TableCell>
                        <TableCell>{formatDateTime(organization.created_at)}</TableCell>
                        <TableCell>{formatDateTime(organization.updated_at)}</TableCell>
                        {can_write && (
                            <TableCell align="right">
                                <Button
                                    size="small"
                                    color="error"
                                    startIcon={<DeleteIcon />}
                                    disabled={pending}
                                    onClick={() => onDelete(organization)}
                                    aria-label={`${organization.name} を削除`}
                                    data-testid={`organization-delete-${organization.id}`}
                                >
                                    削除
                                </Button>
                            </TableCell>
                        )}
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    </TableContainer>
);

export default OrganizationTable;
