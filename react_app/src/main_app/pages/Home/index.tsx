/**
 * @desc AP のホーム (`/{tenant_code}/`。ログイン成功後の遷移先)
 * ヘッダー・ナビゲーション・ログアウトは AppLayout が持つ。この画面はログイン中のユーザーの概要と、今後追加する機能への入口の枠を出す。
 * 使えるフック: useAppSession (テナントコード・ユーザー)。AP の API 呼び出し (useAppApiClient) は、データを出す機能が加わる段階で使う。
 */
import { Link as RouterLink } from 'react-router-dom';
import { Box, Card, CardActionArea, CardContent, Chip, Stack, Typography } from '@mui/material';
import { useAppSession } from '@/main_app/auth/useAppAuth';
import { appNavItemsOf, appRoleLabelsOf } from '@/main_app/layouts/AppLayout/labels';

export const AppHomePage = () => {
    const { tenant_code, user } = useAppSession();
    const display_name = user.preferred_username ?? user.email ?? user.sub;
    // ホーム自身を除いた、機能への入口
    const feature_items = appNavItemsOf(tenant_code).filter((item) => item.id !== 'home');
    return (
        <Stack spacing={3} data-testid="app-home-page" data-tenant-code={tenant_code}>
            <Box>
                <Typography variant="h4" component="h1" gutterBottom>ホーム</Typography>
                <Typography variant="body1" color="text.secondary">
                    テナント「<Box component="span" data-testid="app-home-tenant" sx={{ fontWeight: 'bold' }}>{tenant_code}</Box>」にログインしています。
                </Typography>
            </Box>

            <Card variant="outlined" component="section" aria-labelledby="app-home-user-heading">
                <CardContent>
                    <Typography id="app-home-user-heading" variant="h6" component="h2" gutterBottom>ログイン中のユーザー</Typography>
                    <Stack spacing={1}>
                        <Typography variant="body1" data-testid="app-home-user">{display_name}</Typography>
                        {user.email && <Typography variant="body2" color="text.secondary" data-testid="app-home-email">{user.email}</Typography>}
                        <Stack direction="row" spacing={1} useFlexGap data-testid="app-home-roles" sx={{ flexWrap: 'wrap' }}>
                            {appRoleLabelsOf(user.roles).map((label) => <Chip key={label} size="small" label={label} />)}
                        </Stack>
                    </Stack>
                </CardContent>
            </Card>

            <Box component="section" aria-labelledby="app-home-features-heading">
                <Typography id="app-home-features-heading" variant="h6" component="h2" gutterBottom>機能</Typography>
                <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' } }}>
                    {feature_items.map((item) => (
                        <Card key={item.id} variant="outlined" data-testid={`app-home-feature-${item.id}`}>
                            {item.to === null ? (
                                <CardContent>
                                    <Typography variant="subtitle1" component="h3" color="text.secondary">{item.label}</Typography>
                                    <Chip size="small" variant="outlined" label="準備中" sx={{ mt: 1 }} />
                                </CardContent>
                            ) : (
                                <CardActionArea component={RouterLink} to={item.to}>
                                    <CardContent>
                                        <Typography variant="subtitle1" component="h3">{item.label}</Typography>
                                    </CardContent>
                                </CardActionArea>
                            )}
                        </Card>
                    ))}
                </Box>
            </Box>
        </Stack>
    );
};

export default AppHomePage;
