// 詳細画面の表示用の純粋関数のテスト (下書きの形・重なった項目の案内・件数の上書き・チェックリストの表示)
import { describe, expect, it } from 'vitest';
import { checklistItemOf, checklistOf, todoDetailOf, todoUserRefOf } from '@/main_app/testing/todo_test_data';
import { rebaseDraft } from '@/main_app/todos/rebase_draft';
import { checklistAnnouncementsOf, checklistDoneTextOf, checklistMovedTextOf, checklistPercentOf, checklistProgressTextOf, orderChecklistItems } from './checklist_view';
import { shownChecklistProgress, shownCommentCount, withChecklistProgress, withCommentDelta } from './detail_counts';
import { ASSIGNEES_EQUALS, assigneesDraftOf, audienceDraftOf, conflictLabelsOf, fieldsDraftOf, refreshedNoticeTextOf } from './detail_drafts';
import { todoUserTextOf } from './todo_user_text';

describe('todoUserTextOf', () => {
    it('無効なユーザーには「(無効)」を添える', () => {
        expect(todoUserTextOf(todoUserRefOf('u1', 'Taro'))).toBe('Taro');
        expect(todoUserTextOf({ ...todoUserRefOf('u1', 'Taro'), is_active: false })).toBe('Taro (無効)');
    });
});

describe('下書きの形と案内', () => {
    it('詳細からフォームごとの値を作る (期限なしは空文字)', () => {
        const todo = todoDetailOf({ due_date: null, description: null });
        expect(fieldsDraftOf(todo)).toEqual({ title: '見積もりを作る', description: '', due_date: '', priority: 'medium' });
        expect(audienceDraftOf(todo).visibility).toBe('organization');
        expect(assigneesDraftOf(todo).assignee_ids).toHaveLength(1);
    });

    it('担当者は順序を問わず集合で比べる (並びだけが変わっても重ならない)', () => {
        const base = { assignee_ids: ['a', 'b'] };
        const draft = { assignee_ids: ['b', 'a', 'c'] };
        const next = { assignee_ids: ['b', 'a'] };
        expect(rebaseDraft(base, draft, next, ASSIGNEES_EQUALS)).toEqual({ draft, conflicts: [] });
    });

    it('重なった項目は画面に出す名前にし、重複を除く', () => {
        expect(conflictLabelsOf(['title', 'assignee_ids', 'title', 'organization_ids'])).toEqual(['タイトル', '担当者', '公開先の組織']);
        expect(conflictLabelsOf(['unknown'])).toEqual(['unknown']);
    });

    it('案内文は、重なった項目があるときだけ「◯◯は他の人も変更しています」を入れる', () => {
        expect(refreshedNoticeTextOf([])).toBe('他のユーザーが更新したため最新の内容を表示しました。確認してもう一度保存してください');
        expect(refreshedNoticeTextOf(['タイトル', '説明'])).toBe('他のユーザーが更新したため最新の内容を表示しました。タイトル、説明は他の人も変更しています。確認してもう一度保存してください');
    });
});

describe('件数の上書き', () => {
    it('コメント数は上書きしたときの詳細の値と同じ間だけ使い、詳細が変われば詳細の値にする。0 未満にはしない', () => {
        const added = withCommentDelta(2, null, 1);
        expect(shownCommentCount(2, added)).toBe(3);
        expect(shownCommentCount(3, added)).toBe(3);
        expect(shownCommentCount(5, added)).toBe(5);
        expect(withCommentDelta(2, added, -1).value).toBe(2);
        expect(withCommentDelta(0, null, -1).value).toBe(0);
        expect(shownCommentCount(1, null)).toBe(1);
    });

    it('チェックリストの進捗も、詳細の値が変わったら詳細の値にする', () => {
        const server = { done_count: 0, total_count: 2 };
        const override = withChecklistProgress(server, { done_count: 1, total_count: 2 });
        expect(shownChecklistProgress(server, override)).toEqual({ done_count: 1, total_count: 2 });
        expect(shownChecklistProgress({ done_count: 2, total_count: 3 }, override)).toEqual({ done_count: 2, total_count: 3 });
        expect(shownChecklistProgress(server, null)).toEqual(server);
    });
});

describe('チェックリストの表示', () => {
    const a = checklistItemOf({ id: 'a', title: 'A' });
    const b = checklistItemOf({ id: 'b', title: 'B' });

    it('進捗の割合と文', () => {
        expect(checklistPercentOf(1, 3)).toBe(33);
        expect(checklistPercentOf(0, 0)).toBe(0);
        expect(checklistProgressTextOf(1, 3)).toBe('1 / 3 完了');
    });

    it('並べ替えの結果を待つ間は移した後の並びで出す。食い違う並びは使わない', () => {
        expect(orderChecklistItems([a, b], ['b', 'a']).map((item) => item.id)).toEqual(['b', 'a']);
        expect(orderChecklistItems([a, b], null).map((item) => item.id)).toEqual(['a', 'b']);
        expect(orderChecklistItems([a, b], ['b', 'x']).map((item) => item.id)).toEqual(['a', 'b']);
        expect(orderChecklistItems([a, b], ['a']).map((item) => item.id)).toEqual(['a', 'b']);
    });

    it('完了した人と日時の文は、完了した項目だけに出す', () => {
        expect(checklistDoneTextOf(a)).toBeNull();
        expect(checklistDoneTextOf(checklistItemOf({ is_done: true, done_at: '2026-10-03T00:00:00Z', done_by: { ...todoUserRefOf('u1', 'Taro'), is_active: false } }))).toBe('Taro (無効) が 2026/10/03 9:00 に完了');
        expect(checklistDoneTextOf(checklistItemOf({ is_done: true, done_at: '2026-10-03T00:00:00Z' }))).toBe('2026/10/03 9:00 に完了');
    });

    it('並べ替えの読み上げ文', () => {
        expect(checklistMovedTextOf('A', 1, 3)).toBe('「A」を 2 番目に移動しました (全 3 件)');
        const announcements = checklistAnnouncementsOf(checklistOf([a, b]).items);
        // 読み上げ文は id だけを使うため、dnd-kit の Active / Over の残りの項目は省く
        const active = { id: 'a' } as never;
        const over = { id: 'b' } as never;
        expect(announcements.onDragStart?.({ active })).toBe('「A」を持ち上げました。現在 1 番目です (全 2 件)');
        expect(announcements.onDragOver?.({ active, over })).toBe('「A」を 2 番目の位置に移動しています');
        expect(announcements.onDragEnd?.({ active, over })).toBe('「A」を 2 番目に置きました');
        expect(announcements.onDragEnd?.({ active, over: null })).toBe('「A」を元の位置に戻しました');
        expect(announcements.onDragCancel?.({ active, over: null })).toBe('並べ替えを取り消しました。「A」は元の位置です');
    });
});
