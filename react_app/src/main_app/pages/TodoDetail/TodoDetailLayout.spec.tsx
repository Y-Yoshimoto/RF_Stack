// ToDo 詳細画面のレイアウトのテスト: 狭い幅 (モバイル) で横にはみ出さない (長いタイトル・URL・コメント本文・チェックリスト項目名・タブ・読み上げ用の領域)
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { page } from 'vitest/browser';
import { OTHER_USER_ID } from '@/main_app/testing/app_test_support';
import { renderTodoDetail } from '@/main_app/testing/todo_detail_support';
import { CHECKLIST_ITEM_ID, SECOND_CHECKLIST_ITEM_ID, checklistItemOf, checklistOf, commentOf, todoUserRefOf } from '@/main_app/testing/todo_test_data';

const MOBILE_WIDTH = 393;
const LONG_WORD = 'https://example.com/' + 'a'.repeat(200);

beforeEach(async () => {
    await page.viewport(MOBILE_WIDTH, 800);
});

afterEach(async () => {
    vi.restoreAllMocks();
    await page.viewport(1280, 720);
});

/**
 * 画面の右端 (表示幅) をはみ出している要素を探す関数 (原因の特定用に、テストの失敗メッセージに使う)
 * @returns {string[]} はみ出している要素 (data-testid・タグ・右端)
*/
const overflowingElements = (): string[] => {
    const limit = document.documentElement.clientWidth;
    return [...document.body.querySelectorAll('*')]
        .map((element) => ({ element, right: Math.round(element.getBoundingClientRect().right) }))
        .filter(({ right }) => right > limit + 1)
        .map(({ element, right }) => `${element.getAttribute('data-testid') ?? element.tagName.toLowerCase()}: ${right}`);
};

describe('ToDo 詳細画面: 狭い幅でも横にはみ出さない', () => {
    it('長いタイトル・URL・コメント本文・チェックリスト項目名があっても、ページの横幅が表示幅を超えない', async () => {
        renderTodoDetail({
            detail: { title: `長いタイトル ${LONG_WORD}`, description: LONG_WORD, creator: todoUserRefOf(OTHER_USER_ID, `Taro ${'Yamada'.repeat(20)}`), updater: todoUserRefOf(OTHER_USER_ID, `Jiro ${'Suzuki'.repeat(20)}`), comment_count: 12345, checklist: { done_count: 0, total_count: 2 } },
            checklist: checklistOf([
                checklistItemOf({ id: CHECKLIST_ITEM_ID, title: LONG_WORD }),
                checklistItemOf({ id: SECOND_CHECKLIST_ITEM_ID, title: '短い項目', position: 1 }),
            ]),
            comments: [commentOf({ body: `本文 ${LONG_WORD}`, author: { ...todoUserRefOf(OTHER_USER_ID, `Taro ${'Yamada'.repeat(20)}`), is_active: false }, edited_at: '2026-10-03T00:00:00Z' })],
        });
        await screen.findByTestId('todo-comments-list');
        await screen.findByTestId(`todo-checklist-item-${CHECKLIST_ITEM_ID}`);
        expect(document.documentElement.clientWidth).toBe(MOBILE_WIDTH);
        expect(overflowingElements()).toEqual([]);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(MOBILE_WIDTH);
    });

    it('読み上げ用の領域 (aria-live) に文があっても、横幅を広げない', async () => {
        const user = userEvent.setup();
        renderTodoDetail({ checklist: checklistOf([checklistItemOf({ id: CHECKLIST_ITEM_ID, title: LONG_WORD })]) });
        await user.click(await screen.findByTestId(`todo-checklist-item-${CHECKLIST_ITEM_ID}-check`));
        await vi.waitFor(() => expect(screen.getByTestId('todo-checklist-live')).toBeInTheDocument());
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(MOBILE_WIDTH);
        const live = screen.getByTestId('todo-checklist-live').getBoundingClientRect();
        expect(live.width).toBeLessThanOrEqual(1);
        expect(live.height).toBeLessThanOrEqual(1);
    });

    it('入力欄にフォーカスしても表示領域がずれず、投稿ボタンがクリックできる (入力欄に遮られない)', async () => {
        const user = userEvent.setup();
        renderTodoDetail({ comments: [commentOf({ body: LONG_WORD })] });
        const input = await screen.findByTestId('todo-comment-input');
        await user.click(input);
        await user.type(input, '本文');
        expect(window.scrollX).toBe(0);
        expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(MOBILE_WIDTH);
        const button = screen.getByTestId('todo-comment-submit');
        button.scrollIntoView({ block: 'center' });
        const rect = button.getBoundingClientRect();
        expect(document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)?.closest('[data-testid="todo-comment-submit"]')).toBe(button);
    });
});
