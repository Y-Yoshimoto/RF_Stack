// ToDo 詳細のチェックリストのテスト (権限の出し分け・完了の切り替え・追加・名前変更・並べ替え (メニュー)・削除・上限・412 の自動の取り直し。AP-CHK)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { calledRequests, problemReply, type mockFetch as MockFetch } from '@/shared/testing/fetch_mock';
import { CHECKLIST_KEY, checklistReply, renderTodoDetail } from '@/main_app/testing/todo_detail_support';
import { CHECKLIST_ITEM_ID, SECOND_CHECKLIST_ITEM_ID, TODO_ID, checklistItemOf, checklistOf, todoUserRefOf } from '@/main_app/testing/todo_test_data';

const ITEMS_PATH = `/api/v1/todos/${TODO_ID}/checklist/items`;
const ORDER_KEY = `PUT /api/v1/todos/${TODO_ID}/checklist/order`;
const itemKey = (method: string, id: string) => `${method} ${ITEMS_PATH}/${id}`;

afterEach(() => {
    vi.restoreAllMocks();
});

const FIRST = checklistItemOf({ id: CHECKLIST_ITEM_ID, title: '見積書の雛形を探す', position: 0 });
const SECOND = checklistItemOf({ id: SECOND_CHECKLIST_ITEM_ID, title: '金額を確認する', position: 1, version: 2 });
const lastRequest = (spy: ReturnType<typeof MockFetch>, method: string) => calledRequests(spy).filter((request) => request.method === method).at(-1);

describe('チェックリスト: 権限の出し分け', () => {
    it('作成者・tenant_admin (編集可・チェック可) には、チェック・ドラッグハンドル・名前変更・メニュー・追加欄を出す', async () => {
        renderTodoDetail({ checklist: checklistOf([FIRST, SECOND]) });
        expect(await screen.findByTestId(`todo-checklist-item-${FIRST.id}`)).toBeInTheDocument();
        expect(screen.getByTestId(`todo-checklist-item-${FIRST.id}-check`)).toBeEnabled();
        expect(screen.getByTestId(`todo-checklist-item-${FIRST.id}-handle`)).toBeInTheDocument();
        expect(screen.getByTestId(`todo-checklist-item-${FIRST.id}-edit`)).toBeInTheDocument();
        expect(screen.getByTestId(`todo-checklist-item-${FIRST.id}-menu-button`)).toBeInTheDocument();
        expect(screen.getByTestId('todo-checklist-add-input')).toBeEnabled();
        expect(screen.queryByTestId('todo-checklist-readonly')).toBeNull();
    });

    it('担当者 (チェックのみ可) には、チェックだけを操作できるようにし、名前変更・削除・並べ替え・追加欄を出さない', async () => {
        renderTodoDetail({ checklist: checklistOf([FIRST, SECOND], { permissions: { can_edit: false, can_check: true } }) });
        expect(await screen.findByTestId(`todo-checklist-item-${FIRST.id}`)).toBeInTheDocument();
        expect(screen.getByTestId(`todo-checklist-item-${FIRST.id}-check`)).toBeEnabled();
        expect(screen.queryByTestId(`todo-checklist-item-${FIRST.id}-handle`)).toBeNull();
        expect(screen.queryByTestId(`todo-checklist-item-${FIRST.id}-edit`)).toBeNull();
        expect(screen.queryByTestId(`todo-checklist-item-${FIRST.id}-menu-button`)).toBeNull();
        expect(screen.queryByTestId('todo-checklist-add-form')).toBeNull();
        expect(screen.getByTestId('todo-checklist-readonly')).toHaveTextContent('完了のチェックはできます');
    });

    it('閲覧のみ (編集不可・チェック不可) には、チェックも無効にして理由を示す', async () => {
        renderTodoDetail({ checklist: checklistOf([FIRST], { permissions: { can_edit: false, can_check: false } }) });
        expect(await screen.findByTestId(`todo-checklist-item-${FIRST.id}-check`)).toBeDisabled();
        expect(screen.getByTestId('todo-checklist-readonly')).toBeInTheDocument();
        expect(screen.queryByTestId('todo-checklist-add-form')).toBeNull();
    });

    it('項目が無ければ空の案内を出す (編集できる人には追加を案内する)', async () => {
        renderTodoDetail();
        expect(await screen.findByTestId('todo-checklist-empty')).toHaveTextContent('下の欄から追加できます');
    });
});

