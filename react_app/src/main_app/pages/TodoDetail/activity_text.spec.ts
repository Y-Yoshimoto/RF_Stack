// アクティビティの文のテスト
import { describe, expect, it } from 'vitest';
import { activityOf } from '@/main_app/testing/todo_test_data';
import { activityLinesOf } from './activity_text';

const USERS = {
    u1: { display_name: 'Taro Yamada', is_active: true },
    u2: { display_name: 'Jiro Suzuki', is_active: false },
};
const LOOKUPS = { users: USERS, organization: (id: string) => `org:${id}` };

describe('activityLinesOf', () => {
    it('項目の変更は「項目: 前 → 後」にし、説明は内容を出さずに変更とだけ示す', () => {
        const lines = activityLinesOf(activityOf({ action: 'updated', payload: { changes: { title: { before: 'a', after: 'b' }, description: { before: 'x', after: 'y' }, due_date: { before: null, after: '2026-11-01' }, priority: { before: 'low', after: 'high' } } } }), LOOKUPS);
        expect(lines).toEqual(['タイトル: a → b', '説明を変更しました', '期限: なし → 2026-11-01', '優先度: 低 → 高']);
    });

    it('担当者・公開先組織の追加と削除を、名前に引き直して示す', () => {
        expect(activityLinesOf(activityOf({ action: 'assignees_changed', payload: { added: ['u1'], removed: ['u2'] } }), LOOKUPS)).toEqual(['担当者を追加: Taro Yamada', '担当者を削除: Jiro Suzuki (無効)']);
        expect(activityLinesOf(activityOf({ action: 'visibility_changed', payload: { organization_ids: { added: ['o1'], removed: ['o2'] } } }), LOOKUPS)).toEqual(['公開先の組織を追加: org:o1', '公開先の組織を削除: org:o2']);
    });

    it('名前を引けない担当者は「不明なユーザー」にする。作成時の担当者も名前で示す', () => {
        expect(activityLinesOf(activityOf({ action: 'assignees_changed', payload: { added: ['u9'], removed: [] } }), LOOKUPS)).toEqual(['担当者を追加: 不明なユーザー']);
        expect(activityLinesOf(activityOf({ action: 'created', payload: { values: { assignee_ids: ['u1', 'u2'] } } }), LOOKUPS)).toEqual(['ToDo を作成しました', '担当者: Taro Yamada、Jiro Suzuki (無効)']);
    });

    it('削除はタイトルを添える。payload が読み取れなければ種別の説明だけにする', () => {
        expect(activityLinesOf(activityOf({ action: 'deleted', payload: { title: '見積もり' } }), LOOKUPS)).toEqual(['ToDo「見積もり」を削除しました']);
        expect(activityLinesOf(activityOf({ action: 'status_changed', payload: {} }), LOOKUPS)).toEqual(['ステータスを変更しました']);
        expect(activityLinesOf(activityOf({ action: 'assignees_changed', payload: { added: 1 } }), LOOKUPS)).toEqual(['担当者を変更しました']);
    });

    it('チェックリストの変更 (追加・名前変更・削除・完了・未完了) を文にする', () => {
        const lineOf = (payload: Record<string, unknown>) => activityLinesOf(activityOf({ action: 'checklist_changed', payload }), LOOKUPS);
        expect(lineOf({ op: 'added', item_id: 'i1', title: '雛形を探す' })).toEqual(['チェックリストに「雛形を探す」を追加しました']);
        expect(lineOf({ op: 'renamed', item_id: 'i1', title: '雛形を確認する', before: '雛形を探す', after: '雛形を確認する' })).toEqual(['チェックリストの項目名を変更: 「雛形を探す」 → 「雛形を確認する」']);
        expect(lineOf({ op: 'removed', item_id: 'i1', title: '雛形を探す' })).toEqual(['チェックリストから「雛形を探す」を削除しました']);
        expect(lineOf({ op: 'checked', item_id: 'i1', title: '雛形を探す' })).toEqual(['チェックリストの「雛形を探す」を完了にしました']);
        expect(lineOf({ op: 'unchecked', item_id: 'i1', title: '雛形を探す' })).toEqual(['チェックリストの「雛形を探す」を未完了に戻しました']);
    });

    it('チェックリストの変更の項目名が無ければ「項目」、op が読み取れなければ種別の説明だけにする', () => {
        const lineOf = (payload: Record<string, unknown>) => activityLinesOf(activityOf({ action: 'checklist_changed', payload }), LOOKUPS);
        expect(lineOf({ op: 'checked' })).toEqual(['チェックリストの「項目」を完了にしました']);
        expect(lineOf({ op: 'moved' })).toEqual(['チェックリストを変更しました']);
        expect(lineOf({})).toEqual(['チェックリストを変更しました']);
    });
});
