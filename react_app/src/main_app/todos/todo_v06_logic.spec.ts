// v0.6 の純粋関数のテスト (一覧の表示方法・カンバンの座標と読み上げ・チェックリストとコメントの事前の確認・要約のリンク・日付・アクティビティ)
import { describe, expect, it } from 'vitest';
import type { Active, ClientRect, KeyboardCoordinateGetter, Over } from '@dnd-kit/core';
import { TODO_LIMITS } from '@/main_app/api/contract';
import { buildTodoListUrl, buildTodoSummaryUrl } from '@/main_app/api/todos';
import { activityOf, checklistItemOf, checklistOf, commentOf, SECOND_CHECKLIST_ITEM_ID, summaryOf, todoOf } from '@/main_app/testing/todo_test_data';
import { todoActivityChecklistChangeOf } from './activity_payload';
import {
    adjacentBoardStatus,
    boardCardDataOf,
    boardColumnIdOf,
    boardCoordinatesInColumn,
    boardDropOf,
    boardKeyboardCoordinates,
    boardStatusOfColumnId,
    todoBoardAnnouncementsOf,
} from './board_dnd';
import {
    checklistAddGuardOf,
    checklistRenameGuardOf,
    checklistReorderGuardOf,
    checklistToggleGuardOf,
    moveChecklistItemIds,
    shiftChecklistItemIds,
} from './checklist_changes';
import { commentCreateGuardOf, commentRemoveGuardOf, commentUpdateGuardOf } from './comment_changes';
import { parseTodoListSearch, parseTodoListView, toTodoListSearch, withTodoListView } from './list_search';
import { TodoGuardError } from './todo_changes';
import { addDays, isDueSoon } from './todo_dates';
import { todoSummaryCountsOf, todoSummaryFiltersOf } from './todo_summary';

const LABELS = { open: '未着手', in_progress: '進行中', done: '完了' } as const;

describe('list_search の表示方法 (view)', () => {
    it('view=board だけを board として読み、それ以外は list', () => {
        expect(parseTodoListView('view=board')).toBe('board');
        expect(parseTodoListView('view=kanban')).toBe('list');
        expect(parseTodoListView('')).toBe('list');
    });

    it('withTodoListView は他のクエリを残し、list では view を消す', () => {
        const board = withTodoListView('board', 'scope=mine&status=open');
        expect(board.toString()).toBe('scope=mine&status=open&view=board');
        expect(withTodoListView('list', board).toString()).toBe('scope=mine&status=open');
    });

    it('view は絞り込みでも API のクエリでもない (toTodoListSearch は残し、parseTodoListSearch は無視する)', () => {
        expect(toTodoListSearch({ scope: 'assigned' }, 'view=board').toString()).toBe('view=board&scope=assigned');
        expect(parseTodoListSearch('view=board&scope=mine')).toEqual({ scope: 'mine' });
    });
});

describe('一覧と要約の URL', () => {
    it('include_total は true のときだけ末尾に付ける', () => {
        expect(buildTodoListUrl({ scope: 'mine', include_total: true })).toBe('/api/v1/todos?scope=mine&include_total=true');
        expect(buildTodoListUrl({ scope: 'mine', include_total: false })).toBe('/api/v1/todos?scope=mine');
    });

    it('要約は today と due_soon_days を付ける', () => {
        expect(buildTodoSummaryUrl({ today: '2026-10-29', due_soon_days: 7 })).toBe('/api/v1/todos/summary?today=2026-10-29&due_soon_days=7');
        expect(buildTodoSummaryUrl({})).toBe('/api/v1/todos/summary');
    });
});

