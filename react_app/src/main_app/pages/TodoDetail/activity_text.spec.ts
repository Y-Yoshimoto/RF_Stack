// アクティビティの文のテスト
import { describe, expect, it } from 'vitest';
import { activityOf } from '@/main_app/testing/todo_test_data';
import { activityLinesOf } from './activity_text';

const LOOKUPS = { user: (id: string) => `user:${id}`, organization: (id: string) => `org:${id}` };

describe('activityLinesOf', () => {
    it('項目の変更は「項目: 前 → 後」にし、説明は内容を出さずに変更とだけ示す', () => {
        const lines = activityLinesOf(activityOf({ action: 'updated', payload: { changes: { title: { before: 'a', after: 'b' }, description: { before: 'x', after: 'y' }, due_date: { before: null, after: '2026-11-01' }, priority: { before: 'low', after: 'high' } } } }), LOOKUPS);
        expect(lines).toEqual(['タイトル: a → b', '説明を変更しました', '期限: なし → 2026-11-01', '優先度: 低 → 高']);
    });

    it('担当者・公開先組織の追加と削除を、名前に引き直して示す', () => {
        expect(activityLinesOf(activityOf({ action: 'assignees_changed', payload: { added: ['u1'], removed: ['u2'] } }), LOOKUPS)).toEqual(['担当者を追加: user:u1', '担当者を削除: user:u2']);
        expect(activityLinesOf(activityOf({ action: 'visibility_changed', payload: { organization_ids: { added: ['o1'], removed: ['o2'] } } }), LOOKUPS)).toEqual(['公開先の組織を追加: org:o1', '公開先の組織を削除: org:o2']);
    });

    it('削除はタイトルを添える。payload が読み取れなければ種別の説明だけにする', () => {
        expect(activityLinesOf(activityOf({ action: 'deleted', payload: { title: '見積もり' } }), LOOKUPS)).toEqual(['ToDo「見積もり」を削除しました']);
        expect(activityLinesOf(activityOf({ action: 'status_changed', payload: {} }), LOOKUPS)).toEqual(['ステータスを変更しました']);
        expect(activityLinesOf(activityOf({ action: 'assignees_changed', payload: { added: 1 } }), LOOKUPS)).toEqual(['担当者を変更しました']);
    });
});
