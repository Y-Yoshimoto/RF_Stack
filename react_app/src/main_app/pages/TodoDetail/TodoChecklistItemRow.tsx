/**
 * @desc チェックリストの 1 項目 (並べ替えできる行)
 * - 完了のチェックは can_check のとき、名前の編集・削除・並べ替え (ドラッグハンドルとメニュー) は can_edit のときだけ操作できる
 * - ドラッグ & ドロップは @dnd-kit/sortable。キーボードにはハンドルの操作とメニューの「上へ移動」「下へ移動」を用意する
 * - 実行中の操作があるときは、コントロールを無効にせず (フォーカスが外れるため) 操作を受け付けないだけにする
 */
import { useEffect, useRef, useState } from 'react';
import { Box, Checkbox, IconButton, Typography } from '@mui/material';
import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import EditIcon from '@mui/icons-material/Edit';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { TodoChecklistItemRead } from '@/main_app/api/contract';
import { checklistDoneTextOf } from './checklist_view';
import { TodoChecklistItemEditor } from './TodoChecklistItemEditor';
import { TodoChecklistItemMenu } from './TodoChecklistItemMenu';

export type TodoChecklistItemRowProps = {
    item: TodoChecklistItemRead;
    /** 表示中の位置 (0 から) と項目数。 */
    index: number;
    count: number;
    can_edit: boolean;
    can_check: boolean;
    /** 別の操作を実行中 (操作を受け付けない)。 */
    busy: boolean;
    /** 名前の保存の実行中 (この項目)。 */
    renaming: boolean;
    onToggle: (item: TodoChecklistItemRead) => void;
    onRename: (item: TodoChecklistItemRead, title: string) => Promise<boolean>;
    onRemove: (item: TodoChecklistItemRead) => void;
    /** 上下に 1 つ動かす。 */
    onMove: (item: TodoChecklistItemRead, delta: -1 | 1) => Promise<void>;
};

export const TodoChecklistItemRow = ({ item, index, count, can_edit, can_check, busy, renaming, onToggle, onRename, onRemove, onMove }: TodoChecklistItemRowProps) => {
    const [editing, setEditing] = useState(false);
    const edit_button_ref = useRef<HTMLButtonElement | null>(null);
    const menu_button_ref = useRef<HTMLButtonElement | null>(null);
    const restore_focus = useRef(false);
    const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id: item.id, disabled: !can_edit || busy });
    const done_text = checklistDoneTextOf(item);
    // data-testid は型に無い属性のため、リテラルを直接渡さない
    const check_input_props = { 'aria-label': item.title, 'data-testid': `todo-checklist-item-${item.id}-check` };

    // 編集を終えたら、編集ボタンへフォーカスを戻す
    useEffect(() => {
        if (!editing && restore_focus.current) {
            restore_focus.current = false;
            edit_button_ref.current?.focus();
        }
    }, [editing]);

    const closeEditor = () => {
        restore_focus.current = true;
        setEditing(false);
    };

    const move = async (delta: -1 | 1) => {
        await onMove(item, delta);
        menu_button_ref.current?.focus();
    };

    return (
        <Box
            component="li"
            ref={setNodeRef}
            style={{ transform: CSS.Transform.toString(transform ? { ...transform, x: 0, scaleX: 1, scaleY: 1 } : null), transition }}
            sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5, py: 0.5, borderBottom: 1, borderColor: 'divider', bgcolor: isDragging ? 'action.hover' : 'transparent', position: 'relative', zIndex: isDragging ? 1 : 0 }}
            data-testid={`todo-checklist-item-${item.id}`}
            data-done={item.is_done}
        >
            {can_edit && (
                <IconButton
                    ref={setActivatorNodeRef}
                    size="small"
                    {...attributes}
                    {...listeners}
                    aria-label={`「${item.title}」をドラッグして並べ替え`}
                    sx={{ cursor: 'grab', touchAction: 'none', mt: 0.25 }}
                    data-testid={`todo-checklist-item-${item.id}-handle`}
                >
                    <DragIndicatorIcon fontSize="small" />
                </IconButton>
            )}
            <Checkbox
                checked={item.is_done}
                disabled={!can_check}
                onChange={() => {
                    if (!busy) onToggle(item);
                }}
                slotProps={{ input: check_input_props }}
                sx={{ py: 0.5 }}
            />
            {editing ? (
                <TodoChecklistItemEditor item_id={item.id} title={item.title} pending={renaming} onSave={(title) => onRename(item, title)} onClose={closeEditor} />
            ) : (
                <Box sx={{ flex: 1, minWidth: 0, py: 0.75 }}>
                    <Typography variant="body1" sx={{ overflowWrap: 'anywhere', textDecoration: item.is_done ? 'line-through' : 'none', color: item.is_done ? 'text.secondary' : 'text.primary' }} data-testid={`todo-checklist-item-${item.id}-title`}>{item.title}</Typography>
                    {done_text && <Typography variant="caption" color="text.secondary" data-testid={`todo-checklist-item-${item.id}-done-text`}>{done_text}</Typography>}
                </Box>
            )}
            {can_edit && !editing && (
                <>
                    <IconButton ref={edit_button_ref} size="small" aria-label={`「${item.title}」の名前を変更`} onClick={() => setEditing(true)} sx={{ mt: 0.25 }} data-testid={`todo-checklist-item-${item.id}-edit`}>
                        <EditIcon fontSize="small" />
                    </IconButton>
                    <TodoChecklistItemMenu
                        ref={menu_button_ref}
                        item_id={item.id}
                        title={item.title}
                        is_first={index === 0}
                        is_last={index === count - 1}
                        onMove={(delta) => void move(delta)}
                        onRemove={() => onRemove(item)}
                    />
                </>
            )}
        </Box>
    );
};

export default TodoChecklistItemRow;