describe('board_dnd', () => {
    const rect = (left: number, width = 300): ClientRect => ({ left, top: 100, width, height: 600, right: left + width, bottom: 700 });
    const droppable_rects = new Map([[boardColumnIdOf('open'), rect(0)], [boardColumnIdOf('in_progress'), rect(320)], [boardColumnIdOf('done'), rect(640)]]);
    const todo = todoOf({ status: 'open', title: '見積もり' });
    const activeOf = (data: unknown) => ({ data: { current: data } }) as unknown as Active;
    const overOf = (id: string) => ({ id }) as Over;

    /**
     * キーボードの coordinateGetter を呼ぶ関数
     * @param {string} code KeyboardEvent.code
     * @param {string | null} over_id カードが上にある列
     * @returns {ReturnType<KeyboardCoordinateGetter>} 座標
    */
    const press = (code: string, over_id: string | null) => {
        const context = { over: over_id === null ? null : overOf(over_id), active: activeOf(boardCardDataOf(todo)), droppableRects: droppable_rects, collisionRect: { width: 200 } };
        const args = { active: todo.id, currentCoordinates: { x: 0, y: 0 }, context } as unknown as Parameters<KeyboardCoordinateGetter>[1];
        return boardKeyboardCoordinates(new KeyboardEvent('keydown', { code }), args);
    };

    it('列の ID とステータスを相互に変換する', () => {
        expect(boardStatusOfColumnId(boardColumnIdOf('in_progress'))).toBe('in_progress');
        expect(boardStatusOfColumnId('todo-board-column:unknown')).toBeNull();
        expect(boardStatusOfColumnId(todo.id)).toBeNull();
        expect(adjacentBoardStatus('open', -1)).toBeNull();
        expect(adjacentBoardStatus('open', 1)).toBe('in_progress');
        expect(adjacentBoardStatus('done', 1)).toBeNull();
    });

    it('列の中央・上端の少し下にカードを置く座標を計算する', () => {
        expect(boardCoordinatesInColumn(rect(320), { width: 200 })).toEqual({ x: 370, y: 148 });
        expect(boardCoordinatesInColumn({ left: 0, top: 10, width: 100, height: 40 }, { width: 200 })).toEqual({ x: 0, y: 30 });
    });

    it('右矢印で隣の列へ、左矢印で戻る。端・上下の矢印では動かさない', () => {
        expect(press('ArrowRight', null)).toEqual({ x: 370, y: 148 });
        expect(press('ArrowRight', boardColumnIdOf('in_progress'))).toEqual({ x: 690, y: 148 });
        expect(press('ArrowLeft', boardColumnIdOf('in_progress'))).toEqual({ x: 50, y: 148 });
        expect(press('ArrowLeft', boardColumnIdOf('open'))).toBeUndefined();
        expect(press('ArrowRight', boardColumnIdOf('done'))).toBeUndefined();
        expect(press('ArrowDown', null)).toBeUndefined();
    });

    it('ドロップ先が別の列のときだけ移動にする', () => {
        const active = activeOf(boardCardDataOf(todo));
        expect(boardDropOf(active, overOf(boardColumnIdOf('done')))).toEqual({ todo, to_status: 'done' });
        expect(boardDropOf(active, overOf(boardColumnIdOf('open')))).toBeNull();
        expect(boardDropOf(active, null)).toBeNull();
        expect(boardDropOf(activeOf({ kind: 'other' }), overOf(boardColumnIdOf('done')))).toBeNull();
    });

    it('読み上げはカードのタイトルと列の表示名を使う', () => {
        const announcements = todoBoardAnnouncementsOf(LABELS);
        const active = activeOf(boardCardDataOf(todo));
        expect(announcements.onDragStart({ active })).toBe('「見積もり」を持ち上げました。今の列は「未着手」です。');
        expect(announcements.onDragOver({ active, over: overOf(boardColumnIdOf('done')) })).toBe('「見積もり」を「完了」の列の上に動かしました。');
        expect(announcements.onDragEnd({ active, over: overOf(boardColumnIdOf('done')) })).toBe('「見積もり」を「完了」の列に置きました。ステータスを変更します。');
        expect(announcements.onDragEnd({ active, over: null })).toBe('「見積もり」は「未着手」の列のままです。');
        expect(announcements.onDragCancel({ active, over: null })).toBe('移動を取り消しました。「見積もり」は「未着手」の列のままです。');
    });
});

