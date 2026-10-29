/**
 * @desc 組織一覧 (`/{tenant_code}/organizations`)
 * 組織名の一覧と「さらに読み込む」。tenant_admin には作成・削除 (確認ダイアログ) を出し、member は閲覧のみ。
 * 組織の名前変更・メンバーの設定は詳細画面で行う。
 * 使うフック: useOrganizationList (一覧)、useOrganizationActions (作成・削除)、useAppPermissions (権限)。
 */
import { useState } from 'react';
import { Alert, Button, Stack } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { ifMatchOf } from '@/main_app/api/contract';
import type { OrganizationRead } from '@/main_app/api/contract';
import { useAppPermissions, useAppSession } from '@/main_app/auth/useAppAuth';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import { ConfirmDialog } from '@/main_app/components/ConfirmDialog';
import { PageHeader } from '@/main_app/components/PageHeader';
import { useOrganizationActions } from '@/main_app/organizations/useOrganizationActions';
import { useOrganizationList } from '@/main_app/organizations/useOrganizationList';
import { OrganizationCreateDialog } from './OrganizationCreateDialog';
import { OrganizationListView } from './OrganizationListView';

export const AppOrganizationListPage = () => {
    const { tenant_code } = useAppSession();
    const { can_write } = useAppPermissions();
    const list = useOrganizationList();
    const actions = useOrganizationActions({
        onUpdated: (update) => {
            if (update.action === 'create') list.reload();
            else if (update.action === 'update') list.replaceItem(update.organization);
            else if (update.action === 'delete') list.removeItem(update.organization_id);
        },
    });
    const [is_creating, setIsCreating] = useState(false);
    const [delete_target, setDeleteTarget] = useState<OrganizationRead | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const openCreate = () => {
        actions.clearFailure();
        setNotice(null);
        setIsCreating(true);
    };

    const create = async (name: string): Promise<boolean> => {
        const result = await actions.create({ name });
        if (result.ok) {
            setIsCreating(false);
            setNotice(`組織「${name}」を作成しました。`);
        }
        return result.ok;
    };

    const remove = async () => {
        if (delete_target === null) return;
        setNotice(null);
        const result = await actions.remove({ organization_id: delete_target.id, etag: ifMatchOf(delete_target.version) });
        if (result.ok) setNotice(`組織「${delete_target.name}」を削除しました。`);
        setDeleteTarget(null);
    };

    // 作成の失敗はダイアログの中に出す。それ以外 (削除) の失敗は画面に出す
    const page_failure = actions.failure !== null && actions.failure.action !== 'create' ? actions.failure : null;
    const create_failure = actions.failure !== null && actions.failure.action === 'create' ? actions.failure : null;

    return (
        <Stack spacing={3} data-testid="app-organization-list-page" data-can-write={can_write}>
            <PageHeader
                test_id="organization-list"
                title="組織管理"
                description="テナントの組織の一覧です。"
                actions={can_write ? <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate} data-testid="organization-list-create">組織を作成</Button> : undefined}
            />
            {!can_write && <Alert severity="info" data-testid="organization-list-readonly">閲覧のみ可能です。組織の作成・変更はテナント管理者が行います。</Alert>}
            {notice && <Alert severity="success" role="status" onClose={() => setNotice(null)} data-testid="organization-list-notice">{notice}</Alert>}
            {page_failure && <AppErrorAlert error={page_failure} test_id="organization-list-action-error" onReload={() => { actions.clearFailure(); list.reload(); }} />}

            <OrganizationListView
                list={list}
                tenant_code={tenant_code}
                can_write={can_write}
                pending={actions.pending !== null}
                onDelete={(organization) => {
                    actions.clearFailure();
                    setDeleteTarget(organization);
                }}
            />

            {is_creating && <OrganizationCreateDialog failure={create_failure} pending={actions.pending === 'create'} onSubmit={create} onClose={() => setIsCreating(false)} />}
            <ConfirmDialog
                open={delete_target !== null}
                title="組織を削除しますか？"
                description={`組織「${delete_target?.name ?? ''}」を削除します。組織は一覧から消え、画面からは元に戻せません。メンバーだったユーザー自体は削除されません。`}
                confirm_label="削除する"
                confirm_color="error"
                pending={actions.pending === 'delete'}
                onConfirm={() => void remove()}
                onCancel={() => setDeleteTarget(null)}
                test_id="organization-delete-dialog"
            />
        </Stack>
    );
};

export default AppOrganizationListPage;
