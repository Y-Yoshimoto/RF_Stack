/**
 * @desc ページ読み込み中の表示 (遅延読み込み・認証状態の確認中に使う)
 */
import { Box, CircularProgress } from '@mui/material';

export const PageLoading = () => {
    return (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
            <CircularProgress aria-busy="true" aria-label="読み込み中" data-testid="page-loading" />
        </Box>
    );
};

export default PageLoading;