describe('checklist_changes', () => {
    const second = checklistItemOf({ id: SECOND_CHECKLIST_ITEM_ID, title: '送付先を確認する', position: 1 });
    const checklist = checklistOf([checklistItemOf(), second]);
    const assignee = checklistOf([checklistItemOf(), second], { permissions: { can_edit: false, can_check: true } });
    const reasonOf = (error: unknown) => (error instanceof TodoGuardError ? `forbidden:${error.operation}` : (error as { reason?: string } | null)?.reason ?? null);

    it('担当者 (can_check だけ) は切り替えだけでき、編集は edit_checklist で弾く', () => {
        expect(checklistToggleGuardOf(assignee, checklistItemOf(), true)).toBeNull();
        expect(reasonOf(checklistAddGuardOf(assignee, '追加'))).toBe('forbidden:edit_checklist');
        expect(reasonOf(checklistRenameGuardOf(assignee, checklistItemOf(), '別名'))).toBe('forbidden:edit_checklist');
        const viewer = checklistOf([checklistItemOf()], { permissions: { can_edit: false, can_check: false } });
        expect(reasonOf(checklistToggleGuardOf(viewer, checklistItemOf(), true))).toBe('forbidden:check_checklist_item');
    });

    it('項目名は前後の空白を除いて 1〜200 文字。項目数は 100 まで。同じ値は変更なし', () => {
        expect(reasonOf(checklistAddGuardOf(checklist, '   '))).toBe('todo_checklist_title_invalid');
        expect(reasonOf(checklistAddGuardOf(checklist, 'x'.repeat(TODO_LIMITS.CHECKLIST_ITEM_TITLE_MAX + 1)))).toBe('todo_checklist_title_invalid');
        expect(checklistAddGuardOf(checklist, ` ${'x'.repeat(TODO_LIMITS.CHECKLIST_ITEM_TITLE_MAX)} `)).toBeNull();
        const full = checklistOf(Array.from({ length: TODO_LIMITS.CHECKLIST_ITEMS_MAX }, (_, index) => checklistItemOf({ id: `i${index}`, position: index })));
        expect(reasonOf(checklistAddGuardOf(full, '追加'))).toBe('todo_checklist_too_many_items');
        expect(reasonOf(checklistRenameGuardOf(checklist, checklistItemOf(), ' 見積書の雛形を探す '))).toBe('empty_changes');
        expect(reasonOf(checklistToggleGuardOf(checklist, checklistItemOf(), false))).toBe('empty_changes');
    });

    it('並べ替えは集合の一致・変更の有無・ETag を確かめる', () => {
        const ids = [checklistItemOf().id, second.id];
        expect(checklistReorderGuardOf(checklist, [...ids].reverse(), '"1"')).toBeNull();
        expect(reasonOf(checklistReorderGuardOf(checklist, ids, '"1"'))).toBe('empty_changes');
        expect(reasonOf(checklistReorderGuardOf(checklist, [ids[0]], '"1"'))).toBe('todo_checklist_order_mismatch');
        expect(reasonOf(checklistReorderGuardOf(checklist, [ids[0], ids[0]], '"1"'))).toBe('todo_checklist_order_mismatch');
        expect(reasonOf(checklistReorderGuardOf(checklist, [...ids].reverse(), null))).toBe('missing_etag');
    });

    it('moveChecklistItemIds / shiftChecklistItemIds で新しい並びを作る', () => {
        expect(moveChecklistItemIds(['a', 'b', 'c', 'd'], 'a', 'c')).toEqual(['b', 'c', 'a', 'd']);
        expect(moveChecklistItemIds(['a', 'b', 'c', 'd'], 'd', 'b')).toEqual(['a', 'd', 'b', 'c']);
        expect(moveChecklistItemIds(['a', 'b'], 'a', 'zzz')).toEqual(['a', 'b']);
        expect(shiftChecklistItemIds(['a', 'b', 'c'], 'b', -1)).toEqual(['b', 'a', 'c']);
        expect(shiftChecklistItemIds(['a', 'b', 'c'], 'b', 1)).toEqual(['a', 'c', 'b']);
        expect(shiftChecklistItemIds(['a', 'b', 'c'], 'a', -1)).toBeNull();
        expect(shiftChecklistItemIds(['a', 'b', 'c'], 'c', 1)).toBeNull();
    });
});

