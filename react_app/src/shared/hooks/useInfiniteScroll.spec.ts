// useInfiniteScroll のテスト (IntersectionObserver をモックし、番兵要素が見えたら読み込む・enabled の間だけ監視する)
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { INFINITE_SCROLL_ROOT_MARGIN, useInfiniteScroll } from './useInfiniteScroll';

/** 生成された IntersectionObserver のモック */
type ObserverMock = {
    callback: IntersectionObserverCallback;
    options: IntersectionObserverInit | undefined;
    observed: Element[];
    disconnected: boolean;
    /** 見え方を変える (コールバックを呼ぶ) */
    fire: (is_intersecting: boolean) => void;
};

let observers: ObserverMock[] = [];

beforeEach(() => {
    observers = [];
    class MockIntersectionObserver {
        readonly mock: ObserverMock;

        constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
            const mock: ObserverMock = {
                callback,
                options,
                observed: [],
                disconnected: false,
                fire: (is_intersecting) => callback(mock.observed.map((target) => ({ target, isIntersecting: is_intersecting }) as IntersectionObserverEntry), this as unknown as IntersectionObserver),
            };
            this.mock = mock;
            observers.push(mock);
        }

        observe(target: Element) {
            this.mock.observed.push(target);
        }

        disconnect() {
            this.mock.disconnected = true;
        }

        unobserve() { }

        takeRecords() {
            return [];
        }
    }
    vi.stubGlobal('IntersectionObserver', MockIntersectionObserver);
});

afterEach(() => {
    vi.unstubAllGlobals();
});

const active = () => observers.filter((observer) => !observer.disconnected);

describe('useInfiniteScroll', () => {
    it('番兵要素が見えたら onLoadMore を呼ぶ (rootMargin は既定 200px)', () => {
        const onLoadMore = vi.fn();
        const { result } = renderHook(() => useInfiniteScroll({ enabled: true, onLoadMore }));
        const sentinel = document.createElement('div');
        act(() => result.current(sentinel));
        expect(active()).toHaveLength(1);
        expect(active()[0].observed).toEqual([sentinel]);
        expect(active()[0].options?.rootMargin).toBe(INFINITE_SCROLL_ROOT_MARGIN);

        act(() => active()[0].fire(false));
        expect(onLoadMore).not.toHaveBeenCalled();
        act(() => active()[0].fire(true));
        expect(onLoadMore).toHaveBeenCalledTimes(1);
    });

    it('enabled が false の間は監視しない。true に戻ると監視し直す (見えたままなら続けて読み込める)', () => {
        const onLoadMore = vi.fn();
        const { result, rerender } = renderHook(({ enabled }) => useInfiniteScroll({ enabled, onLoadMore }), { initialProps: { enabled: false } });
        act(() => result.current(document.createElement('div')));
        expect(active()).toHaveLength(0);

        rerender({ enabled: true });
        expect(active()).toHaveLength(1);
        rerender({ enabled: false });
        expect(active()).toHaveLength(0);
        rerender({ enabled: true });
        expect(observers).toHaveLength(2);
        expect(active()).toHaveLength(1);
    });

    it('番兵要素が外れると監視をやめ、onLoadMore の参照が変わっても監視し直さずに最新を呼ぶ', () => {
        const first = vi.fn();
        const second = vi.fn();
        const { result, rerender } = renderHook(({ onLoadMore }) => useInfiniteScroll({ enabled: true, onLoadMore }), { initialProps: { onLoadMore: first } });
        act(() => result.current(document.createElement('div')));
        rerender({ onLoadMore: second });
        expect(observers).toHaveLength(1);
        act(() => active()[0].fire(true));
        expect(first).not.toHaveBeenCalled();
        expect(second).toHaveBeenCalledTimes(1);

        act(() => result.current(null));
        expect(active()).toHaveLength(0);
    });

    it('アンマウントで監視をやめる', () => {
        const { result, unmount } = renderHook(() => useInfiniteScroll({ enabled: true, onLoadMore: vi.fn() }));
        act(() => result.current(document.createElement('div')));
        unmount();
        expect(active()).toHaveLength(0);
    });
});
