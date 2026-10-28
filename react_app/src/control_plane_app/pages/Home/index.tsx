/**
 * @desc CP のホーム (`/cp/`。ログイン成功後の遷移先。ダッシュボード)
 * ヘッダー・ナビゲーション・ログアウトは CpLayout が持つ。この画面は全体サマリーの枠と、ログイン中のユーザーの権限を出す。
 * saas_viewer (can_write=false) には変更操作の UI を出さず、参照のみであることを知らせる (01 §11.2)。
 * 使えるフック: useCpSession (ユーザー)、useCpPermissions (saas_viewer の判定)。CP の API 呼び出し (useCpApiClient) は、サマリーの取得を加える段階で使う。
 */
import { Alert, Box, Card, CardContent, Chip, Stack, Typography } from '@mui/material';
import { useCpPermissions, useCpSession } from '@/control_plane_app/auth/useCpAuth';
import { cpPermissionLabelOf } from '@/control_plane_app/layouts/CpLayout/labels';

/** 全体サマリーの項目 (値は取得の実装後に出す) */
const SUMMARY_ITEMS = [
    { id: 'total', label: 'テナント数' },
    { id: 'active', label: '稼働中' },
    { id: 'provisioning', label: '払い出し中' },
    { id: 'suspended', label: '停止中' },
] as const;

export const CpHomePage = () => {
    const { user } = useCpSession();
    const permissions = useCpPermissions();
    const display_name = user.preferred_username ?? user.email ?? user.sub;
    return (
        <Stack spacing={3} data-testid="cp-home-page" data-can-write={permissions.can_write}>
            <Box>
                <Typography variant="h4" component="h1" gutterBottom>ダッシュボード</Typography>
                <Typography variant="body1" color="text.secondary">全テナントの状況の概要です。</Typography>
            </Box>

            {!permissions.can_write && (
                <Alert severity="info" data-testid="cp-home-viewer-notice">
                    閲覧専用の権限でログインしています。テナントの参照はできますが、作成・停止・再開・削除はできません。
                </Alert>
            )}

            <Box component="section" aria-labelledby="cp-home-summary-heading">
                <Typography id="cp-home-summary-heading" variant="h6" component="h2" gutterBottom>全体サマリー</Typography>
                <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' } }}>
                    {SUMMARY_ITEMS.map((item) => (
                        <Card key={item.id} variant="outlined" data-testid={`cp-home-summary-${item.id}`}>
                            <CardContent>
                                <Typography variant="body2" color="text.secondary">{item.label}</Typography>
                                <Typography variant="h4" component="p" aria-hidden>—</Typography>
                                <Typography variant="caption" color="text.secondary">準備中</Typography>
                            </CardContent>
                        </Card>
                    ))}
                </Box>
            </Box>

            <Card variant="outlined" component="section" aria-labelledby="cp-home-user-heading">
                <CardContent>
                    <Typography id="cp-home-user-heading" variant="h6" component="h2" gutterBottom>ログイン中のユーザー</Typography>
                    <Stack spacing={1}>
                        <Typography variant="body1" data-testid="cp-home-user">{display_name}</Typography>
                        {user.email && <Typography variant="body2" color="text.secondary" data-testid="cp-home-email">{user.email}</Typography>}
                        <Stack direction="row" spacing={1}>
                            <Chip size="small" color="primary" label={cpPermissionLabelOf(permissions)} data-testid="cp-home-permission" />
                        </Stack>
                    </Stack>
                </CardContent>
            </Card>
        </Stack>
    );
};

export default CpHomePage;
