/**
 * @desc ToDo 一覧の表 (タイトル・ステータス・優先度・期限・担当者・公開範囲・作成者・更新日時)
 * タイトルの下に、チェックリストの進捗とコメント数を出す (AP-UX-03)。
 * ステータスは、変更できる行 (can_change_status が true の行) ではセレクト、それ以外はアイコン付きのチップで表示する。
 */
import { Link as RouterLink } from 'react-router-dom';
import { Chip, Link, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material';
import type { TodoRead, TodoStatus } from '@/main_app/api/contract';
import { formatDateTime } from '@/main_app/components/format';
import { TodoDueText, TodoPriorityChip, TodoStatusChip } from '@/main_app/pages/TodoCommon/TodoBadges';
import { TodoItemMeta } from '@/main_app/pages/TodoCommon/TodoProgress';
import { TODO_VISIBILITY_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';
import { assigneeTextOf, userRefTextOf } from '@/main_app/pages/TodoCommon/todo_people';
import { appTodoPath } from '@/main_app/paths';
import { needsOrganizationReselect } from '@/main_app/todos/todo_changes';
import { TodoStatusSelect } from './TodoStatusSelect';

export type TodoTableProps = {
    tenant_code: string;
    todos: readonly TodoRead[];
    /** 行からステータスを変えられるかの判定。 */
    canChangeStatus: (todo: TodoRead) => boolean;
    onChangeStatus: (todo: TodoRead, status: TodoStatus) => void;
    /** 操作中 (セレクトを無効にする)。 */
    pending: boolean;
};

const AudienceCell = ({ todo }: { todo: TodoRead }) => {
    if (needsOrganizationReselect(todo)) {
        return (
            <Stack spacing={0.5} sx={{ alignItems: 'flex-start' }}>
                <Typography variant="body2">{TODO_VISIBILITY_LABELS.private}</Typography>
                <Chip size="small" color="warning" variant="outlined" label="公開先の再指定が必要" data-testid={`todo-reselect-${todo.id}`} />
            </Stack>
        );
    }
    if (todo.visibility === 'organization') return <Typography variant="body2">{`${TODO_VISIBILITY_LABELS.organization}: ${todo.organizations.map((organization) => organization.name).join('、')}`}</Typography>;
    return <Typography variant="body2">{TODO_VISIBILITY_LABELS[todo.visibility]}</Typography>;
};

export const TodoTable = ({ tenant_code, todos, canChangeStatus, onChangeStatus, pending }: TodoTableProps) => (
    <TableContainer component={Paper} variant="outlined">
        <Table size="small" aria-label="ToDo 一覧" data-testid="todo-table">
            <TableHead>
                <TableRow>
                    <TableCell>タイトル</TableCell>
                    <TableCell>ステータス</TableCell>
                    <TableCell>優先度</TableCell>
                    <TableCell>期限</TableCell>
                    <TableCell>担当者</TableCell>
                    <TableCell>公開範囲</TableCell>
                    <TableCell>作成者</TableCell>
                    <TableCell>更新日時</TableCell>
                </TableRow>
            </TableHead>
            <TableBody>
                {todos.map((todo) => (
                    <TableRow key={todo.id} hover data-testid={`todo-row-${todo.id}`} data-status={todo.status}>
                        <TableCell component="th" scope="row" sx={{ overflowWrap: 'anywhere', minWidth: 200 }}>
                            <Link component={RouterLink} to={appTodoPath(tenant_code, todo.id)} underline="hover" data-testid={`todo-link-${todo.id}`}>{todo.title}</Link>
                            <TodoItemMeta checklist={todo.checklist} comment_count={todo.comment_count} todo_id={todo.id} />
                        </TableCell>
                        <TableCell data-testid={`todo-status-${todo.id}`}>
                            {canChangeStatus(todo)
                                ? <TodoStatusSelect todo_id={todo.id} title={todo.title} status={todo.status} disabled={pending} onChange={(status) => onChangeStatus(todo, status)} />
                                : <TodoStatusChip status={todo.status} test_id={`todo-status-chip-${todo.id}`} />}
                        </TableCell>
                        <TableCell><TodoPriorityChip priority={todo.priority} test_id={`todo-priority-${todo.id}`} /></TableCell>
                        <TableCell><TodoDueText due_date={todo.due_date} status={todo.status} test_id={`todo-due-${todo.id}`} /></TableCell>
                        <TableCell sx={{ overflowWrap: 'anywhere' }} data-testid={`todo-assignees-${todo.id}`}>{assigneeTextOf(todo)}</TableCell>
                        <TableCell data-testid={`todo-audience-${todo.id}`}><AudienceCell todo={todo} /></TableCell>
                        <TableCell sx={{ overflowWrap: 'anywhere' }} data-testid={`todo-creator-${todo.id}`}>{userRefTextOf(todo.creator)}</TableCell>
                        <TableCell sx={{ whiteSpace: 'nowrap' }} data-testid={`todo-updated-${todo.id}`}>{formatDateTime(todo.updated_at)}</TableCell>
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    </TableContainer>
);

export default TodoTable;
