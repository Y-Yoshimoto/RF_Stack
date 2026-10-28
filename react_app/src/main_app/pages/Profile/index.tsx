/**
 * @desc プロフィール (`/{tenant_code}/profile`)
 * ログイン中のユーザーの表示名・メールアドレス・ロール・所属組織を表示する (参照のみ。tenant_admin / member の両方が使える)。
 * パスワードの変更は認証基盤 (Keycloak) 側で行うため、その案内を出す。
 * 使うフック: useMe (自分の ID・ロール)、useUser (表示名)、useMyOrganizations (所属組織)。
 */
import { Link as RouterLink } from 'react-router-dom';
import { Box, Chip, Paper, Stack, Typography } from '@mui/material';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import { PageHeader } from '@/main_app/components/PageHeader';
import { RoleChips } from '@/main_app/components/RoleChips';
import { useMe } from '@/main_app/me/useMe';
import { appOrganizationPath } from '@/main_app/paths';
import { useUser } from '@/main_app/users/useUser';
import { PageLoading } from '@/shared/components/PageLoading';
import { useMyOrganizations } from './useMyOrganizations';

/** 自分の ID が分かってから表示する本体 (useUser・useMyOrganizations は ID を必要とする) */
const ProfileBody = ({ tenant_code, user_id, username, email, roles }: { tenant_code: string; user_id: string; username: string | null; email: string | null; roles: string[] }) => {
    const detail = useUser(user_id);
    const organizations = useMyOrganizations(user_id);
    return (
        <>
            <Paper variant="outlined" component="section" aria-labelledby="profile-info-heading" sx={{ p: 2 }} data-testid="profile-info">
                <Typography id="profile-info-heading" variant="h6" component="h2" gutterBottom>基本情報</Typography>
                {detail.status === 'error' && detail.error && <AppErrorAlert error={detail.error} test_id="profile-user-error" onReload={detail.reload} always_retry />}
                <Box component="dl" sx={{ m: 0, display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: 3, rowGap: 1.5, alignItems: 'baseline' }}>
                    <Typography component="dt" variant="body2" color="text.secondary">表示名</Typography>
                    <Typography component="dd" variant="body1" sx={{ m: 0, overflowWrap: 'anywhere' }} data-testid="profile-display-name">
                        {detail.status === 'success' && detail.user ? detail.user.display_name : detail.status === 'loading' ? '読み込み中…' : '—'}
                    </Typography>
                    <Typography component="dt" variant="body2" color="text.secondary">ユーザー名</Typography>
                    <Typography component="dd" variant="body1" sx={{ m: 0, overflowWrap: 'anywhere' }} data-testid="profile-username">{username ?? '—'}</Typography>
                    <Typography component="dt" variant="body2" color="text.secondary">メールアドレス</Typography>
                    <Typography component="dd" variant="body1" sx={{ m: 0, overflowWrap: 'anywhere' }} data-testid="profile-email">{email ?? '—'}</Typography>
                    <Typography component="dt" variant="body2" color="text.secondary">ロール</Typography>
                    <Box component="dd" sx={{ m: 0 }}><RoleChips roles={roles} test_id="profile-roles" /></Box>
                    <Typography component="dt" variant="body2" color="text.secondary">テナント</Typography>
                    <Typography component="dd" variant="body1" sx={{ m: 0 }} data-testid="profile-tenant">{tenant_code}</Typography>
                </Box>
            </Paper>

            <Paper variant="outlined" component="section" aria-labelledby="profile-organizations-heading" sx={{ p: 2 }} data-testid="profile-organizations">
                <Typography id="profile-organizations-heading" variant="h6" component="h2" gutterBottom>所属組織</Typography>
                {organizations.status === 'loading' && <PageLoading />}
                {organizations.status === 'error' && organizations.error && <AppErrorAlert error={organizations.error} test_id="profile-organizations-error" onReload={organizations.reload} always_retry />}
                {organizations.status === 'success' && (
                    organizations.organizations.length === 0 ? (
                        <Typography variant="body2" color="text.secondary" data-testid="profile-organizations-empty">所属している組織はありません。</Typography>
                    ) : (
                        <Stack component="ul" direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', listStyle: 'none', m: 0, p: 0 }} data-testid="profile-organizations-list">
                            {organizations.organizations.map((organization) => (
                                <li key={organization.id}>
                                    <Chip component={RouterLink} to={appOrganizationPath(tenant_code, organization.id)} clickable label={organization.name} data-testid={`profile-organization-${organization.id}`} />
                                </li>
                            ))}
                        </Stack>
                    )
                )}
            </Paper>
        </>
    );
};

export const AppProfilePage = () => {
    const me = useMe();
    return (
        <Stack spacing={3} data-testid="app-profile-page">
            <PageHeader test_id="profile" title="プロフィール" description="ログイン中のあなたの情報です。" />

            {me.status === 'loading' && <PageLoading />}
            {me.status === 'error' && me.error && <AppErrorAlert error={me.error} test_id="profile-error" onReload={me.reload} always_retry />}
            {me.status === 'success' && me.me && (
                <ProfileBody tenant_code={me.me.tenant.tenant_code} user_id={me.me.user.id} username={me.me.user.username} email={me.me.user.email} roles={me.me.user.roles} />
            )}

            <Paper variant="outlined" component="section" aria-labelledby="profile-password-heading" sx={{ p: 2 }} data-testid="profile-password">
                <Typography id="profile-password-heading" variant="h6" component="h2" gutterBottom>パスワードの変更</Typography>
                <Typography variant="body2" color="text.secondary">
                    パスワードの変更はこの画面では行えません。認証基盤 (Keycloak) のアカウント管理画面で変更してください。
                    パスワードを忘れた場合や、アカウント管理画面を開けない場合は、テナント管理者に依頼してください。
                </Typography>
            </Paper>
        </Stack>
    );
};

export default AppProfilePage;
