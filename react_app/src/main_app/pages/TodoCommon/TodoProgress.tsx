/**
 * @desc ToDo のチェックリストの進捗 (「3/5」と細い進捗バー) とコメント数 (一覧・カード・ボードで共用)
 * 進捗は 0 件なら出さない。完了は色だけでなく、アイコンと「3/5」の文字でも示す。
 * 読み上げ用の隠し文字 (VISUALLY_HIDDEN は position: absolute) が、横スクロールのコンテナ (ボードの列) の外へはみ出さないよう、根の要素を position: relative にしている。
 */
import ChatBubbleOutlineIcon from '@mui/icons-material/ChatBubbleOutlineOutlined';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutlined';
import ChecklistIcon from '@mui/icons-material/Checklist';
import { Box, LinearProgress, Stack, Typography } from '@mui/material';
import type { TodoChecklistProgress } from '@/main_app/api/contract';
import { VISUALLY_HIDDEN } from '@/shared/components/visually_hidden';

export type TodoProgressProps = {
    checklist: TodoChecklistProgress;
    test_id: string;
};

export const TodoProgress = ({ checklist, test_id }: TodoProgressProps) => {
    const { done_count, total_count } = checklist;
    if (total_count <= 0) return null;
    const percent = Math.round((done_count / total_count) * 100);
    const completed = done_count >= total_count;
    return (
        <Box sx={{ position: 'relative', minWidth: 96, maxWidth: 200 }} data-testid={test_id} data-done={done_count} data-total={total_count}>
            <Stack direction="row" spacing={0.5} sx={{ alignItems: 'center', color: 'text.secondary' }}>
                {completed ? <CheckCircleOutlineIcon fontSize="inherit" color="success" aria-hidden /> : <ChecklistIcon fontSize="inherit" aria-hidden />}
                <Typography variant="caption" component="span" color="text.secondary">
                    <Box component="span" sx={VISUALLY_HIDDEN}>チェックリスト </Box>
                    {done_count}/{total_count}
                    {completed && <Box component="span" sx={VISUALLY_HIDDEN}> (すべて完了)</Box>}
                </Typography>
            </Stack>
            <LinearProgress
                variant="determinate"
                value={percent}
                color={completed ? 'success' : 'primary'}
                aria-label={`チェックリストの進捗 ${percent}%`}
                sx={{ height: 4, borderRadius: 2, mt: 0.25 }}
            />
        </Box>
    );
};

export type TodoCommentCountProps = {
    comment_count: number;
    test_id: string;
};

/** コメント数 (0 件なら出さない) */
export const TodoCommentCount = ({ comment_count, test_id }: TodoCommentCountProps) => {
    if (comment_count <= 0) return null;
    return (
        <Stack direction="row" spacing={0.5} component="span" sx={{ position: 'relative', alignItems: 'center', color: 'text.secondary', display: 'inline-flex' }} data-testid={test_id} data-count={comment_count}>
            <ChatBubbleOutlineIcon fontSize="inherit" aria-hidden />
            <Typography variant="caption" component="span" color="text.secondary">
                {comment_count}
                <Box component="span" sx={VISUALLY_HIDDEN}> 件のコメント</Box>
            </Typography>
        </Stack>
    );
};

export type TodoItemMetaProps = {
    checklist: TodoChecklistProgress;
    comment_count: number;
    /** 要素 ID (data-testid の接尾辞)。 */
    todo_id: string;
};

/** 進捗とコメント数を並べた行 (どちらも無ければ何も出さない) */
export const TodoItemMeta = ({ checklist, comment_count, todo_id }: TodoItemMetaProps) => {
    if (checklist.total_count <= 0 && comment_count <= 0) return null;
    return (
        <Stack direction="row" spacing={1.5} useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap', mt: 0.5 }} data-testid={`todo-meta-${todo_id}`}>
            <TodoProgress checklist={checklist} test_id={`todo-progress-${todo_id}`} />
            <TodoCommentCount comment_count={comment_count} test_id={`todo-comments-${todo_id}`} />
        </Stack>
    );
};

export default TodoProgress;
