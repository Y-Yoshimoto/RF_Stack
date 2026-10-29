/**
 * @desc ToDo のチェックリスト (進捗・完了の切り替え・名前のその場編集・削除・並べ替え・末尾の追加欄。AP-CHK)
 * - 完了のチェックは permissions.can_check、名前の編集・削除・並べ替え・追加は permissions.can_edit のときだけ操作できる (担当者はチェックのみ)
 * - 並べ替えは、ドラッグ & ドロップ (マウス・タッチ・キーボード) とメニューの「上へ移動」「下へ移動」。結果を待つ間は移した後の並びを先に出す
 * - 412 などで失敗したら、フックが最新を取り直す。取り直せたら「最新を表示しました」と知らせる (failure_refreshed)
 * - 変更に成功したら onChanged で進捗を通知する (詳細の ToDo の checklist は自動では変わらないため)
 * - 操作の結果は、画面に見えない aria-live の領域で読み上げる
 */
import { useState } from 'react';
import { Box, LinearProgress, Typography } from '@mui/material';
import type { DragEndEvent } from '@dnd-kit/core';
import type { TodoChecklistItemRead, TodoChecklistProgress } from '@/main_app/api/contract';
import { isChecklistFull, moveChecklistItemIds, shiftChecklistItemIds } from '@/main_app/todos/checklist_changes';
import { useTodoChecklist } from '@/main_app/todos/useTodoChecklist';
import { VISUALLY_HIDDEN } from '@/shared/components/visually_hidden';
import { checklistMovedTextOf, checklistPercentOf, checklistProgressTextOf, orderChecklistItems } from './checklist_view';
import { TodoChecklistAddForm } from './TodoChecklistAddForm';
import { TodoChecklistList } from './TodoChecklistList';
import { TodoChecklistNotices } from './TodoChecklistNotices';

export type TodoChecklistProps = {
    todo_id: string;
    /** チェックリストを変更できたときに呼ばれる (詳細の進捗表示の更新に使う)。 */
    onChanged: (progress: TodoChecklistProgress) => void;
};

export const TodoChecklist = ({ todo_id, onChanged }: TodoChecklistProps) => {
    const checklist = useTodoChecklist(todo_id, { onChanged: (value) => onChanged({ done_count: value.done_count, total_count: value.total_count }) });
    const [pending_order, setPendingOrder] = useState<string[] | null>(null);
    const [spoken, setSpoken] = useState('');
    const { checklist: value, permissions, pending } = checklist;
    const items = value === null ? [] : orderChecklistItems(value.items, pending_order);
    const can_edit = permissions?.can_edit ?? false;
    const can_check = permissions?.can_check ?? false;
    const busy = pending !== null;

    const reorder = async (item_ids: string[], moved: TodoChecklistItemRead) => {
        setPendingOrder(item_ids);
        const result = await checklist.reorder(item_ids);
        setPendingOrder(null);
        if (result.ok) setSpoken(checklistMovedTextOf(moved.title, item_ids.indexOf(moved.id), item_ids.length));
    };

    const onDragEnd = (event: DragEndEvent) => {
        const { active, over } = event;
        if (busy || !over || active.id === over.id) return;
        const moved = items.find((item) => item.id === active.id);
        if (moved) void reorder(moveChecklistItemIds(items.map((entry) => entry.id), moved.id, String(over.id)), moved);
    };

    const move = async (item: TodoChecklistItemRead, delta: -1 | 1) => {
        if (busy) return;
        const next = shiftChecklistItemIds(items.map((entry) => entry.id), item.id, delta);
        if (next !== null) await reorder(next, item);
    };

    const toggle = async (item: TodoChecklistItemRead) => {
        if (busy) return;
        const result = await checklist.toggle(item);
        if (result.ok) setSpoken(`「${item.title}」を${item.is_done ? '未完了に戻しました' : '完了にしました'}`);
    };

    const rename = async (item: TodoChecklistItemRead, title: string): Promise<boolean> => {
        if (busy) return false;
        const result = await checklist.rename(item, title);
        if (result.ok) setSpoken(`項目名を「${title.trim()}」に変更しました`);
        return result.ok;
    };

    const remove = async (item: TodoChecklistItemRead) => {
        if (busy) return;
        const result = await checklist.remove(item);
        if (result.ok) setSpoken(`「${item.title}」を削除しました`);
    };

    const add = async (title: string): Promise<boolean> => {
        const result = await checklist.add(title);
        if (result.ok) setSpoken(`「${title.trim()}」を追加しました`);
        return result.ok;
    };

    return (
        <Box data-testid="todo-checklist" aria-busy={busy || checklist.is_refreshing}>
            <TodoChecklistNotices checklist={checklist} />
            {checklist.status === 'success' && value !== null && (
                <>
                    <Box sx={{ mb: 1 }}>
                        <Typography variant="body2" color="text.secondary" data-testid="todo-checklist-progress-text">{checklistProgressTextOf(value.done_count, value.total_count)}</Typography>
                        <LinearProgress
                            variant="determinate"
                            value={checklistPercentOf(value.done_count, value.total_count)}
                            aria-label="チェックリストの進捗"
                            aria-valuetext={checklistProgressTextOf(value.done_count, value.total_count)}
                            sx={{ height: 8, borderRadius: 4, mt: 0.5 }}
                            data-testid="todo-checklist-progress"
                        />
                    </Box>
                    {!can_edit && <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }} data-testid="todo-checklist-readonly">{can_check ? '項目の追加・名前の変更・削除・並べ替えができるのは、作成者とテナント管理者だけです。完了のチェックはできます。' : '項目を操作できるのは、作成者・担当者・テナント管理者です。'}</Typography>}
                    <TodoChecklistList
                        items={items}
                        can_edit={can_edit}
                        can_check={can_check}
                        busy={busy}
                        renaming={pending === 'rename'}
                        onDragEnd={onDragEnd}
                        onToggle={(target) => void toggle(target)}
                        onRename={rename}
                        onRemove={(target) => void remove(target)}
                        onMove={move}
                    />
                    {can_edit && <TodoChecklistAddForm is_full={isChecklistFull(value)} pending={pending === 'add'} onAdd={add} />}
                </>
            )}
            <Box role="status" aria-live="polite" sx={VISUALLY_HIDDEN} data-testid="todo-checklist-live">{spoken}</Box>
        </Box>
    );
};

export default TodoChecklist;
