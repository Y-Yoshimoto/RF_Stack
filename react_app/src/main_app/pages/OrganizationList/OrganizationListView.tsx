/**
 * @desc 組織一覧の本体 (読み込み中・エラー・空・表と「さらに読み込む」の出し分け)
 */
import { Box, Typography } from '@mui/material';
import type { OrganizationRead } from '@/main_app/api/contract';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import { ListFooter } from '@/main_app/components/ListFooter';
import type { OrganizationListState } from '@/main_app/organizations/useOrganizationList';
import { PageLoading } from '@/shared/components/PageLoading';
import { OrganizationTable } from './OrganizationTable';

export type OrganizationListViewProps = {
    list: OrganizationListState;
    tenant_code: string;
    can_write: boolean;
    /** 操作中 (削除ボタンを無効にする)。 */
    pending: boolean;
    onDelete: (organization: OrganizationRead) => void;
};

export const OrganizationListView = ({ list, tenant_code, can_write, pending, onDelete }: OrganizationListViewProps) => {
    if (list.status === 'loading') return <PageLoading />;
    if (list.status === 'error' && list.error) return <AppErrorAlert error={list.error} test_id="organization-list-error" onReload={list.reload} always_retry />;
    if (list.items.length === 0) {
        return (
            <Box data-testid="organization-list-empty" sx={{ py: 4, textAlign: 'center' }}>
                <Typography variant="body1" color="text.secondary">組織がありません。</Typography>
            </Box>
        );
    }
    return (
        <>
            <OrganizationTable tenant_code={tenant_code} organizations={list.items} can_write={can_write} pending={pending} onDelete={onDelete} />
            <ListFooter
                test_id="organization-list"
                count={list.items.length}
                unit="件"
                has_more={list.has_more}
                is_loading_more={list.is_loading_more}
                load_more_error={list.load_more_error}
                onLoadMore={list.loadMore}
                onReload={list.reload}
            />
        </>
    );
};

export default OrganizationListView;
