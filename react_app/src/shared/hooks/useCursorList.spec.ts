// useCursorList のテスト (insertItem と total の増減・続きのページがあるときの末尾への差し込み)
import { describe, expect, it } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { classifyApiError } from '@/shared/api/errors';
import { useCursorList, type CursorPage } from './useCursorList';

type Item = { id: string; label?: string };

/**
 * cursor ごとのページを返す fetchPage を作る関数
 * @param {Record<string, CursorPage<Item>>} pages cursor (先頭は '') → ページ
 * @returns {(cursor: string | null) => Promise<CursorPage<Item>>} fetchPage
*/
const pagesOf = (pages: Record<string, CursorPage<Item>>) => (cursor: string | null) => Promise.resolve(pages[cursor ?? '']);

const idsOf = (items: Item[]) => items.map((item) => item.id);

/**
 * 一覧を描画して先頭ページを待つ関数
 * @param {Record<string, CursorPage<Item>>} pages ページ
 * @returns {Promise<ReturnType<typeof renderHook>>} 描画結果
*/
const renderList = async (pages: Record<string, CursorPage<Item>>) => {
    const fetchPage = pagesOf(pages);
    const rendered = renderHook(() => useCursorList<Item>({ query_key: 'k', fetchPage, classify: classifyApiError }));
    await waitFor(() => expect(rendered.result.current.status).toBe('success'));
    return rendered;
};

describe('useCursorList.insertItem', () => {
    it('先頭・位置・末尾に差し込み、total を 1 ずつ増やす', async () => {
        const { result } = await renderList({ '': { items: [{ id: 'a' }, { id: 'b' }], next_cursor: null, total: 2 } });
        act(() => result.current.insertItem({ id: 's' }, 'start'));
        expect(idsOf(result.current.items)).toEqual(['s', 'a', 'b']);
        act(() => result.current.insertItem({ id: 'm' }, 2));
        expect(idsOf(result.current.items)).toEqual(['s', 'a', 'm', 'b']);
        act(() => result.current.insertItem({ id: 'e' }, 'end'));
        expect(idsOf(result.current.items)).toEqual(['s', 'a', 'm', 'b', 'e']);
        expect(result.current.total).toBe(5);
    });

    it('同じ ID の要素は移し、total は変えない。範囲外の位置は端に寄せる', async () => {
        const { result } = await renderList({ '': { items: [{ id: 'a' }, { id: 'b' }, { id: 'c' }], next_cursor: null, total: 3 } });
        act(() => result.current.insertItem({ id: 'c', label: 'moved' }, 0));
        expect(idsOf(result.current.items)).toEqual(['c', 'a', 'b']);
        expect(result.current.items[0].label).toBe('moved');
        act(() => result.current.insertItem({ id: 'x' }, 99));
        expect(idsOf(result.current.items)).toEqual(['c', 'a', 'b', 'x']);
        expect(result.current.total).toBe(4);
    });

    it('removeItem は total を 1 減らす。無い ID では変えない。total が null なら null のまま', async () => {
        const { result } = await renderList({ '': { items: [{ id: 'a' }, { id: 'b' }], next_cursor: null, total: 2 } });
        act(() => result.current.removeItem('a'));
        act(() => result.current.removeItem('zzz'));
        expect(idsOf(result.current.items)).toEqual(['b']);
        expect(result.current.total).toBe(1);

        const other = await renderList({ '': { items: [{ id: 'a' }], next_cursor: null } });
        act(() => other.result.current.insertItem({ id: 'b' }, 'end'));
        act(() => other.result.current.removeItem('a'));
        expect(other.result.current.total).toBeNull();
    });

    it('続きのページがあるときの末尾の差し込みは仮に後ろへ置き、最後のページまで読むと末尾に並ぶ (重複しない)', async () => {
        const { result } = await renderList({
            '': { items: [{ id: 'a' }], next_cursor: 'c1' },
            c1: { items: [{ id: 'b' }], next_cursor: 'c2' },
            c2: { items: [{ id: 'c' }, { id: 'new' }], next_cursor: null },
        });
        act(() => result.current.insertItem({ id: 'new', label: 'local' }, 'end'));
        expect(idsOf(result.current.items)).toEqual(['a', 'new']);

        act(() => result.current.loadMore());
        await waitFor(() => expect(idsOf(result.current.items)).toEqual(['a', 'b', 'new']));
        act(() => result.current.loadMore());
        await waitFor(() => expect(result.current.has_more).toBe(false));
        expect(idsOf(result.current.items)).toEqual(['a', 'b', 'c', 'new']);
    });

    it('replaceItem は仮に後ろへ置いた要素も置き換える', async () => {
        const { result } = await renderList({ '': { items: [{ id: 'a' }], next_cursor: 'c1' } });
        act(() => result.current.insertItem({ id: 'new' }, 'end'));
        act(() => result.current.replaceItem({ id: 'new', label: 'edited' }));
        expect(result.current.items[1].label).toBe('edited');
    });

    it('取得の失敗時は何もしない', async () => {
        const { result } = renderHook(() => useCursorList<Item>({ query_key: 'k', fetchPage: () => Promise.reject(new Error('x')), classify: classifyApiError }));
        await waitFor(() => expect(result.current.status).toBe('error'));
        act(() => result.current.insertItem({ id: 'a' }, 'start'));
        expect(result.current.items).toEqual([]);
    });
});
