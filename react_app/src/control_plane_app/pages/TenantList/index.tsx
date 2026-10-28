/**
 * @desc CP のテナント一覧 (`/cp/tenants`。CP-OPS-01)
 * 状態の絞り込みと並べ替えは URL のクエリに持つ。取得は useTenantList (カーソル方式の「さらに読み込む」)。
 * テナント作成への導線は変更権限 (saas_admin) があるときだけ出す (01 §11.2)。
 */
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
import { Box, Button, MenuItem, Stack, TextField, Typography } from '@mui/material';
import AddBusinessIcon from '@mui/icons-material/AddBusiness';
import type { TenantSortKey, TenantStatus } from '@/control_plane_app/api/contract';
import { useCpPermissions } from '@/control_plane_app/auth/useCpAuth';
import { CpErrorAlert } from '@/control_plane_app/components/CpErrorAlert';
import { TENANT_STATUS_LABEL, TENANT_STATUSES } from '@/control_plane_app/components/tenant_labels';
import { CP_TENANT_CREATE_PATH } from '@/control_plane_app/paths';
import { useTenantList, type TenantListState } from '@/control_plane_app/tenants/useTenantList';
import { PageLoading } from '@/shared/components/PageLoading';
import { buildTenantListSearch, parseTenantListParams } from './list_params';
import { TenantTable } from './TenantTable';

/** 1 回に読み込む件数 */
export const TENANT_LIST_PAGE_SIZE = 20;

type ListBodyProps = {
    list: TenantListState;
    sort: TenantSortKey;
    onSortChange: (sort: TenantSortKey) => void;
    is_filtered: boolean;
};

/** 一覧の本体 (読み込み中・エラー・空・表) */
const ListBody = ({ list, sort, onSortChange, is_filtered }: ListBodyProps) => {
    const { can_write } = useCpPermissions();
    if (list.status === 'loading') return <PageLoading />;
    if (list.status === 'error' && list.error) return <CpErrorAlert error={list.error} test_id="tenant-list-error" onReload={list.reload} always_retry />;
    if (list.items.length === 0) {
        return (
            <Stack spacing={2} sx={{ alignItems: 'center', py: 6, border: 1, borderColor: 'divider', borderRadius: 1, bgcolor: 'background.paper' }} data-testid="tenant-list-empty">
                <Typography variant="body1">{is_filtered ? '条件に一致するテナントはありません。' : 'テナントはまだありません。'}</Typography>
                {can_write && !is_filtered && (
                    <Button component={RouterLink} to={CP_TENANT_CREATE_PATH} variant="contained" startIcon={<AddBusinessIcon />} data-testid="tenant-list-empty-create">最初のテナントを作成</Button>
                )}
            </Stack>
        );
    }
    const load_more_error = list.load_more_error;
    return (
        <Stack spacing={2}>
            <TenantTable items={list.items} sort={sort} onSortChange={onSortChange} />
            {load_more_error && (
                <CpErrorAlert error={load_more_error} test_id="tenant-list-load-more-error" onReload={load_more_error.requires_reload ? list.reload : list.loadMore} always_retry />
            )}
            {list.has_more && (
                <Box sx={{ textAlign: 'center' }}>
                    <Button variant="outlined" onClick={list.loadMore} disabled={list.is_loading_more} data-testid="tenant-list-load-more">
                        {list.is_loading_more ? '読み込み中…' : 'さらに読み込む'}
                    </Button>
                </Box>
            )}
        </Stack>
    );
};

export const CpTenantListPage = () => {
    const { can_write } = useCpPermissions();
    const [search, setSearch] = useSearchParams();
    const params = parseTenantListParams(search);
    const list = useTenantList({ status: params.status ? [params.status] : [], sort: params.sort, include_total: true, limit: TENANT_LIST_PAGE_SIZE });

    const update = (next: { status?: TenantStatus | null; sort?: TenantSortKey }) => {
        setSearch(buildTenantListSearch({ status: next.status === undefined ? params.status : next.status, sort: next.sort ?? params.sort }), { replace: true });
    };

    const count_text = list.status === 'success'
        ? `${list.total !== null ? `全 ${list.total} 件のうち ` : ''}${list.items.length} 件を表示しています。`
        : '';
    return (
        <Stack spacing={3} data-testid="cp-tenant-list-page" data-can-write={can_write}>
            <Stack direction="row" spacing={2} sx={{ alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', rowGap: 1 }}>
                <Box>
                    <Typography variant="h4" component="h1" gutterBottom>テナント一覧</Typography>
                    <Typography variant="body1" color="text.secondary">払い出し済みのテナントの状態・ユーザー数・主要指標です。行を選ぶと詳細を表示します。</Typography>
                </Box>
                {can_write && (
                    <Button component={RouterLink} to={CP_TENANT_CREATE_PATH} variant="contained" startIcon={<AddBusinessIcon />} data-testid="tenant-list-create">テナントを作成</Button>
                )}
            </Stack>

            <Stack direction="row" spacing={2} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
                <TextField
                    select
                    size="small"
                    label="状態で絞り込み"
                    value={params.status ?? ''}
                    onChange={(event) => update({ status: (event.target.value || null) as TenantStatus | null })}
                    sx={{ minWidth: 220 }}
                    data-testid="tenant-list-status-filter"
                    slotProps={{ select: { displayEmpty: true }, inputLabel: { shrink: true } }}
                >
                    <MenuItem value="" data-testid="tenant-list-status-option-all">すべて (削除済みを含む)</MenuItem>
                    {TENANT_STATUSES.map((status) => (
                        <MenuItem key={status} value={status} data-testid={`tenant-list-status-option-${status}`}>{TENANT_STATUS_LABEL[status]}</MenuItem>
                    ))}
                </TextField>
                <Typography variant="body2" color="text.secondary" role="status" data-testid="tenant-list-count">{count_text}</Typography>
            </Stack>

            <Box component="section" aria-label="テナントの一覧" aria-busy={list.status === 'loading'}>
                <ListBody list={list} sort={params.sort} onSortChange={(sort) => update({ sort })} is_filtered={params.status !== null} />
            </Box>
        </Stack>
    );
};

export default CpTenantListPage;
