/**
 * @desc 認証関連ページ (ランディング・ログイン・テナントのエラー) の中身を載せるカード
 * 見出し (h1) を持つ `<main>` として描画する。プレーン固有の配色はテーマ (primary) から取る。
 */
import type { ReactNode } from 'react';
import { Avatar, Paper, Stack, Typography } from '@mui/material';

export type AuthCardProps = {
    /** 見出し (h1)。 */
    title: string;
    /** 見出しの下の補足。 */
    description?: ReactNode;
    /** 見出しの上に出すアイコン (装飾。読み上げ対象にしない)。 */
    icon?: ReactNode;
    /** 見出しの色 (MUI の palette のキー)。既定は primary。エラー画面で error を使う。 */
    tone?: 'primary' | 'error' | 'warning';
    /** `<main>` の data-testid。 */
    test_id: string;
    /** その他の data-* 属性 (テストの検証用)。 */
    data_attributes?: Record<`data-${string}`, string>;
    children?: ReactNode;
};

export const AuthCard = ({ title, description, icon, tone = 'primary', test_id, data_attributes, children }: AuthCardProps) => {
    return (
        <Paper
            component="main"
            elevation={2}
            data-testid={test_id}
            {...data_attributes}
            sx={{ p: { xs: 3, sm: 5 }, borderTop: 6, borderColor: `${tone}.main`, borderRadius: 2 }}
        >
            <Stack spacing={3} sx={{ alignItems: 'stretch' }}>
                <Stack spacing={1.5} sx={{ alignItems: 'center', textAlign: 'center' }}>
                    {icon && <Avatar aria-hidden sx={{ bgcolor: `${tone}.main`, color: `${tone}.contrastText`, width: 56, height: 56 }}>{icon}</Avatar>}
                    <Typography variant="h5" component="h1">{title}</Typography>
                    {description && <Typography variant="body2" color="text.secondary" component="div">{description}</Typography>}
                </Stack>
                {children}
            </Stack>
        </Paper>
    );
};

export default AuthCard;
