/**
 * @desc ページが見つからない場合の表示
 * 予約語の URL や、プレーン内の未定義のパスで表示する。
 */
import { Link as RouterLink } from 'react-router-dom';
import { Box, Button, Container, Stack, Typography } from '@mui/material';
import SearchOffIcon from '@mui/icons-material/SearchOff';

export type NotFoundPageProps = {
    /**
     * 認証後のレイアウト (ヘッダー・`<main>` を持つ) の中に表示する場合は true。
     * `<main>` を重ねないため、中身を `<section>` で描画する。
     */
    embedded?: boolean;
    /** 戻り先のパス。 */
    home_path?: string;
    /** 戻り先の文言。 */
    home_label?: string;
};

export const NotFoundPage = ({ embedded = false, home_path = '/', home_label = 'トップへ戻る' }: NotFoundPageProps) => {
    return (
        <Container maxWidth="sm" component={embedded ? 'section' : 'main'} data-testid="not-found-page" sx={{ py: { xs: 6, sm: 10 } }}>
            <Stack spacing={2} sx={{ alignItems: 'center', textAlign: 'center' }}>
                <Box aria-hidden sx={{ color: 'text.secondary', display: 'flex' }}>
                    <SearchOffIcon sx={{ fontSize: 64 }} />
                </Box>
                <Typography variant="h5" component="h1">ページが見つかりません</Typography>
                <Typography variant="body2" color="text.secondary">
                    お探しのページは存在しないか、移動した可能性があります。URL を確認してください。
                </Typography>
                <Button component={RouterLink} to={home_path} variant="contained" data-testid="not-found-home-link">{home_label}</Button>
            </Stack>
        </Container>
    );
};

export default NotFoundPage;