describe('チェックリスト: 完了の切り替えと進捗', () => {
    it('チェックすると項目の版を If-Match に付けて is_done だけを送り、進捗 (バーと詳細の表示) を更新する', async () => {
        const user = userEvent.setup();
        const done = checklistItemOf({ ...FIRST, is_done: true, done_at: '2026-10-03T00:00:00Z', done_by: todoUserRefOf(), version: 2 });
        const spy = renderTodoDetail({
            detail: { checklist: { done_count: 0, total_count: 2 } },
            checklist: checklistOf([FIRST, SECOND]),
            replies: { [itemKey('PATCH', FIRST.id)]: checklistReply(checklistOf([done, SECOND], { version: 1 })) },
        });
        expect(await screen.findByTestId('todo-checklist-progress-text')).toHaveTextContent('0 / 2 完了');
        expect(screen.getByTestId('todo-detail-checklist-progress')).toHaveTextContent('チェックリスト 0 / 2');
        await user.click(screen.getByTestId(`todo-checklist-item-${FIRST.id}-check`));
        await vi.waitFor(() => expect(screen.getByTestId('todo-checklist-progress-text')).toHaveTextContent('1 / 2 完了'));
        const request = lastRequest(spy, 'PATCH');
        expect(request?.headers.get('If-Match')).toBe('"1"');
        expect(await request?.json()).toEqual({ is_done: true });
        expect(screen.getByTestId('todo-detail-checklist-progress')).toHaveTextContent('チェックリスト 1 / 2');
        expect(screen.getByTestId(`todo-checklist-item-${FIRST.id}-done-text`)).toHaveTextContent('Hanako Suzuki が');
        expect(screen.getByTestId('todo-checklist-progress')).toHaveAttribute('aria-valuenow', '50');
        expect(screen.getByTestId('todo-checklist-live')).toHaveTextContent('「見積書の雛形を探す」を完了にしました');
    });
});

describe('チェックリスト: 追加', () => {
    it('Enter で追加して入力を空にし、続けて入力できるようフォーカスを保つ', async () => {
        const user = userEvent.setup();
        const added = checklistItemOf({ id: 'new-item', title: '新しい項目', position: 1 });
        const spy = renderTodoDetail({
            checklist: checklistOf([FIRST]),
            replies: { [`POST ${ITEMS_PATH}`]: checklistReply(checklistOf([FIRST, added], { version: 2 }), 201) },
        });
        const input = await screen.findByTestId('todo-checklist-add-input');
        await user.type(input, '新しい項目{Enter}');
        expect(await screen.findByTestId('todo-checklist-item-new-item')).toBeInTheDocument();
        expect(await lastRequest(spy, 'POST')?.json()).toEqual({ title: '新しい項目' });
        expect(input).toHaveValue('');
        expect(input).toHaveFocus();
    });

    it('空白だけ・200 文字超えは追加できない', async () => {
        const user = userEvent.setup();
        renderTodoDetail({ checklist: checklistOf([FIRST]) });
        const input = await screen.findByTestId('todo-checklist-add-input');
        expect(screen.getByTestId('todo-checklist-add-submit')).toBeDisabled();
        await user.type(input, '   ');
        expect(screen.getByTestId('todo-checklist-add-submit')).toBeDisabled();
        await user.clear(input);
        await user.click(input);
        await user.paste('a'.repeat(201));
        expect(screen.getByTestId('todo-checklist-add-submit')).toBeDisabled();
        expect(screen.getByText('項目名は 200 文字以内で入力してください。')).toBeInTheDocument();
    });

    it('項目が上限 (100) に達したら、追加欄を無効にして理由を示す', async () => {
        const items = Array.from({ length: 100 }, (_, index) => checklistItemOf({ id: `item-${index}`, title: `項目 ${index}`, position: index }));
        renderTodoDetail({ checklist: checklistOf(items) });
        expect(await screen.findByTestId('todo-checklist-add-input')).toBeDisabled();
        expect(screen.getByTestId('todo-checklist-add-submit')).toBeDisabled();
        expect(screen.getByText(/項目は最大 100 件までです/)).toBeInTheDocument();
    });
});

