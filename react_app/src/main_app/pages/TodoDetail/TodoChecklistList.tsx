/**
 * @desc チェックリストの項目の並び (ドラッグ & ドロップで並べ替えられる。マウス・タッチ・キーボード)
 * 項目が無ければ空の案内を出す。読み上げ文は日本語 (checklist_view.ts)。
 */
import { Box, Typography } from '@mui/material';
import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from '@dnd-kit/sortable';
import type { TodoChecklistItemRead } from '@/main_app/api/contract';
import { CHECKLIST_DRAG_INSTRUCTIONS, checklistAnnouncementsOf } from './checklist_view';
import { TodoChecklistItemRow } from './TodoChecklistItemRow';

export type TodoChecklistListProps = {
    /** 表示する並び。 */
    items: readonly TodoChecklistItemRead[];
    can_edit: boolean;
    can_check: boolean;
    /** 実行中の操作がある。 */
    busy: boolean;
    /** 名前の保存の実行中。 */
    renaming: boolean;
    onDragEnd: (event: DragEndEvent) => void;
    onToggle: (item: TodoChecklistItemRead) => void;
    onRename: (item: TodoChecklistItemRead, title: string) => Promise<boolean>;
    onRemove: (item: TodoChecklistItemRead) => void;
    onMove: (item: TodoChecklistItemRead, delta: -1 | 1) => Promise<void>;
};

export const TodoChecklistList = ({ items, can_edit, can_check, busy, renaming, onDragEnd, onToggle, onRename, onRemove, onMove }: TodoChecklistListProps) => {
    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
    if (items.length === 0) {
        return <Typography variant="body2" color="text.secondary" data-testid="todo-checklist-empty">{can_edit ? '項目はまだありません。下の欄から追加できます。' : '項目はありません。'}</Typography>;
    }
    return (
        <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={onDragEnd}
            accessibility={{ announcements: checklistAnnouncementsOf(items), screenReaderInstructions: { draggable: CHECKLIST_DRAG_INSTRUCTIONS } }}
        >
            <SortableContext items={items.map((item) => item.id)} strategy={verticalListSortingStrategy}>
                <Box component="ul" aria-label="チェックリスト" sx={{ listStyle: 'none', m: 0, p: 0, opacity: busy ? 0.7 : 1 }} data-testid="todo-checklist-items">
                    {items.map((item, index) => (
                        <TodoChecklistItemRow
                            key={item.id}
                            item={item}
                            index={index}
                            count={items.length}
                            can_edit={can_edit}
                            can_check={can_check}
                            busy={busy}
                            renaming={renaming}
                            onToggle={onToggle}
                            onRename={onRename}
                            onRemove={onRemove}
                            onMove={onMove}
                        />
                    ))}
                </Box>
            </SortableContext>
        </DndContext>
    );
};

export default TodoChecklistList;
