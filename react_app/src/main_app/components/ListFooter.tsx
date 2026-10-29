/**
 * @desc 一覧の下部 (表示件数・「さらに読み込む」・読み込み失敗の通知)
 * 総件数は AP の一覧では取得できないため、「N 件を表示」とする。
 */
import { Box, Button, CircularProgress, Stack, Typography } from '@mui/material';
import type { AppErrorInfo } from '@/main_app/api/errors';
import { AppErrorAlert } from './AppErrorAlert';

export type ListFooterProps = {
    /** 表示中の件数。 */
    count: number;
    /** 件数の単位 (「件」など)。 */
    unit?: string;
    has_more: boolean;
    is_loading_more: boolean;
    load_more_error: AppErrorInfo | null;
    onLoadMore: () => void;
    /** 先頭から取り直す (requires_reload のエラーで使う)。 */
    onReload: () => void;
    /** data-testid の接頭辞。 */
    test_id: string;
};

export const ListFooter = ({ count, unit = '件', has_more, is_loading_more, load_more_error, onLoadMore, onReload, test_id }: ListFooterProps) => (
    <Stack spacing={2} sx={{ alignItems: 'flex-start' }}>
        <Typography variant="body2" color="text.secondary" role="status" data-testid={`${test_id}-count`}>
            {count} {unit}を表示{has_more ? ' (続きがあります)' : ''}
        </Typography>
        {load_more_error && <AppErrorAlert error={load_more_error} test_id={`${test_id}-load-more-error`} onReload={load_more_error.requires_reload ? onReload : onLoadMore} always_retry />}
        {has_more && (
            <Box>
                <Button
                    variant="outlined"
                    onClick={onLoadMore}
                    disabled={is_loading_more}
                    startIcon={is_loading_more ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                    data-testid={`${test_id}-load-more`}
                >
                    {is_loading_more ? '読み込み中…' : 'さらに読み込む'}
                </Button>
            </Box>
        )}
    </Stack>
);

export default ListFooter;