describe('チェックリスト: 名前の変更・並べ替え・削除', () => {
    it('名前を編集して Enter で保存する (title だけを送る)。Esc では保存せずに取り消す', async () => {
        const user = userEvent.setup();
        const renamed = checklistItemOf({ ...FIRST, title: '雛形を確認する', version: 2 });
        const spy = renderTodoDetail({
            checklist: checklistOf([FIRST]),
            replies: { [itemKey('PATCH', FIRST.id)]: checklistReply(checklistOf([renamed])) },
        });
        await user.click(await screen.findByTestId(`todo-checklist-item-${FIRST.id}-edit`));
        const input = screen.getByTestId(`todo-checklist-item-${FIRST.id}-rename-input`);
        expect(input).toHaveFocus();
        await user.clear(input);
        await user.type(input, '捨てる{Escape}');
        expect(screen.queryByTestId(`todo-checklist-item-${FIRST.id}-rename-input`)).toBeNull();
        expect(screen.getByTestId(`todo-checklist-item-${FIRST.id}-title`)).toHaveTextContent('見積書の雛形を探す');
        expect(lastRequest(spy, 'PATCH')).toBeUndefined();
        // 取り消した後は編集ボタンへフォーカスが戻る
        expect(screen.getByTestId(`todo-checklist-item-${FIRST.id}-edit`)).toHaveFocus();

        await user.click(screen.getByTestId(`todo-checklist-item-${FIRST.id}-edit`));
        const again = screen.getByTestId(`todo-checklist-item-${FIRST.id}-rename-input`);
        await user.clear(again);
        await user.type(again, '雛形を確認する{Enter}');
        await vi.waitFor(() => expect(screen.getByTestId(`todo-checklist-item-${FIRST.id}-title`)).toHaveTextContent('雛形を確認する'));
        const request = lastRequest(spy, 'PATCH');
        expect(request?.headers.get('If-Match')).toBe('"1"');
        expect(await request?.json()).toEqual({ title: '雛形を確認する' });
    });

    it('メニューの「下へ移動」で並べ替える (チェックリストの版を If-Match に付けて全項目の ID を送る)。先頭の「上へ移動」は無効', async () => {
        const user = userEvent.setup();
        const spy = renderTodoDetail({
            checklist: checklistOf([FIRST, SECOND], { version: 3 }),
            replies: { [ORDER_KEY]: checklistReply(checklistOf([{ ...SECOND, position: 0 }, { ...FIRST, position: 1 }], { version: 4 })) },
        });
        await user.click(await screen.findByTestId(`todo-checklist-item-${FIRST.id}-menu-button`));
        expect(await screen.findByTestId(`todo-checklist-item-${FIRST.id}-move-up`)).toHaveAttribute('aria-disabled', 'true');
        await user.click(screen.getByTestId(`todo-checklist-item-${FIRST.id}-move-down`));
        await vi.waitFor(() => expect(lastRequest(spy, 'PUT')).toBeDefined());
        const request = lastRequest(spy, 'PUT');
        expect(request?.headers.get('If-Match')).toBe('"3"');
        expect(await request?.json()).toEqual({ item_ids: [SECOND.id, FIRST.id] });
        const rows = await within(screen.getByTestId('todo-checklist-items')).findAllByRole('listitem');
        await vi.waitFor(() => expect(rows[0]).toHaveAttribute('data-testid', `todo-checklist-item-${SECOND.id}`));
        expect(screen.getByTestId('todo-checklist-live')).toHaveTextContent('「見積書の雛形を探す」を 2 番目に移動しました');
    });

    it('ドラッグハンドルをキーボード (スペースで持ち上げ、矢印で移動、スペースで置く) で操作して並べ替える', async () => {
        const user = userEvent.setup();
        const spy = renderTodoDetail({
            checklist: checklistOf([FIRST, SECOND], { version: 3 }),
            replies: { [ORDER_KEY]: checklistReply(checklistOf([{ ...SECOND, position: 0 }, { ...FIRST, position: 1 }], { version: 4 })) },
        });
        const handle = await screen.findByTestId(`todo-checklist-item-${FIRST.id}-handle`);
        expect(handle).toHaveAccessibleName('「見積書の雛形を探す」をドラッグして並べ替え');
        const liveRegion = () => document.querySelector('[id^="DndLiveRegion"]');
        handle.scrollIntoView({ block: 'center' });
        handle.focus();
        await user.keyboard(' ');
        await vi.waitFor(() => expect(liveRegion()).toHaveTextContent('1 番目の位置に移動しています'));
        // dnd-kit は持ち上げの直後にキーの受け付けを始めるため、少し待ってから動かす
        await new Promise((resolve) => setTimeout(resolve, 200));
        await user.keyboard('{ArrowDown}');
        await vi.waitFor(() => expect(liveRegion()).toHaveTextContent('2 番目の位置に移動しています'));
        await user.keyboard(' ');
        await vi.waitFor(() => expect(lastRequest(spy, 'PUT')).toBeDefined());
        expect(await lastRequest(spy, 'PUT')?.json()).toEqual({ item_ids: [SECOND.id, FIRST.id] });
    });

    it('メニューの「削除」で、項目の版を If-Match に付けて削除する', async () => {
        const user = userEvent.setup();
        const spy = renderTodoDetail({
            checklist: checklistOf([FIRST, SECOND]),
            replies: { [itemKey('DELETE', SECOND.id)]: checklistReply(checklistOf([FIRST], { version: 2 })) },
        });
        await user.click(await screen.findByTestId(`todo-checklist-item-${SECOND.id}-menu-button`));
        await user.click(await screen.findByTestId(`todo-checklist-item-${SECOND.id}-delete`));
        await vi.waitFor(() => expect(screen.queryByTestId(`todo-checklist-item-${SECOND.id}`)).toBeNull());
        expect(lastRequest(spy, 'DELETE')?.headers.get('If-Match')).toBe('"2"');
    });
});