describe('comment_changes', () => {
    const reasonOf = (error: unknown) => (error instanceof TodoGuardError ? `forbidden:${error.operation}` : (error as { reason?: string } | null)?.reason ?? null);

    it('投稿は can_comment と本文 (空白だけ・4,000 文字超えは不可) を確かめる', () => {
        expect(commentCreateGuardOf('ok', true)).toBeNull();
        expect(commentCreateGuardOf('ok', undefined)).toBeNull();
        expect(reasonOf(commentCreateGuardOf('ok', false))).toBe('write_not_allowed');
        expect(reasonOf(commentCreateGuardOf(' \n ', true))).toBe('todo_comment_body_invalid');
        expect(reasonOf(commentCreateGuardOf('x'.repeat(TODO_LIMITS.COMMENT_BODY_MAX + 1), true))).toBe('todo_comment_body_invalid');
    });

    it('編集・削除はコメントの permissions で弾く。同じ本文は変更なし', () => {
        const others = commentOf({ permissions: { can_edit: false, can_delete: true } });
        expect(reasonOf(commentUpdateGuardOf(others, '別の本文'))).toBe('forbidden:edit_comment');
        expect(commentRemoveGuardOf(others)).toBeNull();
        expect(reasonOf(commentRemoveGuardOf(commentOf({ permissions: { can_edit: false, can_delete: false } })))).toBe('forbidden:delete_comment');
        expect(reasonOf(commentUpdateGuardOf(commentOf(), '確認しました'))).toBe('empty_changes');
    });
});

describe('要約と日付', () => {
    it('addDays は月末・年末をまたぐ', () => {
        expect(addDays('2026-10-29', 7)).toBe('2026-11-05');
        expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
        expect(addDays('2028-03-01', -1)).toBe('2028-02-29');
    });

    it('isDueSoon は today〜until (両端を含む) の未完了', () => {
        expect(isDueSoon('2026-10-29', 'open', '2026-10-29', '2026-11-05')).toBe(true);
        expect(isDueSoon('2026-11-05', 'in_progress', '2026-10-29', '2026-11-05')).toBe(true);
        expect(isDueSoon('2026-11-06', 'open', '2026-10-29', '2026-11-05')).toBe(false);
        expect(isDueSoon('2026-10-30', 'done', '2026-10-29', '2026-11-05')).toBe(false);
        expect(isDueSoon(null, 'open', '2026-10-29', '2026-11-05')).toBe(false);
    });

    it('要約のカードの件数と、絞り込み済みの一覧のリンク', () => {
        const summary = summaryOf();
        expect(todoSummaryCountsOf(summary)).toEqual({ assigned_unfinished: 4, assigned_overdue: 1, assigned_due_soon: 2, created_unfinished: 2 });
        const filters = todoSummaryFiltersOf(summary);
        expect(toTodoListSearch(filters.assigned_overdue).toString()).toBe('scope=assigned&status=open%2Cin_progress&due_before=2026-10-28&sort=due_date');
        expect(toTodoListSearch(filters.assigned_due_soon).toString()).toBe('scope=assigned&status=open%2Cin_progress&due_before=2026-11-05&due_after=2026-10-29&sort=due_date');
        expect(toTodoListSearch(filters.created_unfinished).toString()).toBe('scope=mine&status=open%2Cin_progress');
    });
});

describe('checklist_changed のアクティビティ', () => {
    it('op・項目・名前の変更前後を取り出す。形が合わなければ null', () => {
        const renamed = activityOf({ action: 'checklist_changed', payload: { op: 'renamed', item_id: 'i1', title: '新', before: '旧', after: '新' } });
        expect(todoActivityChecklistChangeOf(renamed)).toEqual({ op: 'renamed', item_id: 'i1', title: '新', before: '旧', after: '新' });
        const checked = activityOf({ action: 'checklist_changed', payload: { op: 'checked', item_id: 'i1', title: '新' } });
        expect(todoActivityChecklistChangeOf(checked)).toEqual({ op: 'checked', item_id: 'i1', title: '新', before: null, after: null });
        expect(todoActivityChecklistChangeOf(activityOf({ action: 'checklist_changed', payload: { op: 'moved' } }))).toBeNull();
        expect(todoActivityChecklistChangeOf(activityOf({ action: 'updated', payload: { op: 'checked' } }))).toBeNull();
    });
});
