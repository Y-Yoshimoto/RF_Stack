// useAsyncValue のテスト
import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useAsyncValue } from './useAsyncValue';

describe('useAsyncValue', () => {
    it('loading → success', async () => {
        const { result } = renderHook(() => useAsyncValue(() => Promise.resolve(42), 'k'));
        expect(result.current.result).toEqual({ status: 'loading' });
        await waitFor(() => expect(result.current.result).toEqual({ status: 'success', value: 42 }));
    });

    it('失敗は error として保持する', async () => {
        const error = new Error('boom');
        const { result } = renderHook(() => useAsyncValue(() => Promise.reject(error), 'k'));
        await waitFor(() => expect(result.current.result).toEqual({ status: 'error', error }));
    });

    it('key が変わると loading に戻って再実行する', async () => {
        const load = vi.fn((key: string) => Promise.resolve(key));
        const { result, rerender } = renderHook(({ key }) => useAsyncValue(() => load(key), key), { initialProps: { key: 'a' } });
        await waitFor(() => expect(result.current.result).toEqual({ status: 'success', value: 'a' }));
        rerender({ key: 'b' });
        expect(result.current.result).toEqual({ status: 'loading' });
        await waitFor(() => expect(result.current.result).toEqual({ status: 'success', value: 'b' }));
    });

    it('reload で再実行する', async () => {
        let count = 0;
        const { result } = renderHook(() => useAsyncValue(() => Promise.resolve(++count), 'k'));
        await waitFor(() => expect(result.current.result).toEqual({ status: 'success', value: 1 }));
        act(() => result.current.reload());
        await waitFor(() => expect(result.current.result).toEqual({ status: 'success', value: 2 }));
    });

    it('古い実行の結果は捨てる', async () => {
        let resolveFirst: (value: string) => void = () => { };
        const first = new Promise<string>((resolve) => { resolveFirst = resolve; });
        const { result, rerender } = renderHook(({ key }) => useAsyncValue(() => (key === 'a' ? first : Promise.resolve('b')), key), { initialProps: { key: 'a' } });
        rerender({ key: 'b' });
        await waitFor(() => expect(result.current.result).toEqual({ status: 'success', value: 'b' }));
        await act(async () => resolveFirst('a'));
        expect(result.current.result).toEqual({ status: 'success', value: 'b' });
    });
});
