// テスト用: 狭い幅でページ全体が横にはみ出していないことを確かめる補助 (アプリのコードからは import しない)
// モバイルではページが横にはみ出すと表示領域そのものが広がり、固定位置の UI (メニューの背面など) がずれる。
import { page } from 'vitest/browser';

/** モバイル (Pixel 5 相当) の幅と高さ */
export const MOBILE_VIEWPORT = { width: 393, height: 851 } as const;

/**
 * ビューポートをモバイルの幅にする関数
*/
export const useMobileViewport = async (): Promise<void> => {
    await page.viewport(MOBILE_VIEWPORT.width, MOBILE_VIEWPORT.height);
};

/**
 * ビューポートを既定 (vitest.config.js の browser.viewport) に戻す関数
*/
export const resetViewport = async (): Promise<void> => {
    await page.viewport(1280, 720);
};

/**
 * position: absolute / fixed の要素のうち、ビューポートの右端を越え、かつ横スクロールのコンテナの外へはみ出しているものを返す関数
 * デスクトップの Chrome ではページの scrollWidth に現れなくても、モバイルでは表示領域そのものが広がる (Pixel 5 の実機エミュレーションで確認済み)。
 * 位置の基準 (offsetParent) から祖先をたどり、overflow が visible でないコンテナ (スクロール・クリップ) に収まっていなければ、はみ出しとみなす。
 * @param {number} viewport_width ビューポートの幅
 * @returns {string[]} はみ出している要素の説明
*/
const escapedAbsoluteElementsOf = (viewport_width: number): string[] => {
    const escaped: string[] = [];
    for (const element of document.body.querySelectorAll<HTMLElement>('*')) {
        const position = getComputedStyle(element).position;
        if ((position !== 'absolute' && position !== 'fixed') || element.getBoundingClientRect().right <= viewport_width + 1) continue;
        if (position === 'fixed') continue;
        let container: HTMLElement | null = element.offsetParent as HTMLElement | null;
        let contained = false;
        while (container !== null && container !== document.body) {
            if (getComputedStyle(container).overflowX !== 'visible') {
                contained = true;
                break;
            }
            container = container.parentElement;
        }
        if (!contained) escaped.push(`${element.tagName.toLowerCase()}[${element.getAttribute('data-testid') ?? ''}] "${(element.textContent ?? '').slice(0, 20)}" right=${Math.round(element.getBoundingClientRect().right)}`);
    }
    return escaped;
};

/**
 * ページ全体の横幅がビューポートを超えていないことを返す関数 (ページの scrollWidth と、はみ出した絶対配置の要素の両方を見る)
 * @returns {{ ok: boolean; scroll_width: number; viewport_width: number; escaped: string[] }} 結果 (ok が false ならはみ出している)
*/
export const pageOverflowOf = (): { ok: boolean; scroll_width: number; viewport_width: number; escaped: string[] } => {
    const viewport_width = document.documentElement.clientWidth;
    const scroll_width = document.documentElement.scrollWidth;
    const escaped = escapedAbsoluteElementsOf(viewport_width);
    return { ok: scroll_width <= viewport_width && escaped.length === 0, scroll_width, viewport_width, escaped };
};
