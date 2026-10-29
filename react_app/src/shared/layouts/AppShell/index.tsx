/**
 * @desc 認証後の画面の共通レイアウト (ヘッダー・ナビゲーション・本文)
 * AP / CP の両方で使う。プレーン固有の値 (テナントコード・ユーザー・項目・ログアウト処理) はすべてプロップで受け取り、ここにはロジックを持たない (01 §11.2)。
 * 本文は `<main>` で描画する。子の画面は `<main>` を重ねないこと。
 */
import type { ReactNode } from 'react';
import { Link as RouterLink, NavLink } from 'react-router-dom';
import { AppBar, Box, Button, Chip, Container, GlobalStyles, Stack, Toolbar, Typography } from '@mui/material';
import PersonIcon from '@mui/icons-material/Person';
import { LogoutButton } from '@/shared/components/LogoutButton';
import { VISUALLY_HIDDEN } from '@/shared/components/visually_hidden';
import type { NavItem } from './nav_item';

export type AppShellProps = {
    /** ヘッダーの主表示 (AP: テナントコード、CP: コントロールプレーン)。 */
    title: string;
    /** 主表示の上に小さく出す補足 (AP: 「テナント」)。 */
    caption?: string;
    /** 主表示のリンク先 (ホーム)。 */
    title_to: string;
    /** 主表示の横に出すバッジ (CP: 管理画面であることの表示)。 */
    badge_label?: string;
    /** ヘッダーに出すアイコン (装飾)。 */
    icon?: ReactNode;
    /** ログイン中のユーザーの表示名。 */
    user_name: string;
    /** ユーザー名の横に出す補足 (権限など)。 */
    user_note?: string;
    /** ナビゲーション項目。 */
    nav_items: NavItem[];
    /** ナビゲーションの読み上げ名。 */
    nav_label?: string;
    /** ログアウトを実行する。失敗時は reject する。 */
    onLogout: () => Promise<void>;
    children: ReactNode;
};

const MAIN_ID = 'main-content';

/** 現在地の項目の見た目 (色だけに頼らず、下線と太字でも示す) */
const NAV_CURRENT_SX = { color: 'primary.main', fontWeight: 'bold', borderBottomColor: 'primary.main' } as const;

const NavButton = ({ item }: { item: NavItem }) => {
    const common_sx = { borderRadius: 0, borderBottom: 3, borderBottomColor: 'transparent', whiteSpace: 'nowrap', py: 1.5, px: 2, flexShrink: 0 } as const;
    if (item.to === null) {
        return (
            <Button disabled color="inherit" startIcon={item.icon} sx={common_sx} data-testid={`nav-${item.id}`} data-ready="false">
                {item.label}
                <Box component="span" sx={VISUALLY_HIDDEN}>（準備中）</Box>
            </Button>
        );
    }
    return (
        <Button
            component={NavLink}
            to={item.to}
            end={item.end}
            color="inherit"
            startIcon={item.icon}
            sx={{ ...common_sx, '&[aria-current="page"]': NAV_CURRENT_SX }}
            data-testid={`nav-${item.id}`}
            data-ready="true"
        >
            {item.label}
        </Button>
    );
};

export const AppShell = ({ title, caption, title_to, badge_label, icon, user_name, user_note, nav_items, nav_label = 'メインナビゲーション', onLogout, children }: AppShellProps) => {
    return (
        <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', bgcolor: 'background.default' }} data-testid="app-shell">
            {/* 全幅のヘッダーをブラウザの既定の余白 (body の margin) なしで表示する */}
            <GlobalStyles styles={{ body: { margin: 0 } }} />
            <AppBar position="static" elevation={0} data-testid="app-shell-header">
                <Box
                    component="a"
                    href={`#${MAIN_ID}`}
                    sx={{ ...VISUALLY_HIDDEN, '&:focus': { position: 'fixed', top: 8, left: 8, width: 'auto', height: 'auto', m: 0, p: 1.5, clip: 'auto', clipPath: 'none', zIndex: 'tooltip', bgcolor: 'background.paper', color: 'text.primary', borderRadius: 1, boxShadow: 4 } }}
                >
                    本文へ移動
                </Box>
                <Toolbar sx={{ gap: 2, flexWrap: 'wrap', py: 0.5 }}>
                    <Stack
                        component={RouterLink}
                        to={title_to}
                        direction="row"
                        spacing={1.5}
                        sx={{ alignItems: 'center', color: 'inherit', textDecoration: 'none', minWidth: 0, flexGrow: 1 }}
                        data-testid="app-shell-title-link"
                    >
                        {icon && <Box aria-hidden sx={{ display: 'flex' }}>{icon}</Box>}
                        <Box sx={{ minWidth: 0 }}>
                            {caption && <Typography variant="caption" component="p" sx={{ lineHeight: 1.2 }}>{caption}</Typography>}
                            <Typography variant="h6" component="p" noWrap data-testid="app-shell-title" sx={{ lineHeight: 1.3 }}>{title}</Typography>
                        </Box>
                        {badge_label && <Chip size="small" label={badge_label} color="secondary" data-testid="app-shell-badge" />}
                    </Stack>
                    <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', minWidth: 0 }}>
                        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', minWidth: 0 }}>
                            <PersonIcon aria-hidden fontSize="small" />
                            <Typography variant="body2" noWrap data-testid="app-shell-user">{user_name}</Typography>
                            {user_note && <Chip size="small" variant="outlined" label={user_note} data-testid="app-shell-user-note" sx={{ color: 'inherit', borderColor: 'currentColor' }} />}
                        </Stack>
                        <LogoutButton onLogout={onLogout} />
                    </Stack>
                </Toolbar>
            </AppBar>
            <Box component="nav" aria-label={nav_label} sx={{ bgcolor: 'background.paper', borderBottom: 1, borderColor: 'divider', overflowX: 'auto' }} data-testid="app-shell-nav">
                <Container maxWidth="lg" disableGutters sx={{ px: { xs: 1, sm: 2 } }}>
                    <Stack component="ul" direction="row" sx={{ listStyle: 'none', m: 0, p: 0 }}>
                        {nav_items.map((item) => (
                            <Box component="li" key={item.id} sx={{ display: 'flex' }}>
                                <NavButton item={item} />
                            </Box>
                        ))}
                    </Stack>
                </Container>
            </Box>
            <Container component="main" id={MAIN_ID} tabIndex={-1} maxWidth="lg" sx={{ py: 3, flexGrow: 1, outline: 'none' }} data-testid="app-shell-main">
                {children}
            </Container>
        </Box>
    );
};

export default AppShell;