describe('チェックリスト: 同時編集 (412) と失敗', () => {
    it('412 では最新のチェックリストを自動で取り直し、「最新を表示しました」と知らせる', async () => {
        const user = userEvent.setup();
        let get_calls = 0;
        const other_done = checklistItemOf({ ...FIRST, is_done: true, version: 2, done_by: todoUserRefOf(), done_at: '2026-10-03T00:00:00Z' });
        renderTodoDetail({
            checklist: checklistOf([FIRST]),
            replies: {
                [CHECKLIST_KEY]: () => {
                    get_calls += 1;
                    return get_calls === 1 ? checklistReply(checklistOf([FIRST])) : checklistReply(checklistOf([other_done], { version: 2 }));
                },
                [itemKey('PATCH', FIRST.id)]: problemReply(412, 'todo_checklist_version_conflict'),
            },
        });
        await user.click(await screen.findByTestId(`todo-checklist-item-${FIRST.id}-check`));
        const notice = await screen.findByTestId('todo-checklist-refreshed');
        expect(notice).toHaveAttribute('role', 'alert');
        expect(notice).toHaveTextContent('最新の内容を表示しました');
        expect(screen.getByTestId(`todo-checklist-item-${FIRST.id}`)).toHaveAttribute('data-done', 'true');
        expect(screen.queryByTestId('todo-checklist-error')).toBeNull();
    });

    it('権限の無い操作の失敗など、取り直しで直らない失敗は role="alert" で出す', async () => {
        const user = userEvent.setup();
        renderTodoDetail({
            checklist: checklistOf([FIRST]),
            replies: { [itemKey('PATCH', FIRST.id)]: problemReply(500, 'internal_error') },
        });
        await user.click(await screen.findByTestId(`todo-checklist-item-${FIRST.id}-check`));
        expect(await screen.findByTestId('todo-checklist-error')).toHaveAttribute('role', 'alert');
    });
});
