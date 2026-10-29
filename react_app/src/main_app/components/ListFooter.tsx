/**
 * @desc 一覧の下部 (表示件数・「さらに読み込む」・読み込み失敗の通知)
 * 総件数 (total) を渡すと「N 件中 M 件を表示」とする。AP の一覧のうち総件数を取得しないもの (ユーザー・組織) は「M 件を表示」のまま。
 * auto_load を true にすると、末尾の番兵要素が見えたときに続きを自動で読み込む (無限スクロール。AP-UX-02)。
 * 「さらに読み込む」のボタンは、読み込みの失敗後・キーボード操作・IntersectionObserver が無い環境の代替として残す。
 */
import { Box, Button, CircularProgress, Stack, Typography } from '@mui/material';
import type { AppErrorInfo } from '@/main_app/api/errors';
import { useInfiniteScroll } from '@/shared/hooks/useInfiniteScroll';
import { AppErrorAlert } from './AppErrorAlert';

export type ListFooterProps = {
    /** 表示中の件数。 */
    count: number;
    /** 総件数 (取得していれば。省略または null なら「M 件を表示」)。 */
    total?: number | null;
    /** 件数の単位 (「件」など)。 */
    unit?: string;
    has_more: boolean;
    is_loading_more: boolean;
    load_more_error: AppErrorInfo | null;
    onLoadMore: () => void;
    /** 先頭から取り直す (requires_reload のエラーで使う)。 */
    onReload: () => void;
    /** 末尾が見えたら続きを自動で読み込む (既定は読み込まない)。 */
    auto_load?: boolean;
    /** data-testid の接頭辞。 */
    test_id: string;
};

/**
 * 件数の表示にする関数
 * @param {number} count 表示中の件数
 * @param {number | null | undefined} total 総件数
 * @param {string} unit 単位
 * @param {boolean} has_more 続きがあるか
 * @returns {string} 表示
*/
const countTextOf = (count: number, total: number | null | undefined, unit: string, has_more: boolean): string => {
    if (typeof total === 'number') return `${total} ${unit}中 ${count} ${unit}を表示`;
    return `${count} ${unit}を表示${has_more ? ' (続きがあります)' : ''}`;
};

export const ListFooter = ({ count, total, unit = '件', has_more, is_loading_more, load_more_error, onLoadMore, onReload, auto_load = false, test_id }: ListFooterProps) => {
    const sentinelRef = useInfiniteScroll({ enabled: auto_load && has_more && !is_loading_more && load_more_error === null, onLoadMore });
    return (
        <Stack spacing={2} sx={{ alignItems: 'flex-start' }}>
            <Typography variant="body2" color="text.secondary" role="status" data-testid={`${test_id}-count`}>
                {countTextOf(count, total, unit, has_more)}
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
            {auto_load && has_more && <Box ref={sentinelRef} aria-hidden sx={{ height: '1px', width: '100%' }} data-testid={`${test_id}-sentinel`} />}
        </Stack>
    );
};

export default ListFooter;
