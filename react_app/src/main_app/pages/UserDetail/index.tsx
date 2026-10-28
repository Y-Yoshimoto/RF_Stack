/**
 * @desc ユーザー詳細・編集 (`/{tenant_code}/users/:userId`)
 * 基本情報 (ロール付き) を表示する。tenant_admin には姓名・ロールの編集と、有効/無効の切り替えを出す。member は閲覧のみ。
 * 自分自身の無効化・tenant_admin 解除は、ボタンを無効にして理由を表示する。412 / 428 (他の操作で更新済み) は再読み込みを促す。
 * 使うフック: useUser (詳細・ETag)、useMe (自分の ID)、useUserActions (更新。UserDetailContent)、useAppPermissions (権限)。
 */
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Chip, Stack } from '@mui/material';
import { useAppPermissions, useAppSession } from '@/main_app/auth/useAppAuth';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import { PageHeader } from '@/main_app/components/PageHeader';
import { useMe } from '@/main_app/me/useMe';
import { appUsersPath } from '@/main_app/paths';
import { useUser } from '@/main_app/users/useUser';
import { PageLoading } from '@/shared/components/PageLoading';
import { UserDetailContent } from './UserDetailContent';

export const AppUserDetailPage = () => {
    const { userId = '' } = useParams();
    const { tenant_code } = useAppSession();
    const { can_write } = useAppPermissions();
    const me = useMe();
    const detail = useUser(userId);
    const [notice, setNotice] = useState<string | null>(null);

    const user = detail.user;
    const is_loading = detail.status === 'loading' || me.status === 'loading';
    const is_self = user !== null && me.self_user_id === user.id;
    return (
        <Stack spacing={3} data-testid="app-user-detail-page" data-can-write={can_write}>
            <PageHeader
                test_id="user-detail"
                title={user?.display_name ?? 'ユーザー詳細'}
                description={is_self ? <Chip size="small" color="primary" label="あなた" data-testid="user-detail-self" /> : undefined}
                back={{ to: appUsersPath(tenant_code), label: 'ユーザー管理へ戻る' }}
            />

            {is_loading && <PageLoading />}
            {!is_loading && detail.status === 'error' && detail.error && <AppErrorAlert error={detail.error} test_id="user-detail-error" onReload={detail.reload} always_retry />}
            {!is_loading && user !== null && (
                <UserDetailContent user={user} etag={detail.etag} self_user_id={me.self_user_id} onUpdated={detail.applyUpdate} onReload={detail.reload} notice={notice} onNoticeChange={setNotice} />
            )}
        </Stack>
    );
};

export default AppUserDetailPage;
