/**
 * @desc ToDo のカンバン (ボード表示。AP-BRD-01〜06)
 * ステータス (未着手 / 進行中 / 完了) の 3 列に、一覧と共通の絞り込み・並び順 (ステータスを除く) の ToDo を並べる。
 * カードを別の列へ移すとステータスが変わる (useTodoBoard の moveCard。楽観的に移し、失敗したら戻して TodoErrorAlert で知らせる)。
 * - センサー: マウス (6px 動かすと開始。クリックはそのまま通る)・タッチ (250ms 長押し。縦のスクロールを妨げない)・キーボード (ハンドルで持ち上げ、左右の矢印で隣の列へ)
 * - 読み上げ: 日本語の操作説明と、持ち上げ・移動・配置・取り消しの通知 (board_dnd.ts)
 * - ドラッグ以外の手段: カードのメニューのステータスのセレクト (TodoDraggableCard)
 * - モバイル (md 未満): 列を横スクロールにし、1 列を画面幅の 85% にして scroll-snap で揃える
 */
import { useState, type ReactNode } from 'react';
import { DndContext, DragOverlay, KeyboardSensor, PointerSensor, TouchSensor, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from '@dnd-kit/core';
import { Box } from '@mui/material';
import { TODO_STATUSES, type TodoRead, type TodoStatus } from '@/main_app/api/contract';
import type { TodoListFilter } from '@/main_app/api/todos';
import { TodoCard } from '@/main_app/pages/TodoCommon/TodoCard';
import { TODO_STATUS_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { TODO_BOARD_SCREEN_READER_INSTRUCTIONS, boardCardTodoOf, boardDropOf, boardKeyboardCoordinates, todoBoardAnnouncementsOf } from '@/main_app/todos/board_dnd';
import { useTodoBoard } from '@/main_app/todos/useTodoBoard';
import { TodoBoardColumn } from './TodoBoardColumn';
import { TodoDraggableCard } from './TodoDraggableCard';

export type TodoBoardProps = {
    /** 表示範囲・絞り込み・並び順 (status は無視される)。 */
    filter: TodoListFilter;
    tenant_code: string;
    /** カードを掴めるか (ステータスを変更できるか) の判定。 */
    canChangeStatus: (todo: TodoRead) => boolean;
    /** すべての列が空のときの案内。 */
    empty_state: ReactNode;
    /** 操作の結果の通知 (null で消す)。 */
    onNotice: (notice: string | null) => void;
};

/** DndContext の読み上げ (列の外に作ると毎回作り直さずに済む) */
const ACCESSIBILITY = {
    announcements: todoBoardAnnouncementsOf(TODO_STATUS_LABELS),
    screenReaderInstructions: TODO_BOARD_SCREEN_READER_INSTRUCTIONS,
};

/** 列の並び (横。md 未満は横スクロールで scroll-snap) */
const COLUMNS_SX = {
    // position: absolute の子孫 (読み上げ用の隠し文字など) もこの中でクリップし、ページ全体の幅を広げない
    position: 'relative',
    display: 'flex',
    gap: 2,
    alignItems: 'flex-start',
    overflowX: { xs: 'auto', md: 'visible' },
    scrollSnapType: { xs: 'x mandatory', md: 'none' },
    pb: { xs: 1, md: 0 },
    '& > *': { flex: { xs: '0 0 85vw', md: '1 1 0' }, minWidth: 0, scrollSnapAlign: 'start' },
} as const;

export const TodoBoard = ({ filter, tenant_code, canChangeStatus, empty_state, onNotice }: TodoBoardProps) => {
    const board = useTodoBoard(filter);
    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
        useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }),
        useSensor(KeyboardSensor, { coordinateGetter: boardKeyboardCoordinates }),
    );
    const [dragging, setDragging] = useState<TodoRead | null>(null);

    const move = async (todo: TodoRead, to_status: TodoStatus) => {
        onNotice(null);
        const result = await board.moveCard(todo, to_status);
        if (result.ok && result.todo !== null) onNotice(`「${todo.title}」のステータスを「${TODO_STATUS_LABELS[to_status]}」に変更しました。`);
    };

    const onDragStart = (event: DragStartEvent) => setDragging(boardCardTodoOf(event.active.data.current));
    const onDragEnd = (event: DragEndEvent) => {
        setDragging(null);
        const drop = boardDropOf(event.active, event.over);
        if (drop !== null) void move(drop.todo, drop.to_status);
    };

    const reloadAll = () => {
        board.clearFailure();
        onNotice(null);
        board.reload();
    };

    const all_empty = TODO_STATUSES.every((status) => board.columns[status].status === 'success' && board.columns[status].items.length === 0);
    const busy = board.moving_id !== null;

    return (
        <Box data-testid="todo-board" data-busy={busy}>
            {board.failure && <Box sx={{ mb: 2 }}><TodoErrorAlert error={board.failure} test_id="todo-board-error" onReload={reloadAll} /></Box>}
            {all_empty ? empty_state : (
                <DndContext sensors={sensors} accessibility={ACCESSIBILITY} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setDragging(null)}>
                    <Box role="group" aria-label="ステータス別のボード" sx={COLUMNS_SX} data-testid="todo-board-columns">
                        {TODO_STATUSES.map((status) => (
                            <TodoBoardColumn
                                key={status}
                                status={status}
                                list={board.columns[status]}
                                renderCard={(todo) => (
                                    <TodoDraggableCard
                                        todo={todo}
                                        tenant_code={tenant_code}
                                        can_change={canChangeStatus(todo)}
                                        busy={busy}
                                        moving={board.moving_id === todo.id}
                                        onChangeStatus={(target, next) => void move(target, next)}
                                    />
                                )}
                            />
                        ))}
                    </Box>
                    <DragOverlay>
                        {dragging && <Box aria-hidden sx={{ cursor: 'grabbing' }}><TodoCard todo={dragging} tenant_code={tenant_code} compact preview /></Box>}
                    </DragOverlay>
                </DndContext>
            )}
        </Box>
    );
};

export default TodoBoard;
