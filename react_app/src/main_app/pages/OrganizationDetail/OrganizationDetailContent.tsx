/**
 * @desc 組織詳細の本体 (詳細とユーザー一覧の取得後に表示する。組織名・メンバー・削除)
 * 変更の操作 (useOrganizationActions) と結果の通知はここで持つ。tenant_admin には変更を出し、member は閲覧のみ。
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Button, Paper, Typography } from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import type { OrganizationDetail, UserRead } from '@/main_app/api/contract';
import { useAppPermissions, useAppSession } from '@/main_app/auth/useAppAuth';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import { ConfirmDialog } from '@/main_app/components/ConfirmDialog';
import { useOrganizationActions } from '@/main_app/organizations/useOrganizationActions';
import type { OrganizationActionUpdate } from '@/main_app/organizations/useOrganization';
import { appOrganizationsPath } from '@/main_app/paths';
import { MemberSection } from './MemberSection';
import { OrganizationRenameForm } from './OrganizationRenameForm';

export type OrganizationDetailContentProps = {
    organization: OrganizationDetail;
    /** 保持している ETag (If-Match に使う)。 */
    etag: string | null;
    /** テナントの全ユーザー (メンバーの名前・選択肢)。 */
    users: readonly UserRead[];
    /** 更新の結果を詳細に反映する (useOrganization の applyUpdate)。 */
    onUpdated: (update: OrganizationActionUpdate) => void;
    /** 詳細を取り直す。 */
    onReload: () => void;
};

export const OrganizationDetailContent = ({ organization, etag, users, onUpdated, onReload }: OrganizationDetailContentProps) => {
    const navigate = useNavigate();
    const { tenant_code } = useAppSession();
    const { can_write } = useAppPermissions();
    const actions = useOrganizationActions({ onUpdated });
    const [notice, setNotice] = useState<string | null>(null);
    const [is_deleting, setIsDeleting] = useState(false);
    const target = { organization_id: organization.id, etag };

    const rename = async (name: string): Promise<boolean> => {
        setNotice(null);
        const result = await actions.update(target, { name });
        if (result.ok) setNotice('組織名を変更しました。');
        return result.ok;
    };

    const saveMembers = async (user_ids: string[]): Promise<boolean> => {
        setNotice(null);
        const result = await actions.setMembers(target, user_ids);
        if (result.ok) setNotice('メンバーを保存しました。');
        return result.ok;
    };

    const remove = async () => {
        setNotice(null);
        const result = await actions.remove(target);
        setIsDeleting(false);
        if (result.ok) void navigate(appOrganizationsPath(tenant_code));
    };

    const reloadAll = () => {
        actions.clearFailure();
        setNotice(null);
        onReload();
    };

    return (
        <>
            {notice && <Alert severity="success" role="status" onClose={() => setNotice(null)} data-testid="organization-detail-notice">{notice}</Alert>}
            {actions.failure && <AppErrorAlert error={actions.failure} test_id="organization-detail-action-error" onReload={reloadAll} />}
            {!can_write && <Alert severity="info" data-testid="organization-detail-readonly">閲覧のみ可能です。組織の変更はテナント管理者が行います。</Alert>}
            <OrganizationRenameForm key={`rename-${organization.version}`} organization={organization} can_write={can_write} pending={actions.pending === 'update'} onRename={rename} />
            <MemberSection
                key={`members-${organization.version}`}
                member_ids={organization.member_ids}
                users={users}
                can_write={can_write}
                pending={actions.pending === 'set_members'}
                onSave={saveMembers}
            />
            {can_write && (
                <Paper variant="outlined" component="section" aria-labelledby="organization-delete-heading" sx={{ p: 2 }} data-testid="organization-delete-panel">
                    <Typography id="organization-delete-heading" variant="h6" component="h2" gutterBottom>組織の削除</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>削除した組織は一覧から消え、画面からは元に戻せません。メンバーだったユーザー自体は削除されません。</Typography>
                    <Button
                        variant="outlined"
                        color="error"
                        startIcon={<DeleteIcon />}
                        disabled={actions.pending !== null}
                        onClick={() => {
                            actions.clearFailure();
                            setIsDeleting(true);
                        }}
                        data-testid="organization-delete"
                    >
                        この組織を削除
                    </Button>
                </Paper>
            )}
            <ConfirmDialog
                open={is_deleting}
                title="組織を削除しますか？"
                description={`組織「${organization.name}」を削除します。組織は一覧から消え、画面からは元に戻せません。メンバーだったユーザー自体は削除されません。`}
                confirm_label="削除する"
                confirm_color="error"
                pending={actions.pending === 'delete'}
                onConfirm={() => void remove()}
                onCancel={() => setIsDeleting(false)}
                test_id="organization-delete-dialog"
            />
        </>
    );
};

export default OrganizationDetailContent;
