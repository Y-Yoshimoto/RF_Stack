/**
 * @desc コメントの一覧 (古い順。読み込み中・失敗・空・「さらに読み込む」)
 */
import { Box, Button, CircularProgress, Typography } from '@mui/material';
import type { TodoCommentRead } from '@/main_app/api/contract';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import type { TodoCommentsState } from '@/main_app/todos/useTodoComments';
import { PageLoading } from '@/shared/components/PageLoading';
import { TodoCommentItem } from './TodoCommentItem';

export type TodoCommentsListProps = {
    comments: TodoCommentsState;
    /** 編集の保存の実行中。 */
    saving: boolean;
    onUpdate: (comment: TodoCommentRead, body: string) => Promise<boolean>;
    onRequestDelete: (comment: TodoCommentRead) => void;
};

export const TodoCommentsList = ({ comments, saving, onUpdate, onRequestDelete }: TodoCommentsListProps) => (
    <>
        {comments.status === 'loading' && <PageLoading />}
        {comments.status === 'error' && comments.error && <TodoErrorAlert error={comments.error} test_id="todo-comments-load-error" onReload={comments.reload} always_retry />}
        {comments.status === 'success' && comments.items.length === 0 && <Typography variant="body2" color="text.secondary" data-testid="todo-comments-empty">コメントはまだありません。</Typography>}
        {comments.status === 'success' && comments.items.length > 0 && (
            <Box component="ol" aria-label="コメント" sx={{ listStyle: 'none', m: 0, p: 0 }} data-testid="todo-comments-list">
                {comments.items.map((comment) => (
                    <TodoCommentItem key={comment.id} comment={comment} saving={saving} onUpdate={onUpdate} onRequestDelete={onRequestDelete} />
                ))}
            </Box>
        )}
        {comments.load_more_error && <TodoErrorAlert error={comments.load_more_error} test_id="todo-comments-load-more-error" onReload={comments.load_more_error.requires_reload ? comments.reload : comments.loadMore} always_retry />}
        {comments.has_more && (
            <Button
                variant="outlined"
                onClick={comments.loadMore}
                disabled={comments.is_loading_more}
                startIcon={comments.is_loading_more ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                sx={{ mt: 2 }}
                data-testid="todo-comments-load-more"
            >
                {comments.is_loading_more ? '読み込み中…' : 'さらに読み込む'}
            </Button>
        )}
    </>
);

export default TodoCommentsList;
