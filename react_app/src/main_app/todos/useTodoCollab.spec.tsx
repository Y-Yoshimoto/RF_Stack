// useTodoComments / useTodoChecklist / useTodoSummary のテスト (権限で API を呼ばない・ETag の受け渡し・412 の自動の取り直し)
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { TodoChecklistRead, TodoCommentRead, TodoOperation } from '@/main_app/api/contract';
import { APP_STATUS_KEY, AppTestProvider, appStatusReply, OTHER_USER_ID } from '@/main_app/testing/app_test_support';
import { CHECKLIST_ITEM_ID, checklistItemOf, checklistOf, COMMENT_ID, commentOf, SECOND_CHECKLIST_ITEM_ID, summaryOf, TODO_ID, todoUserRefOf } from '@/main_app/testing/todo_test_data';
import { calledKeys, calledRequests, mockFetch, problemReply, type MockHandler, type MockReply } from '@/shared/testing/fetch_mock';
import { useTodoChecklist } from './useTodoChecklist';
import { useTodoComments, type TodoCommentResult } from './useTodoComments';
import { useTodoSummary } from './useTodoSummary';

const COMMENTS_PATH = `/api/v1/todos/${TODO_ID}/comments`;
const COMMENT_PATH = `${COMMENTS_PATH}/${COMMENT_ID}`;
const CHECKLIST_PATH = `/api/v1/todos/${TODO_ID}/checklist`;
const ITEM_PATH = `${CHECKLIST_PATH}/items/${CHECKLIST_ITEM_ID}`;

afterEach(() => {
    vi.restoreAllMocks();
});

const writeKeys = (spy: ReturnType<typeof mockFetch>) => calledKeys(spy).filter((key) => !key.startsWith('GET '));
const requestOf = (spy: ReturnType<typeof mockFetch>, key: string) => calledRequests(spy).find((request) => `${request.method} ${new URL(request.url).pathname}` === key);
const commentReply = (comment: TodoCommentRead, status = 200): MockReply => ({ status, body: comment, headers: { ETag: `"${comment.version}"` } });
const checklistReply = (checklist: TodoChecklistRead, status = 200): MockReply => ({ status, body: checklist, headers: { ETag: `"${checklist.version}"` } });

