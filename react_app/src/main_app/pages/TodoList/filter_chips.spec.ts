// 適用中の条件 (チップ) の純粋関数のテスト
import { describe, expect, it } from 'vitest';
import { activeFilterChipsOf, filterCountOf, withoutStatusOf } from './filter_chips';

const LOOKUPS = {
    assigneeNameOf: (id: string) => (id === 'u1' ? 'Taro Yamada' : undefined),
    organizationNameOf: (id: string) => (id === 'o1' ? '営業部' : undefined),
};

describe('activeFilterChipsOf', () => {
    it('条件が無ければ空 (表示範囲と並び順は条件に含めない)', () => {
        expect(activeFilterChipsOf({ scope: 'mine', sort: 'due_date' }, 'list', LOOKUPS)).toEqual([]);
    });

    it('条件ごとにチップを作り、1 つ外した絞り込みを持たせる', () => {
        const filter = { scope: 'assigned' as const, q: '見積', status: ['open' as const, 'done' as const], priority: ['high' as const], assignee_id: 'u1', organization_id: 'o9', due_after: '2026-11-01', due_before: '2026-11-30' };
        const chips = activeFilterChipsOf(filter, 'list', LOOKUPS);
        expect(chips.map((chip) => [chip.id, chip.label])).toEqual([
            ['q', 'タイトル: 「見積」'],
            ['status-open', 'ステータス: 未着手'],
            ['status-done', 'ステータス: 完了'],
            ['priority-high', '優先度: 高'],
            ['assignee', '担当者: Taro Yamada'],
            ['organization', '公開先: (不明な組織)'],
            ['due-after', '期限: 2026-11-01 以降'],
            ['due-before', '期限: 2026-11-30 以前'],
        ]);
        expect(chips[1].without.status).toEqual(['done']);
        expect(chips[1].without.q).toBe('見積');
        expect(chips[0].without.q).toBeUndefined();
        expect(chips[0].without.scope).toBe('assigned');
    });

    it('ボードではステータスの条件を出さない', () => {
        const chips = activeFilterChipsOf({ status: ['open'], priority: ['low'] }, 'board', LOOKUPS);
        expect(chips.map((chip) => chip.id)).toEqual(['priority-low']);
    });

    it('適用数は検索語を数えない', () => {
        const chips = activeFilterChipsOf({ q: 'a', status: ['open', 'done'], priority: ['low'] }, 'list', LOOKUPS);
        expect(chips).toHaveLength(4);
        expect(filterCountOf(chips)).toBe(3);
    });
});

describe('withoutStatusOf', () => {
    it('ステータスだけを除く', () => {
        expect(withoutStatusOf({ scope: 'mine', status: ['open'], priority: ['low'] })).toEqual({ scope: 'mine', priority: ['low'] });
    });
});
