/**
 * @desc カンバンの 1 列 (ステータス 1 つ。AP-BRD-02・05)
 * useDroppable でカードの移動先になる。見出しに総件数 (total。取得前は読み込み済みの件数) を出し、列ごとに無限スクロールで続きを読み込む。
 * 移動先の列は、色だけでなく破線の枠でも示す。列の中は縦にスクロールする (固定の高さ)。
 */
import { useId, type ReactNode } from 'react';
import { useDroppable } from '@dnd-kit/core';
import { Box, Chip, CircularProgress, Paper, Stack, Typography } from '@mui/material';
import type { TodoRead, TodoStatus } from '@/main_app/api/contract';
import { ListFooter } from '@/main_app/components/ListFooter';
import { TODO_STATUS_ICONS } from '@/main_app/pages/TodoCommon/TodoBadges';
import { TODO_STATUS_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { boardColumnIdOf } from '@/main_app/todos/board_dnd';
import type { TodoListState } from '@/main_app/todos/useTodoList';

export type TodoBoardColumnProps = {
    status: TodoStatus;
    list: TodoListState;
    /** 1 枚のカード。 */
    renderCard: (todo: TodoRead) => ReactNode;
};

export const TodoBoardColumn = ({ status, list, renderCard }: TodoBoardColumnProps) => {
    const heading_id = useId();
    const { setNodeRef, isOver } = useDroppable({ id: boardColumnIdOf(status) });
    const count = list.total ?? list.items.length;
    return (
        <Paper
            ref={setNodeRef}
            variant="outlined"
            role="group"
            aria-labelledby={heading_id}
            sx={{ display: 'flex', flexDirection: 'column', boxSizing: 'border-box', p: 1.5, gap: 1.5, bgcolor: isOver ? 'action.hover' : 'background.default', outline: isOver ? '2px dashed' : 'none', outlineColor: 'primary.main', outlineOffset: -2 }}
            data-testid={`todo-board-column-${status}`}
            data-over={isOver}
        >
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
                {TODO_STATUS_ICONS[status]}
                <Typography id={heading_id} variant="subtitle1" component="h2" sx={{ flex: 1 }} data-testid={`todo-board-heading-${status}`}>{TODO_STATUS_LABELS[status]}</Typography>
                {list.status === 'success' && <Chip size="small" label={`${count} 件`} data-testid={`todo-board-count-${status}`} data-total={list.total ?? ''} />}
            </Stack>

            <Box sx={{ overflowY: 'auto', maxHeight: 'max(320px, calc(100vh - 360px))', minHeight: 96 }}>
                {list.status === 'loading' && (
                    <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                        <CircularProgress size={24} aria-label={`${TODO_STATUS_LABELS[status]}を読み込み中`} data-testid={`todo-board-loading-${status}`} />
                    </Box>
                )}
                {list.status === 'error' && list.error && <TodoErrorAlert error={list.error} test_id={`todo-board-column-error-${status}`} onReload={list.reload} always_retry />}
                {list.status === 'success' && (
                    <Stack spacing={1.5}>
                        {list.items.length === 0 ? (
                            <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }} data-testid={`todo-board-empty-${status}`}>
                                {`「${TODO_STATUS_LABELS[status]}」の ToDo はありません。`}
                            </Typography>
                        ) : (
                            <Stack component="ul" role="list" aria-label={`${TODO_STATUS_LABELS[status]}の ToDo`} spacing={1.5} sx={{ listStyle: 'none', m: 0, p: 0 }}>
                                {list.items.map((todo) => <li key={todo.id}>{renderCard(todo)}</li>)}
                            </Stack>
                        )}
                        {(list.items.length > 0 || list.has_more) && (
                            <ListFooter
                                test_id={`todo-board-${status}`}
                                count={list.items.length}
                                total={list.total}
                                has_more={list.has_more}
                                is_loading_more={list.is_loading_more}
                                load_more_error={list.load_more_error}
                                onLoadMore={list.loadMore}
                                onReload={list.reload}
                                auto_load
                            />
                        )}
                    </Stack>
                )}
            </Box>
        </Paper>
    );
};

export default TodoBoardColumn;
