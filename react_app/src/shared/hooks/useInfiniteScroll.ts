/**
 * @description:
 * 無限スクロール (一覧の末尾の番兵要素が見えたら続きを読み込む) のカスタムフック (プレーン共通。AP-UX-02)
 * - 戻り値はコールバック ref。一覧の末尾に置いた要素 (ListFooter など) の ref に渡す
 * - IntersectionObserver で番兵要素が画面 (rootMargin 分だけ手前) に入ったら onLoadMore を呼ぶ
 * - enabled が false の間は監視しない。enabled に戻るたびに監視し直すため、読み込んだ後も番兵要素が見えたままなら続けて読み込む
 *   (useCursorList と組み合わせる場合は `enabled: has_more && !is_loading_more && load_more_error === null` にする)
 * - IntersectionObserver が無い環境では何もしない (「さらに読み込む」の操作を残すこと)
*/
import { useEffect, useRef, useState, type RefCallback } from 'react';

/** 既定の rootMargin (番兵要素が画面に入る 200px 手前で読み込みを始める) */
export const INFINITE_SCROLL_ROOT_MARGIN = '200px';

export type UseInfiniteScrollParams = {
    /** 監視するか (続きがあり、読み込み中・失敗中でないとき true)。 */
    enabled: boolean;
    /** 番兵要素が見えたときに呼ばれる (最新の関数を呼ぶ。参照が変わっても監視し直さない)。 */
    onLoadMore: () => void;
    /** IntersectionObserver の rootMargin (省略時は 200px)。 */
    root_margin?: string;
};

/**
 * 無限スクロールのカスタムフック
 * @param {UseInfiniteScrollParams} params 監視の有無・読み込み関数・rootMargin
 * @returns {RefCallback<Element>} 番兵要素に渡すコールバック ref
*/
export const useInfiniteScroll = ({ enabled, onLoadMore, root_margin = INFINITE_SCROLL_ROOT_MARGIN }: UseInfiniteScrollParams): RefCallback<Element> => {
    const [node, setNode] = useState<Element | null>(null);
    const on_load_more = useRef(onLoadMore);
    useEffect(() => {
        on_load_more.current = onLoadMore;
    });

    useEffect(() => {
        if (!enabled || node === null || typeof IntersectionObserver === 'undefined') return;
        const observer = new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting)) on_load_more.current();
        }, { rootMargin: root_margin });
        observer.observe(node);
        return () => observer.disconnect();
    }, [enabled, node, root_margin]);

    return setNode;
};

export default useInfiniteScroll;
