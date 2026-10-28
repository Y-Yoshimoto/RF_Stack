/**
 * @desc 組織の詳細・編集 (`/{tenant_code}/organizations/:organizationId`)
 * 組織名とメンバーを表示する。tenant_admin には名前の変更・メンバーの設定 (複数選択)・削除 (確認ダイアログ) を出し、member は閲覧のみ。
 * 412 / 428 (他の操作で更新済み) は再読み込みを促す。
 * 使うフック: useOrganization (詳細・ETag)、useAllUsers (メンバーの名前。全ユーザーの取得)、useOrganizationActions (変更。OrganizationDetailContent)、useAppPermissions (権限)。
 */
import { useParams } from 'react-router-dom';
import { Stack } from '@mui/material';
import { useAppPermissions, useAppSession } from '@/main_app/auth/useAppAuth';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import { PageHeader } from '@/main_app/components/PageHeader';
import { useOrganization } from '@/main_app/organizations/useOrganization';
import { appOrganizationsPath } from '@/main_app/paths';
import { PageLoading } from '@/shared/components/PageLoading';
import { OrganizationDetailContent } from './OrganizationDetailContent';
import { useAllUsers } from './useAllUsers';

export const AppOrganizationDetailPage = () => {
    const { organizationId = '' } = useParams();
    const { tenant_code } = useAppSession();
    const { can_write } = useAppPermissions();
    const detail = useOrganization(organizationId);
    const users = useAllUsers();

    const organization = detail.organization;
    const is_loading = detail.status === 'loading' || (detail.status === 'success' && users.status === 'loading');
    return (
        <Stack spacing={3} data-testid="app-organization-detail-page" data-can-write={can_write}>
            <PageHeader test_id="organization-detail" title={organization?.name ?? '組織詳細'} back={{ to: appOrganizationsPath(tenant_code), label: '組織管理へ戻る' }} />

            {is_loading && <PageLoading />}
            {detail.status === 'error' && detail.error && <AppErrorAlert error={detail.error} test_id="organization-detail-error" onReload={detail.reload} always_retry />}
            {/* メンバーの名前を表示するため、ユーザーの一覧を全件取得している */}
            {detail.status === 'success' && users.status === 'error' && users.error && <AppErrorAlert error={users.error} test_id="organization-users-error" onReload={users.reload} always_retry />}
            {!is_loading && organization !== null && users.status === 'success' && (
                <OrganizationDetailContent organization={organization} etag={detail.etag} users={users.users} onUpdated={detail.applyUpdate} onReload={detail.reload} />
            )}
        </Stack>
    );
};

export default AppOrganizationDetailPage;
