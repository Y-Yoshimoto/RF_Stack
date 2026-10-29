/**
 * @desc AP の管理画面の見出し部分 (戻るリンク・h1・説明・操作)
 */
import type { ReactNode } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Box, Link, Stack, Typography } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';

export type PageHeaderProps = {
    title: string;
    description?: ReactNode;
    /** 見出しの右に置く操作 (作成ボタンなど)。 */
    actions?: ReactNode;
    /** 戻り先 (一覧など)。 */
    back?: { to: string; label: string };
    /** data-testid の接頭辞 (`${test_id}-title` を見出しに付ける)。 */
    test_id: string;
};

export const PageHeader = ({ title, description, actions, back, test_id }: PageHeaderProps) => (
    <Box>
        {back && (
            <Link component={RouterLink} to={back.to} underline="hover" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, mb: 1 }} data-testid={`${test_id}-back`}>
                <ArrowBackIcon fontSize="small" aria-hidden />
                {back.label}
            </Link>
        )}
        <Stack direction="row" sx={{ alignItems: 'flex-start', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap' }}>
            <Box sx={{ minWidth: 0 }}>
                <Typography variant="h4" component="h1" gutterBottom={description !== undefined} sx={{ overflowWrap: 'anywhere' }} data-testid={`${test_id}-title`}>{title}</Typography>
                {description && <Typography variant="body1" color="text.secondary" component="div">{description}</Typography>}
            </Box>
            {actions && <Box sx={{ flexShrink: 0 }}>{actions}</Box>}
        </Stack>
    </Box>
);

export default PageHeader;
