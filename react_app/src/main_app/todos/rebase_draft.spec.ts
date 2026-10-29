// rebaseDraft (純粋関数) と useRebasedDraft のテスト (触っていない項目は新しい値・触った項目は入力を残す・衝突の検出・集合の比較)
import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { rebaseDraft, sameDraft, type DraftEquals } from './rebase_draft';
import { sameIdSet } from './todo_changes';
import { useRebasedDraft } from './useRebasedDraft';

type Form = { title: string; due_date: string | null; assignee_ids: readonly string[] };

const EQUALS: DraftEquals<Form> = { assignee_ids: sameIdSet };
const base: Form = { title: '見積もり', due_date: '2026-11-01', assignee_ids: ['u1', 'u2'] };

describe('rebaseDraft', () => {
    it('触っていない項目は next の値にし、触った項目は入力を残す', () => {
        const draft: Form = { ...base, title: '見積もり (改)' };
        const next: Form = { ...base, due_date: '2026-12-01' };
        expect(rebaseDraft(base, draft, next, EQUALS)).toEqual({ draft: { ...next, title: '見積もり (改)' }, conflicts: [] });
    });

    it('自分も他の人も同じ項目を違う値に変えたら衝突として知らせ、入力を残す', () => {
        const draft: Form = { ...base, title: 'A' };
        const next: Form = { ...base, title: 'B' };
        expect(rebaseDraft(base, draft, next, EQUALS)).toEqual({ draft: { ...next, title: 'A' }, conflicts: ['title'] });
    });

    it('同じ値に変えていれば衝突にしない (保存した値が戻ってきた場合)', () => {
        const draft: Form = { ...base, title: 'A' };
        expect(rebaseDraft(base, draft, { ...base, title: 'A' }, EQUALS)).toEqual({ draft: { ...base, title: 'A' }, conflicts: [] });
    });

    it('配列の項目は equals で集合として比べる (並びが違うだけなら触っていない)', () => {
        const draft: Form = { ...base, assignee_ids: ['u2', 'u1'] };
        const next: Form = { ...base, assignee_ids: ['u3'] };
        expect(rebaseDraft(base, draft, next, EQUALS)).toEqual({ draft: next, conflicts: [] });
        // equals を渡さないと参照の比較になり、並べ替えただけでも触った扱いになる
        expect(rebaseDraft(base, draft, next).conflicts).toEqual(['assignee_ids']);
    });

    it('sameDraft は項目ごとの比較で等しさを判定する', () => {
        expect(sameDraft(base, { ...base, assignee_ids: ['u2', 'u1'] }, EQUALS)).toBe(true);
        expect(sameDraft(base, { ...base, due_date: null }, EQUALS)).toBe(false);
    });
});

describe('useRebasedDraft', () => {
    it('server が変わると入力を残して載せ替え、衝突を知らせる。入力し直すと衝突は消える', () => {
        const { result, rerender } = renderHook(({ server }: { server: Form | null }) => useRebasedDraft(server, EQUALS), { initialProps: { server: null as Form | null } });
        expect(result.current.draft).toBeNull();
        rerender({ server: base });
        expect(result.current.draft).toEqual(base);
        expect(result.current.is_dirty).toBe(false);

        act(() => result.current.setField('title', 'A'));
        expect(result.current.dirty_fields).toEqual(['title']);

        // 別のフォームの保存 (期限) と、他の人のタイトルの変更が届く
        rerender({ server: { ...base, title: 'B', due_date: '2026-12-01' } });
        expect(result.current.draft).toEqual({ ...base, title: 'A', due_date: '2026-12-01' });
        expect(result.current.conflicts).toEqual(['title']);

        act(() => result.current.setField('title', 'C'));
        expect(result.current.conflicts).toEqual([]);
    });

    it('同じ値の server を作り直しても載せ替えない (毎回新しいオブジェクトでよい)', () => {
        const { result, rerender } = renderHook(({ server }: { server: Form }) => useRebasedDraft(server, EQUALS), { initialProps: { server: base } });
        act(() => result.current.setField('title', 'A'));
        rerender({ server: { ...base, assignee_ids: ['u2', 'u1'] } });
        expect(result.current.draft?.title).toBe('A');
        expect(result.current.base).toBe(base);
    });

    it('保存した値が server に反映されると dirty が消える。reset で入力を捨てる', () => {
        const { result, rerender } = renderHook(({ server }: { server: Form }) => useRebasedDraft(server, EQUALS), { initialProps: { server: base } });
        act(() => result.current.setField('title', 'A'));
        rerender({ server: { ...base, title: 'A' } });
        expect(result.current.is_dirty).toBe(false);

        act(() => result.current.setField('due_date', null));
        act(() => result.current.reset());
        expect(result.current.draft).toEqual({ ...base, title: 'A' });
    });
});
