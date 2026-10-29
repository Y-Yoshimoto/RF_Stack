// useVersionedResource のテスト (refresh は loading に戻さず取り直す・applyUpdate の破棄・失敗時は表示を保つ)
import { describe, expect, it } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { classifyApiError } from '@/shared/api/errors';
import type { WithEtag } from '@/shared/api/etag';
import { useVersionedResource } from './useVersionedResource';

type Doc = { id: string; title: string; version: number };

/**
 * 取得のたびに次の値を返す load を作る関数
 * @param {Array<WithEtag<Doc> | Error>} values 取得結果 (順に返す。最後の値を繰り返す)
 * @returns {{ load: () => Promise<WithEtag<Doc>>, calls: () => number }} load と呼び出し回数
*/
const sequence = (values: (WithEtag<Doc> | Error)[]) => {
    let count = 0;
    const load = () => {
        const value = values[Math.min(count, values.length - 1)];
        count += 1;
        return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
    };
    return { load, calls: () => count };
};

const docOf = (version: number, title = `v${version}`): WithEtag<Doc> => ({ body: { id: 'a', title, version }, etag: `"${version}"` });
const replace = (_current: WithEtag<Doc>, update: WithEtag<Doc>) => update;

describe('useVersionedResource.refresh', () => {
    it('表示を保ったまま取り直す (status は loading にならず、is_refreshing が立つ)', async () => {
        let resolveSecond: (value: WithEtag<Doc>) => void = () => { };
        const second = new Promise<WithEtag<Doc>>((resolve) => { resolveSecond = resolve; });
        let count = 0;
        const load = () => (++count === 1 ? Promise.resolve(docOf(1)) : second);
        const { result } = renderHook(() => useVersionedResource<Doc, WithEtag<Doc>>({ key: 'k', load, merge: replace, classify: classifyApiError }));
        await waitFor(() => expect(result.current.status).toBe('success'));

        let refreshed: Promise<boolean> = Promise.resolve(false);
        act(() => {
            refreshed = result.current.refresh();
        });
        expect(result.current.status).toBe('success');
        expect(result.current.is_refreshing).toBe(true);
        expect(result.current.value?.version).toBe(1);

        await act(async () => resolveSecond(docOf(2)));
        await expect(refreshed).resolves.toBe(true);
        expect(result.current.status).toBe('success');
        expect(result.current.is_refreshing).toBe(false);
        expect(result.current.value?.version).toBe(2);
        expect(result.current.etag).toBe('"2"');
    });

    it('取り直した値は、それまでの applyUpdate の結果より優先する。取り直した後の applyUpdate は重ねる', async () => {
        const { load } = sequence([docOf(1), docOf(5)]);
        const { result } = renderHook(() => useVersionedResource<Doc, WithEtag<Doc>>({ key: 'k', load, merge: replace, classify: classifyApiError }));
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => result.current.applyUpdate(docOf(2)));
        expect(result.current.value?.version).toBe(2);

        await act(async () => {
            await result.current.refresh();
        });
        expect(result.current.value?.version).toBe(5);

        act(() => result.current.applyUpdate(docOf(6)));
        expect(result.current.value?.version).toBe(6);
    });

    it('失敗したら false を返し、表示はそのまま (refresh_error に分類を入れる)', async () => {
        const { load } = sequence([docOf(1), new Error('boom')]);
        const { result } = renderHook(() => useVersionedResource<Doc, WithEtag<Doc>>({ key: 'k', load, merge: replace, classify: classifyApiError }));
        await waitFor(() => expect(result.current.status).toBe('success'));
        let ok = true;
        await act(async () => {
            ok = await result.current.refresh();
        });
        expect(ok).toBe(false);
        expect(result.current.status).toBe('success');
        expect(result.current.value?.version).toBe(1);
        expect(result.current.refresh_error?.kind).toBe('unknown');
    });

    it('取得前に呼ぶと reload と同じく取り直し、false を返す', async () => {
        const { load, calls } = sequence([new Error('boom'), docOf(1)]);
        const { result } = renderHook(() => useVersionedResource<Doc, WithEtag<Doc>>({ key: 'k', load, merge: replace, classify: classifyApiError }));
        await waitFor(() => expect(result.current.status).toBe('error'));
        let ok = true;
        await act(async () => {
            ok = await result.current.refresh();
        });
        expect(ok).toBe(false);
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(calls()).toBe(2);
    });

    it('reload は従来どおり loading に戻る', async () => {
        const { load } = sequence([docOf(1), docOf(2)]);
        const { result } = renderHook(() => useVersionedResource<Doc, WithEtag<Doc>>({ key: 'k', load, merge: replace, classify: classifyApiError }));
        await waitFor(() => expect(result.current.status).toBe('success'));
        act(() => result.current.reload());
        expect(result.current.status).toBe('loading');
        await waitFor(() => expect(result.current.value?.version).toBe(2));
    });
});
