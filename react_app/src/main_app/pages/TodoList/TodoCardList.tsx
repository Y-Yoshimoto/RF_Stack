/**
 * @desc ToDo 一覧のカード表示 (md 未満の幅。AP-UX-04)
 * 表と同じ情報・同じ操作 (権限があればステータスのセレクト、無ければチップ) を、TodoCard を並べて出す。
 */
import { Stack } from '@mui/material';
import type { TodoRead, TodoStatus } from '@/main_app/api/contract';
import { TodoCard } from '@/main_app/pages/TodoCommon/TodoCard';
import { TodoStatusChip } from '@/main_app/pages/TodoCommon/TodoBadges';
import { TodoStatusSelect } from './TodoStatusSelect';

export type TodoCardListProps = {
    tenant_code: string;
    todos: readonly TodoRead[];
    /** カードからステータスを変えられるかの判定。 */
    canChangeStatus: (todo: TodoRead) => boolean;
    onChangeStatus: (todo: TodoRead, status: TodoStatus) => void;
    /** 操作中 (セレクトを無効にする)。 */
    pending: boolean;
};

export const TodoCardList = ({ tenant_code, todos, canChangeStatus, onChangeStatus, pending }: TodoCardListProps) => (
    <Stack component="ul" role="list" aria-label="ToDo 一覧" spacing={1.5} sx={{ listStyle: 'none', m: 0, p: 0 }} data-testid="todo-card-list">
        {todos.map((todo) => (
            <li key={todo.id}>
                <TodoCard
                    todo={todo}
                    tenant_code={tenant_code}
                    status_control={canChangeStatus(todo)
                        ? <TodoStatusSelect todo_id={todo.id} title={todo.title} status={todo.status} disabled={pending} onChange={(status) => onChangeStatus(todo, status)} />
                        : <TodoStatusChip status={todo.status} test_id={`todo-status-chip-${todo.id}`} />}
                />
            </li>
        ))}
    </Stack>
);

export default TodoCardList;
