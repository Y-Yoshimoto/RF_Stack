/**
 * @desc テナント一覧の表 (見出しのボタンで並べ替え、行を押すと詳細へ)
 * 表の見出しは th scope="col"、並べ替え中の列は aria-sort で伝える。行の移動はテナントコードのリンクでもできる (キーボード)。
 */
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { Box, Link, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TableSortLabel, Typography } from '@mui/material';
import type { TenantListItem, TenantSortKey } from '@/control_plane_app/api/contract';
import { TenantStatusChip } from '@/control_plane_app/components/TenantStatusChip';
import { formatDateTime, formatMetricValue, metricLabelOf } from '@/control_plane_app/components/tenant_labels';
import { cpTenantPathOf } from '@/control_plane_app/paths';
import { nextTenantSort, sortColumnOf, type SortableColumn } from './list_params';

export type TenantTableProps = {
    items: readonly TenantListItem[];
    sort: TenantSortKey;
    onSortChange: (sort: TenantSortKey) => void;
};

/** 並べ替えできる列の見出し */
const SortableHead = ({ column, label, sort, onSortChange }: { column: SortableColumn; label: string; sort: TenantSortKey; onSortChange: (sort: TenantSortKey) => void }) => {
    const current = sortColumnOf(sort);
    const is_active = current.column === column;
    return (
        <TableCell scope="col" sortDirection={is_active ? current.direction : false}>
            <TableSortLabel active={is_active} direction={is_active ? current.direction : 'asc'} onClick={() => onSortChange(nextTenantSort(sort, column))} data-testid={`tenant-sort-${column}`}>
                {label}
            </TableSortLabel>
        </TableCell>
    );
};

/**
 * ユーザー数の表示を作る関数
 * @param {TenantListItem} item 一覧の要素
 * @returns {string} 「有効 / 総数」。集計前は「—」
*/
export const usersTextOf = (item: TenantListItem): string => {
    if (item.users_total === null || item.users_total === undefined) return '—';
    return `${item.users_active ?? '—'} / ${item.users_total}`;
};

const TenantRowView = ({ item }: { item: TenantListItem }) => {
    const navigate = useNavigate();
    const to = cpTenantPathOf(item.id);
    return (
        <TableRow hover onClick={() => void navigate(to)} sx={{ cursor: 'pointer' }} data-testid={`tenant-row-${item.tenant_code}`}>
            <TableCell component="th" scope="row">
                <Link component={RouterLink} to={to} onClick={(event) => event.stopPropagation()} underline="hover" data-testid={`tenant-link-${item.tenant_code}`}>{item.tenant_code}</Link>
            </TableCell>
            <TableCell>{item.name}</TableCell>
            <TableCell><TenantStatusChip status={item.status} test_id={`tenant-status-${item.tenant_code}`} /></TableCell>
            <TableCell align="right" data-testid={`tenant-users-${item.tenant_code}`}>{usersTextOf(item)}</TableCell>
            <TableCell data-testid={`tenant-metrics-${item.tenant_code}`}>
                {item.primary_metrics.length === 0 ? '—' : item.primary_metrics.map((metric) => (
                    <Typography key={metric.metric_key} variant="body2" component="span" sx={{ display: 'block' }}>
                        {metricLabelOf(metric.metric_key)}: {formatMetricValue(metric.value)}
                    </Typography>
                ))}
            </TableCell>
            <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatDateTime(item.created_at)}</TableCell>
        </TableRow>
    );
};

export const TenantTable = ({ items, sort, onSortChange }: TenantTableProps) => (
    <TableContainer component={Box} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: 'background.paper' }}>
        <Table size="small" aria-label="テナント一覧" data-testid="tenant-table">
            <TableHead>
                <TableRow>
                    <SortableHead column="tenant_code" label="テナントコード" sort={sort} onSortChange={onSortChange} />
                    <SortableHead column="name" label="名前" sort={sort} onSortChange={onSortChange} />
                    <TableCell scope="col">状態</TableCell>
                    <TableCell scope="col" align="right">ユーザー数 (有効 / 総数)</TableCell>
                    <TableCell scope="col">主要指標</TableCell>
                    <SortableHead column="created_at" label="作成日時" sort={sort} onSortChange={onSortChange} />
                </TableRow>
            </TableHead>
            <TableBody>
                {items.map((item) => <TenantRowView key={item.id} item={item} />)}
            </TableBody>
        </Table>
    </TableContainer>
);

export default TenantTable;
