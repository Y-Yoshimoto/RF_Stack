/**
 * @desc ユーザー一覧 (`/{tenant_code}/users`)
 * 表示名・メールアドレス・状態・最終ログインの一覧。有効/無効の絞り込みと「さらに読み込む」。
 * tenant_admin には作成の導線を出し、member は閲覧のみ (変更の UI を出さない)。
 * 使うフック: useUserList (一覧)、useAppPermissions (権限)。
 */
import { Link as RouterLink, useSearchParams } from 'react-router-dom';
import { Alert, Box, Button, MenuItem, Stack, TextField, Typography } from '@mui/material';
import PersonAddIcon from '@mui/icons-material/PersonAdd';
import type { UserListFilter } from '@/main_app/api/users';
import { useAppPermissions, useAppSession } from '@/main_app/auth/useAppAuth';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import { ListFooter } from '@/main_app/components/ListFooter';
import { PageHeader } from '@/main_app/components/PageHeader';
import { appUserCreatePath } from '@/main_app/paths';
import { useUserList } from '@/main_app/users/useUserList';
import { PageLoading } from '@/shared/components/PageLoading';
import { UserTable } from './UserTable';

/** 状態の絞り込み (URL の `?status=`)。省略時はすべて */
const STATUS_FILTERS = {
    all: { label: 'すべて', filter: {} },
    active: { label: '有効', filter: { is_active: true } },
    inactive: { label: '無効', filter: { is_active: false } },
} as const satisfies Record<string, { label: string; filter: UserListFilter }>;
type StatusFilterKey = keyof typeof STATUS_FILTERS;

const isStatusFilterKey = (value: string | null): value is StatusFilterKey => value !== null && Object.hasOwn(STATUS_FILTERS, value);

export const AppUserListPage = () => {
    const { tenant_code } = useAppSession();
    const { can_write } = useAppPermissions();
    const [search_params, setSearchParams] = useSearchParams();
    const status_param = search_params.get('status');
    const status_key: StatusFilterKey = isStatusFilterKey(status_param) ? status_param : 'all';
    const list = useUserList(STATUS_FILTERS[status_key].filter);

    const changeStatus = (next: string) => {
        setSearchParams(next === 'all' ? {} : { status: next }, { replace: true });
    };

    return (
        <Stack spacing={3} data-testid="app-user-list-page" data-can-write={can_write}>
            <PageHeader
                test_id="user-list"
                title="ユーザー管理"
                description="テナントのユーザーの一覧です。"
                actions={can_write ? (
                    <Button component={RouterLink} to={appUserCreatePath(tenant_code)} variant="contained" startIcon={<PersonAddIcon />} data-testid="user-list-create">ユーザーを作成</Button>
                ) : undefined}
            />
            {!can_write && <Alert severity="info" data-testid="user-list-readonly">閲覧のみ可能です。ユーザーの作成・変更はテナント管理者が行います。</Alert>}

            <TextField
                select
                size="small"
                label="状態"
                value={status_key}
                onChange={(event) => changeStatus(event.target.value)}
                sx={{ width: 200 }}
                data-testid="user-filter-status"
            >
                {Object.entries(STATUS_FILTERS).map(([key, { label }]) => <MenuItem key={key} value={key} data-testid={`user-filter-status-${key}`}>{label}</MenuItem>)}
            </TextField>

            {list.status === 'loading' && <PageLoading />}
            {list.status === 'error' && list.error && <AppErrorAlert error={list.error} test_id="user-list-error" onReload={list.reload} always_retry />}
            {list.status === 'success' && (
                list.items.length === 0 ? (
                    <Box data-testid="user-list-empty" sx={{ py: 4, textAlign: 'center' }}>
                        <Typography variant="body1" color="text.secondary">
                            {status_key === 'all' ? 'ユーザーがいません。' : `${STATUS_FILTERS[status_key].label}のユーザーはいません。`}
                        </Typography>
                    </Box>
                ) : (
                    <>
                        <UserTable tenant_code={tenant_code} users={list.items} />
                        <ListFooter
                            test_id="user-list"
                            count={list.items.length}
                            unit="人"
                            has_more={list.has_more}
                            is_loading_more={list.is_loading_more}
                            load_more_error={list.load_more_error}
                            onLoadMore={list.loadMore}
                            onReload={list.reload}
                        />
                    </>
                )
            )}
        </Stack>
    );
};

export default AppUserListPage;
