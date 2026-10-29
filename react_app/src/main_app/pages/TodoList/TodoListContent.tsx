/**
 * @desc ToDo 一覧のリスト表示の本体 (読み込み中・エラー・空・表／カードと、無限スクロールの出し分け)
 * 幅が md 以上なら表 (TodoTable)、md 未満ならカード (TodoCardList)。続きは末尾が見えたら自動で読み込み (ListFooter の auto_load)、
 * 「さらに読み込む」のボタンは失敗時・キーボード操作の代替として残す。ステータス変更は useTodoActions、一覧は useTodoList。
 */
import { useState, type ReactNode } from 'react';
import { Stack, useMediaQuery } from '@mui/material';
import { useTheme } from '@mui/material/styles';
import type { TodoRead, TodoStatus } from '@/main_app/api/contract';
import type { TodoListFilter } from '@/main_app/api/todos';
import { ListFooter } from '@/main_app/components/ListFooter';
import { TODO_STATUS_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { todoReadOf, todoTargetOf } from '@/main_app/todos/todo_changes';
import { useTodoActions } from '@/main_app/todos/useTodoActions';
import { useTodoList } from '@/main_app/todos/useTodoList';
import { PageLoading } from '@/shared/components/PageLoading';
import { TodoCardList } from './TodoCardList';
import { TodoTable } from './TodoTable';

export type TodoListContentProps = {
    /** 表示範囲・絞り込み・並び順。 */
    filter: TodoListFilter;
    tenant_code: string;
    /** 一覧の行からステータスを変えられるかの判定。 */
    canChangeStatus: (todo: TodoRead) => boolean;
    /** 一覧が空のときの案内。 */
    empty_state: ReactNode;
    /** 操作の結果の通知 (null で消す)。 */
    onNotice: (notice: string | null) => void;
};

export const TodoListContent = ({ filter, tenant_code, canChangeStatus, empty_state, onNotice }: TodoListContentProps) => {
    const list = useTodoList(filter);
    // md 未満の幅ではカード表示 (AP-UX-04)
    const is_narrow = useMediaQuery(useTheme().breakpoints.down('md'), { noSsr: true });
    const [changing_id, setChangingId] = useState<string | null>(null);
    const actions = useTodoActions({
        onUpdated: (update) => {
            if (update.action === 'change_status') list.replaceItem(todoReadOf(update.todo));
        },
    });

    const changeStatus = async (todo: TodoRead, status: TodoStatus) => {
        onNotice(null);
        setChangingId(todo.id);
        const result = await actions.changeStatus(todoTargetOf(todo), status);
        setChangingId(null);
        if (result.ok) onNotice(`「${todo.title}」のステータスを「${TODO_STATUS_LABELS[status]}」に変更しました。`);
    };

    const reloadAll = () => {
        actions.clearFailure();
        onNotice(null);
        list.reload();
    };

    const list_props = {
        tenant_code,
        todos: list.items,
        canChangeStatus,
        onChangeStatus: (todo: TodoRead, status: TodoStatus) => void changeStatus(todo, status),
        pending: actions.pending !== null && changing_id !== null,
    };

    return (
        <Stack spacing={3} data-testid="todo-list-content" data-layout={is_narrow ? 'cards' : 'table'}>
            {actions.failure && <TodoErrorAlert error={actions.failure} test_id="todo-list-action-error" onReload={reloadAll} />}

            {list.status === 'loading' && <PageLoading />}
            {list.status === 'error' && list.error && <TodoErrorAlert error={list.error} test_id="todo-list-error" onReload={list.reload} always_retry />}
            {list.status === 'success' && (
                list.items.length === 0 ? empty_state : (
                    <>
                        {is_narrow ? <TodoCardList {...list_props} /> : <TodoTable {...list_props} />}
                        <ListFooter
                            test_id="todo-list"
                            count={list.items.length}
                            total={list.total}
                            has_more={list.has_more}
                            is_loading_more={list.is_loading_more}
                            load_more_error={list.load_more_error}
                            onLoadMore={list.loadMore}
                            onReload={list.reload}
                            auto_load
                        />
                    </>
                )
            )}
        </Stack>
    );
};

export default TodoListContent;
