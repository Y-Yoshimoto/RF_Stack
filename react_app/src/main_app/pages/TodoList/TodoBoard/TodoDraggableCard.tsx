/**
 * @desc カンバンのカード (useDraggable で TodoCard を包む。AP-BRD-03・04)
 * - 掴む操作: ポインタ・タッチはカード全体、キーボード・スクリーンリーダーは先頭のハンドル (スペース / Enter で持ち上げ、左右の矢印で隣の列へ)
 *   リンクやメニューのボタンを入れ子にしないよう、フォーカスできる要素 (role="button") はハンドルだけにしている
 * - ステータスを変更できないカード (canChangeStatusInList が false。取得前を含む) は掴めない: ハンドルを鍵アイコンにし、aria-disabled とツールチップで理由を示す
 * - ドラッグ以外の手段: 右上のメニューを開き、既存の TodoStatusSelect でステータスを選ぶ
 * 移動中は、どのカードも掴めない (useTodoBoard が二重の移動を弾くため)。
 */
import { useState } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Box, IconButton, Popover, Stack, Tooltip, Typography } from '@mui/material';
import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import type { TodoRead, TodoStatus } from '@/main_app/api/contract';
import { TodoCard } from '@/main_app/pages/TodoCommon/TodoCard';
import { boardCardDataOf } from '@/main_app/todos/board_dnd';
import { TodoStatusSelect } from '../TodoStatusSelect';

/** 掴めない理由 (鍵アイコンのツールチップ) */
export const TODO_BOARD_LOCKED_TEXT = 'ステータスを変更できるのは作成者・担当者・テナント管理者です';

export type TodoDraggableCardProps = {
    todo: TodoRead;
    tenant_code: string;
    /** ステータスを変更できる (権限)。 */
    can_change: boolean;
    /** いずれかのカードを移動中 (掴めない)。 */
    busy: boolean;
    /** このカードを移動中。 */
    moving: boolean;
    /** メニューからステータスを変える。 */
    onChangeStatus: (todo: TodoRead, status: TodoStatus) => void;
};

export const TodoDraggableCard = ({ todo, tenant_code, can_change, busy, moving, onChangeStatus }: TodoDraggableCardProps) => {
    const can_drag = can_change && !busy;
    const { attributes, listeners, setNodeRef, setActivatorNodeRef, isDragging } = useDraggable({
        id: todo.id,
        data: boardCardDataOf(todo),
        disabled: !can_drag,
        attributes: { roleDescription: 'ドラッグできるカード' },
    });
    const [menu_anchor, setMenuAnchor] = useState<HTMLElement | null>(null);

    const handle = (
        <IconButton
            size="small"
            ref={setActivatorNodeRef}
            {...attributes}
            aria-label={can_change ? `「${todo.title}」を移動` : `「${todo.title}」は移動できません。${TODO_BOARD_LOCKED_TEXT}`}
            sx={{ cursor: can_drag ? 'grab' : 'not-allowed', mt: -0.25, ml: -0.75, touchAction: 'none' }}
            data-testid={`todo-board-handle-${todo.id}`}
            data-locked={!can_change}
        >
            {can_change ? <DragIndicatorIcon fontSize="small" aria-hidden /> : <LockOutlinedIcon fontSize="small" aria-hidden />}
        </IconButton>
    );

    return (
        <>
            <Box
                ref={setNodeRef}
                {...(can_drag ? listeners : {})}
                aria-busy={moving || undefined}
                sx={{ touchAction: 'manipulation', opacity: isDragging ? 0.4 : moving ? 0.7 : 1, outline: isDragging ? '2px dashed' : 'none', outlineColor: 'text.disabled', borderRadius: 1 }}
                data-testid={`todo-board-card-${todo.id}`}
                data-draggable={can_drag}
            >
                <TodoCard
                    todo={todo}
                    tenant_code={tenant_code}
                    compact
                    leading={can_change ? handle : <Tooltip title={TODO_BOARD_LOCKED_TEXT}>{handle}</Tooltip>}
                    actions={can_change && (
                        <IconButton
                            size="small"
                            aria-label={`「${todo.title}」のメニュー`}
                            aria-haspopup="dialog"
                            aria-expanded={menu_anchor !== null}
                            onClick={(event) => setMenuAnchor(event.currentTarget)}
                            sx={{ mt: -0.25, mr: -0.75 }}
                            data-testid={`todo-board-menu-${todo.id}`}
                        >
                            <MoreVertIcon fontSize="small" aria-hidden />
                        </IconButton>
                    )}
                />
            </Box>
            {/* メニューは、ドラッグの対象 (上の Box) の外に置く。Popover の中のポインタ操作がドラッグの開始にならないようにする */}
            <Popover
                open={menu_anchor !== null}
                anchorEl={menu_anchor}
                onClose={() => setMenuAnchor(null)}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                transformOrigin={{ vertical: 'top', horizontal: 'right' }}
                slotProps={{ paper: { 'aria-label': `「${todo.title}」のメニュー`, role: 'dialog' } }}
            >
                <Stack spacing={1} sx={{ p: 2 }} data-testid={`todo-board-menu-panel-${todo.id}`}>
                    <Typography variant="subtitle2" component="p">ステータスを変更</Typography>
                    <TodoStatusSelect
                        todo_id={todo.id}
                        title={todo.title}
                        status={todo.status}
                        disabled={busy}
                        onChange={(status) => {
                            setMenuAnchor(null);
                            onChangeStatus(todo, status);
                        }}
                    />
                </Stack>
            </Popover>
        </>
    );
};

export default TodoDraggableCard;
