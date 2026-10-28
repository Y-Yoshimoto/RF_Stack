/**
 * @desc ユーザー詳細の本体 (詳細の取得後に表示する。基本情報・編集・有効/無効)
 * 更新の操作 (useUserActions) と結果の通知はここで持つ。tenant_admin には編集を出し、member は閲覧のみ。
 */
import { Alert } from '@mui/material';
import type { UserDetail } from '@/main_app/api/contract';
import type { UserChanges } from '@/main_app/api/users';
import { useAppPermissions } from '@/main_app/auth/useAppAuth';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import { useUserActions } from '@/main_app/users/useUserActions';
import type { UserVersioned } from '@/main_app/users/useUser';
import { UserEditForm } from './UserEditForm';
import { UserInfo } from './UserInfo';
import { UserStatusPanel } from './UserStatusPanel';

export type UserDetailContentProps = {
    user: UserDetail;
    /** 保持している ETag (If-Match に使う)。 */
    etag: string | null;
    /** 自分のユーザー ID (未取得なら null)。 */
    self_user_id: string | null;
    /** 更新の結果を詳細に反映する (useUser の applyUpdate)。 */
    onUpdated: (update: UserVersioned) => void;
    /** 詳細を取り直す。 */
    onReload: () => void;
    /** 直前の操作の結果の通知 (ロールを変えた更新は詳細を取り直してこの画面が作り直されるため、呼び出し側が保持する)。 */
    notice: string | null;
    onNoticeChange: (notice: string | null) => void;
};

export const UserDetailContent = ({ user, etag, self_user_id, onUpdated, onReload, notice, onNoticeChange }: UserDetailContentProps) => {
    const { can_write } = useAppPermissions();
    const actions = useUserActions({ self_user_id, onUpdated });
    const pending = actions.pending === 'update';

    const save = async (changes: UserChanges, message: string): Promise<boolean> => {
        onNoticeChange(null);
        const result = await actions.update({ user_id: user.id, etag }, changes);
        if (result.ok) onNoticeChange(message);
        return result.ok;
    };

    const reloadAll = () => {
        actions.clearFailure();
        onNoticeChange(null);
        onReload();
    };

    return (
        <>
            {notice && <Alert severity="success" role="status" onClose={() => onNoticeChange(null)} data-testid="user-detail-notice">{notice}</Alert>}
            {actions.failure && <AppErrorAlert error={actions.failure} test_id="user-detail-action-error" onReload={reloadAll} />}
            <UserInfo user={user} />
            {can_write ? (
                <>
                    <UserEditForm key={user.version} user={user} self_user_id={self_user_id} pending={pending} onSave={(changes) => save(changes, '変更を保存しました。')} />
                    <UserStatusPanel
                        user={user}
                        self_user_id={self_user_id}
                        pending={pending}
                        onChange={(is_active) => save({ is_active }, is_active ? 'ユーザーを有効にしました。' : 'ユーザーを無効にしました。')}
                    />
                </>
            ) : (
                <Alert severity="info" data-testid="user-detail-readonly">閲覧のみ可能です。ユーザーの変更はテナント管理者が行います。</Alert>
            )}
        </>
    );
};

export default UserDetailContent;