describe('useTodoComments', () => {
    const others = commentOf({ id: 'c2', author: todoUserRefOf(OTHER_USER_ID, 'Taro Yamada'), permissions: { can_edit: false, can_delete: false } });

    /**
     * コメントの一覧を描画して取得を待つ関数
     * @param {Record<string, MockHandler>} replies 追加の応答
     * @param {boolean | undefined} can_comment 投稿の権限
     * @returns {Promise<{ result, spy }>} 描画結果と fetch の spy
    */
    const renderComments = async (replies: Record<string, MockHandler>, can_comment?: boolean) => {
        const spy = mockFetch({
            [APP_STATUS_KEY]: appStatusReply(['member']),
            [`GET ${COMMENTS_PATH}`]: { status: 200, body: { items: [commentOf(), others], next_cursor: null } },
            ...replies,
        });
        const { result } = renderHook(() => useTodoComments(TODO_ID, { can_comment }), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        return { result, spy };
    };

    it('投稿は末尾に足し、編集は置き換え (If-Match はコメントの版)、削除は除く (If-Match 付き)', async () => {
        const created = commentOf({ id: 'c3', body: '追加', version: 1 });
        const { result, spy } = await renderComments({
            [`POST ${COMMENTS_PATH}`]: commentReply(created, 201),
            [`PATCH ${COMMENT_PATH}`]: commentReply(commentOf({ body: '直した', version: 2, edited_at: '2026-10-03T00:00:00Z' })),
            [`DELETE ${COMMENT_PATH}`]: { status: 204 },
        }, true);

        await act(async () => {
            await result.current.create('追加');
        });
        expect(result.current.items.map((item) => item.id)).toEqual([COMMENT_ID, 'c2', 'c3']);
        expect(await requestOf(spy, `POST ${COMMENTS_PATH}`)?.json()).toEqual({ body: '追加' });

        await act(async () => {
            await result.current.update(result.current.items[0], '直した');
        });
        expect(result.current.items[0].edited_at).not.toBeNull();
        expect(requestOf(spy, `PATCH ${COMMENT_PATH}`)?.headers.get('If-Match')).toBe('"1"');

        await act(async () => {
            await result.current.remove(result.current.items[0]);
        });
        expect(result.current.items.map((item) => item.id)).toEqual(['c2', 'c3']);
        expect(requestOf(spy, `DELETE ${COMMENT_PATH}`)?.headers.get('If-Match')).toBe('"2"');
    });

    it('権限が無い操作・空の本文は API を呼ばずに失敗にする', async () => {
        const { result, spy } = await renderComments({}, false);
        const outcomes: TodoCommentResult[] = [];
        for (const run of [() => result.current.create('投稿'), () => result.current.update(others, '書き換え'), () => result.current.remove(others)]) {
            await act(async () => {
                outcomes.push(await run());
            });
        }
        expect(outcomes.map((outcome) => (outcome.ok ? null : [outcome.failure.kind, outcome.failure.operation]))).toEqual([
            ['forbidden', null],
            ['forbidden', 'edit_comment'],
            ['forbidden', 'delete_comment'],
        ]);
        const own = await renderComments({}, true);
        await act(async () => {
            await own.result.current.create('   ');
        });
        expect(own.result.current.failure?.kind).toBe('invalid_input');
        expect([...writeKeys(spy), ...writeKeys(own.spy)]).toEqual([]);
    });

    it('412 todo_comment_version_conflict は requires_reload の失敗にする', async () => {
        const { result } = await renderComments({ [`PATCH ${COMMENT_PATH}`]: problemReply(412, 'todo_comment_version_conflict') });
        await act(async () => {
            await result.current.update(result.current.items[0], '直した');
        });
        expect(result.current.failure).toMatchObject({ kind: 'version_conflict', requires_reload: true, comment_id: COMMENT_ID });
    });
});

describe('useTodoChecklist', () => {
    const second = checklistItemOf({ id: SECOND_CHECKLIST_ITEM_ID, title: '送付先を確認する', position: 1, version: 3 });
    const initial = checklistOf([checklistItemOf(), second], { version: 2 });

    /**
     * チェックリストを描画して取得を待つ関数
     * @param {Record<string, MockHandler>} replies 追加の応答
     * @param {MockHandler} get_reply GET の応答
     * @returns {Promise<{ result, spy }>} 描画結果と fetch の spy
    */
    const renderChecklist = async (replies: Record<string, MockHandler>, get_reply: MockHandler = checklistReply(initial)) => {
        const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(['member']), [`GET ${CHECKLIST_PATH}`]: get_reply, ...replies });
        const onChanged = vi.fn();
        const { result } = renderHook(() => useTodoChecklist(TODO_ID, { onChanged }), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        return { result, spy, onChanged };
    };

    it('切り替えは項目の版を If-Match に付け、応答の全体で置き換える', async () => {
        const toggled = checklistOf([checklistItemOf({ is_done: true, version: 2, done_by: todoUserRefOf() }), second], { version: 2 });
        const { result, spy, onChanged } = await renderChecklist({ [`PATCH ${ITEM_PATH}`]: checklistReply(toggled) });
        expect(result.current.etag).toBe('"2"');
        await act(async () => {
            await result.current.toggle(initial.items[0]);
        });
        const request = requestOf(spy, `PATCH ${ITEM_PATH}`);
        expect(request?.headers.get('If-Match')).toBe('"1"');
        expect(await request?.json()).toEqual({ is_done: true });
        expect(result.current.checklist?.done_count).toBe(1);
        expect(onChanged).toHaveBeenCalledWith(toggled);
    });

    it('並べ替えはチェックリストの ETag を If-Match に付け、追加は項目名の前後の空白を除いて送る', async () => {
        const reordered = checklistOf([{ ...second, position: 0 }, { ...checklistItemOf(), position: 1 }], { version: 3 });
        const added = checklistOf([...reordered.items, checklistItemOf({ id: 'new', title: '追加', position: 2 })], { version: 4 });
        const { result, spy } = await renderChecklist({
            [`PUT ${CHECKLIST_PATH}/order`]: checklistReply(reordered),
            [`POST ${CHECKLIST_PATH}/items`]: checklistReply(added, 201),
        });
        await act(async () => {
            await result.current.reorder([SECOND_CHECKLIST_ITEM_ID, CHECKLIST_ITEM_ID]);
        });
        const put = requestOf(spy, `PUT ${CHECKLIST_PATH}/order`);
        expect(put?.headers.get('If-Match')).toBe('"2"');
        expect(await put?.json()).toEqual({ item_ids: [SECOND_CHECKLIST_ITEM_ID, CHECKLIST_ITEM_ID] });
        expect(result.current.etag).toBe('"3"');

        await act(async () => {
            await result.current.add('  追加  ');
        });
        const post = requestOf(spy, `POST ${CHECKLIST_PATH}/items`);
        expect(post?.headers.has('If-Match')).toBe(false);
        expect(await post?.json()).toEqual({ title: '追加' });
        expect(result.current.checklist?.items.map((item) => item.id)).toEqual([SECOND_CHECKLIST_ITEM_ID, CHECKLIST_ITEM_ID, 'new']);
        expect(result.current.etag).toBe('"4"');
    });

    it('can_edit / can_check が無い操作は API を呼ばずに弾く (担当者はチェックだけできる)', async () => {
        const assignee = checklistOf(initial.items, { version: 2, permissions: { can_edit: false, can_check: true } });
        const toggled = checklistOf([checklistItemOf({ is_done: true, version: 2 }), second], { version: 2, permissions: { can_edit: false, can_check: true } });
        const { result, spy } = await renderChecklist({ [`PATCH ${ITEM_PATH}`]: checklistReply(toggled) }, checklistReply(assignee));
        const operations: (TodoOperation | null)[] = [];
        for (const run of [() => result.current.add('追加'), () => result.current.rename(initial.items[0], '別名'), () => result.current.remove(initial.items[0]), () => result.current.reorder([SECOND_CHECKLIST_ITEM_ID, CHECKLIST_ITEM_ID])]) {
            await act(async () => {
                const outcome = await run();
                operations.push(outcome.ok ? null : outcome.failure.operation);
            });
        }
        expect(operations).toEqual(['edit_checklist', 'edit_checklist', 'edit_checklist', 'edit_checklist']);
        expect(writeKeys(spy)).toEqual([]);

        await act(async () => {
            await result.current.toggle(initial.items[0]);
        });
        expect(writeKeys(spy)).toEqual([`PATCH ${ITEM_PATH}`]);
    });

    it('412 は自動で最新を取り直し (表示は success のまま)、refreshed / failure_refreshed で知らせる', async () => {
        const latest = checklistOf([checklistItemOf({ title: '他の人が変えた', version: 2 }), second], { version: 2 });
        let gets = 0;
        const { result, spy } = await renderChecklist(
            { [`PATCH ${ITEM_PATH}`]: problemReply(412, 'todo_checklist_version_conflict') },
            () => (++gets === 1 ? checklistReply(initial) : checklistReply(latest)),
        );
        let refreshed = false;
        await act(async () => {
            const outcome = await result.current.rename(initial.items[0], '自分の名前');
            refreshed = !outcome.ok && outcome.refreshed;
        });
        expect(refreshed).toBe(true);
        expect(result.current.status).toBe('success');
        expect(result.current.failure).toMatchObject({ kind: 'version_conflict', item_id: CHECKLIST_ITEM_ID });
        expect(result.current.failure_refreshed).toBe(true);
        expect(result.current.checklist?.items[0].title).toBe('他の人が変えた');
        expect(calledKeys(spy).filter((key) => key === `GET ${CHECKLIST_PATH}`)).toHaveLength(2);
    });

    it('422 の並べ替えの集合不一致も取り直す', async () => {
        const mismatch: MockReply = {
            status: 422,
            body: { type: 'about:blank', title: 'x', status: 422, detail: 'x', instance: '/', code: 'invalid_todo_input', errors: [{ field: 'item_ids', code: 'mismatch', message: 'x' }] },
        };
        const { result, spy } = await renderChecklist({ [`PUT ${CHECKLIST_PATH}/order`]: mismatch });
        await act(async () => {
            await result.current.reorder([SECOND_CHECKLIST_ITEM_ID, CHECKLIST_ITEM_ID]);
        });
        expect(result.current.failure).toMatchObject({ kind: 'invalid_input', requires_reload: true });
        await waitFor(() => expect(calledKeys(spy).filter((key) => key === `GET ${CHECKLIST_PATH}`)).toHaveLength(2));
    });
});

describe('useTodoSummary', () => {
    it('today と due_soon_days を付けて要約を取得する', async () => {
        const spy = mockFetch({ [APP_STATUS_KEY]: appStatusReply(['member']), 'GET /api/v1/todos/summary': { status: 200, body: summaryOf() } });
        const { result } = renderHook(() => useTodoSummary('2026-10-29'), { wrapper: AppTestProvider });
        await waitFor(() => expect(result.current.status).toBe('success'));
        expect(result.current.summary?.assigned.overdue).toBe(1);
        const request = requestOf(spy, 'GET /api/v1/todos/summary');
        expect(new URL(request?.url ?? '').search).toBe('?today=2026-10-29&due_soon_days=7');
    });
});
