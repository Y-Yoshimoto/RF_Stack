/**
 * @desc ToDo の見出しの下に出す、作成者・作成日時と最終更新者・更新日時 (AP-UX-09)
 * 無効化されたユーザーは名前に「(無効)」を添える。コメント・チェックリストの変更では更新日時は変わらない (§10 #16)。
 */
import { Stack, Typography } from '@mui/material';
import type { TodoRead } from '@/main_app/api/contract';
import { formatDateTime } from '@/main_app/components/format';
import { todoUserTextOf } from './todo_user_text';

export type TodoMetaLineProps = {
    todo: Pick<TodoRead, 'creator' | 'updater' | 'created_at' | 'updated_at'>;
};

export const TodoMetaLine = ({ todo }: TodoMetaLineProps) => (
    <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }} data-testid="todo-detail-meta">
        <Typography variant="body2" color="text.secondary" component="p" sx={{ minWidth: 0, maxWidth: '100%', overflowWrap: 'anywhere' }} data-testid="todo-detail-created">
            作成: <span data-testid="todo-detail-creator">{todoUserTextOf(todo.creator)}</span>・<time dateTime={todo.created_at}>{formatDateTime(todo.created_at)}</time>
        </Typography>
        <Typography variant="body2" color="text.secondary" component="p" sx={{ minWidth: 0, maxWidth: '100%', overflowWrap: 'anywhere' }} data-testid="todo-detail-updated">
            最終更新: <span data-testid="todo-detail-updater">{todoUserTextOf(todo.updater)}</span>・<time dateTime={todo.updated_at}>{formatDateTime(todo.updated_at)}</time>
        </Typography>
    </Stack>
);

export default TodoMetaLine;
