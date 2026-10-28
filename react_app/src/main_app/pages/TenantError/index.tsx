/**
 * @desc AP のエラー画面 (テナント不在・停止中・利用不可・別テナントでログイン中)
 * 認証後のレイアウトの外 (ログイン画面・ルートガード・テナントコード不正) に置かれるため、AuthContainer で自分を包む。
 * ログアウトの失敗は LogoutButton が通知する。
 */
import type { ReactNode } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Button, Stack, Typography } from '@mui/material';
import BlockIcon from '@mui/icons-material/Block';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutlined';
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutlined';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import { appHomePath, LANDING_PATH } from '@/main_app/paths';
import { AuthCard, type AuthCardProps } from '@/shared/components/AuthCard';
import { LogoutButton } from '@/shared/components/LogoutButton';
import { AuthContainer } from '@/shared/layouts/AuthLayout';

/**
 * エラーの種類。
 * - not_found: テナントが存在しない (削除済み・形式不正・予約語を含む)
 * - suspended: 停止中・削除要求中
 * - unavailable: 払い出し中など、それ以外の理由で利用できない
 * - mismatch: 別テナントでログイン中 (AP のセッションはブラウザあたり 1 テナント。ログアウトしてから切り替える)
 */
export type TenantErrorKind = 'not_found' | 'suspended' | 'unavailable' | 'mismatch';

export type TenantErrorPageProps = {
    /** エラーの種類。 */
    kind: TenantErrorKind;
    /** URL のテナントコード。 */
    tenant_code: string;
    /** ログイン中のテナントコード (mismatch のみ)。 */
    session_tenant_code?: string | null;
    /** ログアウトする (mismatch のみ)。失敗時は reject する (画面に失敗を表示する)。 */
    onLogout?: () => Promise<void>;
};

type KindView = {
    title: string;
    tone: NonNullable<AuthCardProps['tone']>;
    icon: ReactNode;
    /** 補足の文言 (テナントコードを受け取る)。 */
    detail: (tenant_code: string) => string;
};

const KIND_VIEWS: Readonly<Record<TenantErrorKind, KindView>> = {
    not_found: {
        title: 'テナントが見つかりません',
        tone: 'error',
        icon: <ErrorOutlineIcon />,
        detail: (tenant_code) => `テナントコード「${tenant_code}」のテナントは存在しないか、利用できません。テナントコードを確認してください。`,
    },
    suspended: {
        title: 'このテナントは停止中です',
        tone: 'warning',
        icon: <PauseCircleOutlineIcon />,
        detail: (tenant_code) => `テナント「${tenant_code}」は現在停止されています。再開については、テナントの管理者または運用担当者に確認してください。`,
    },
    unavailable: {
        title: 'このテナントは現在利用できません',
        tone: 'warning',
        icon: <BlockIcon />,
        detail: (tenant_code) => `テナント「${tenant_code}」は準備中などの理由で利用できません。しばらくしてからもう一度お試しください。`,
    },
    mismatch: {
        title: '別のテナントにログイン中です',
        tone: 'warning',
        icon: <SwapHorizIcon />,
        detail: (tenant_code) => `テナント「${tenant_code}」を開くには、いまのテナントからログアウトしてください。同じブラウザで同時にログインできるテナントは 1 つです。`,
    },
};

export const TenantErrorPage = ({ kind, tenant_code, session_tenant_code, onLogout }: TenantErrorPageProps) => {
    const view = KIND_VIEWS[kind];
    const is_mismatch = kind === 'mismatch';
    return (
        <AuthContainer>
            <AuthCard
                test_id="tenant-error-page"
                data_attributes={{ 'data-kind': kind }}
                title={view.title}
                tone={view.tone}
                icon={view.icon}
                description={view.detail(tenant_code)}
            >
                <Stack spacing={1.5}>
                    {is_mismatch && session_tenant_code && (
                        <Button component={RouterLink} to={appHomePath(session_tenant_code)} variant="contained" data-testid="tenant-error-current-tenant">
                            ログイン中のテナント「{session_tenant_code}」に戻る
                        </Button>
                    )}
                    {is_mismatch && onLogout && (
                        <LogoutButton onLogout={onLogout} test_id="tenant-error-logout" label="ログアウトしてテナントを切り替える" variant="outlined" color="primary" />
                    )}
                    <Button component={RouterLink} to={LANDING_PATH} variant={is_mismatch ? 'text' : 'contained'} data-testid="tenant-error-top-link">
                        トップへ戻る
                    </Button>
                </Stack>
                {!is_mismatch && (
                    <Typography variant="caption" component="p" color="text.secondary" sx={{ textAlign: 'center' }}>
                        解決しない場合は、テナントの管理者にお問い合わせください
                    </Typography>
                )}
            </AuthCard>
        </AuthContainer>
    );
};

export default TenantErrorPage;
