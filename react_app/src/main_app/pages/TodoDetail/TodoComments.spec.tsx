// ToDo 詳細のコメントのテスト (古い順・投稿者・編集済み・編集/削除の出し分け・投稿 (Ctrl/Cmd + Enter)・編集・削除の確認・文字数の上限。AP-CMT)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { calledRequests, problemReply, type mockFetch as MockFetch } from '@/shared/testing/fetch_mock';
import { OTHER_USER_ID } from '@/main_app/testing/app_test_support';
import { commentReply, renderTodoDetail } from '@/main_app/testing/todo_detail_support';
import { COMMENT_ID, TODO_ID, VIEWER_TODO_PERMISSIONS, commentOf, todoUserRefOf } from '@/main_app/testing/todo_test_data';

const COMMENTS_PATH = `/api/v1/todos/${TODO_ID}/comments`;
const OTHER_COMMENT_ID = '01900000-0000-7000-8000-00000000e002';

afterEach(() => {
    vi.restoreAllMocks();
});

const MINE = commentOf({ id: COMMENT_ID, body: '確認しました\n明日までに返します', created_at: '2026-10-02T00:00:00Z' });
/** 他人のコメント (tenant_admin は削除だけできる) */
const THEIRS = commentOf({
    id: OTHER_COMMENT_ID,
    author: { ...todoUserRefOf(OTHER_USER_ID, 'Taro Yamada'), is_active: false },
    body: '了解です',
    version: 3,
    edited_at: '2026-10-03T00:00:00Z',
    created_at: '2026-10-03T00:00:00Z',
    permissions: { can_edit: false, can_delete: true },
});
const lastRequest = (spy: ReturnType<typeof MockFetch>, method: string) => calledRequests(spy).filter((request) => request.method === method).at(-1);

describe('コメント: 表示と出し分け', () => {
    it('古い順に、投稿者・日時・本文 (改行を保つ) を出し、編集したコメントには「編集済み」、無効なユーザーには「(無効)」を添える', async () => {
        renderTodoDetail({ comments: [MINE, THEIRS], detail: { comment_count: 2 } });
        const list = await screen.findByTestId('todo-comments-list');
        const rows = within(list).getAllByRole('listitem');
        expect(rows.map((row) => row.getAttribute('data-testid'))).toEqual([`todo-comment-${COMMENT_ID}`, `todo-comment-${OTHER_COMMENT_ID}`]);
        expect(screen.getByTestId(`todo-comment-${COMMENT_ID}-author`)).toHaveTextContent('Hanako Suzuki');
        expect(screen.getByTestId(`todo-comment-${COMMENT_ID}-body`)).toHaveTextContent('確認しました');
        expect(screen.getByTestId(`todo-comment-${COMMENT_ID}-body`)).toHaveStyle({ whiteSpace: 'pre-wrap' });
        expect(screen.queryByTestId(`todo-comment-${COMMENT_ID}-edited`)).toBeNull();
        expect(screen.getByTestId(`todo-comment-${OTHER_COMMENT_ID}-author`)).toHaveTextContent('Taro Yamada (無効)');
        expect(screen.getByTestId(`todo-comment-${OTHER_COMMENT_ID}-edited`)).toHaveTextContent('編集済み');
        expect(screen.getByTestId('todo-tab-comments')).toHaveTextContent('コメント (2)');
    });

    it('自分のコメントには編集と削除を、tenant_admin には他人のコメントの削除だけを出す', async () => {
        renderTodoDetail({ comments: [MINE, THEIRS] });
        await screen.findByTestId('todo-comments-list');
        expect(screen.getByTestId(`todo-comment-${COMMENT_ID}-edit`)).toBeInTheDocument();
        expect(screen.getByTestId(`todo-comment-${COMMENT_ID}-delete`)).toBeInTheDocument();
        expect(screen.queryByTestId(`todo-comment-${OTHER_COMMENT_ID}-edit`)).toBeNull();
        expect(screen.getByTestId(`todo-comment-${OTHER_COMMENT_ID}-delete`)).toBeInTheDocument();
    });

    it('member の他人のコメントには、編集も削除も出さない', async () => {
        const theirs = commentOf({ ...THEIRS, permissions: { can_edit: false, can_delete: false } });
        renderTodoDetail({ roles: ['member'], comments: [theirs] });
        await screen.findByTestId('todo-comments-list');
        expect(screen.queryByTestId(`todo-comment-${OTHER_COMMENT_ID}-edit`)).toBeNull();
        expect(screen.queryByTestId(`todo-comment-${OTHER_COMMENT_ID}-delete`)).toBeNull();
    });

    it('コメントが無ければ空の案内を出す。投稿の権限が無ければ入力欄の代わりに理由を示す', async () => {
        renderTodoDetail({ detail: { permissions: { ...VIEWER_TODO_PERMISSIONS, can_comment: false } } });
        expect(await screen.findByTestId('todo-comments-empty')).toBeInTheDocument();
        expect(screen.getByTestId('todo-comment-readonly')).toBeInTheDocument();
        expect(screen.queryByTestId('todo-comment-input')).toBeNull();
    });
});

describe('コメント: 投稿', () => {
    it('Ctrl + Enter で投稿し、末尾に加える。入力を空にしてフォーカスを保ち、タブの件数を増やす', async () => {
        const user = userEvent.setup();
        const created = commentOf({ id: 'new-comment', body: '追記します', created_at: '2026-10-04T00:00:00Z' });
        const spy = renderTodoDetail({ comments: [MINE], detail: { comment_count: 1 }, replies: { [`POST ${COMMENTS_PATH}`]: commentReply(created, 201) } });
        const input = await screen.findByTestId('todo-comment-input');
        await user.type(input, '追記します');
        await user.keyboard('{Control>}{Enter}{/Control}');
        const row = await screen.findByTestId('todo-comment-new-comment');
        expect(row).toBeInTheDocument();
        expect(within(screen.getByTestId('todo-comments-list')).getAllByRole('listitem').at(-1)).toBe(row);
        expect(await lastRequest(spy, 'POST')?.json()).toEqual({ body: '追記します' });
        expect(input).toHaveValue('');
        expect(input).toHaveFocus();
        expect(screen.getByTestId('todo-tab-comments')).toHaveTextContent('コメント (2)');
    });

    it('Enter だけでは投稿せず改行になる。空白だけでは投稿できない', async () => {
        const user = userEvent.setup();
        const spy = renderTodoDetail();
        const input = await screen.findByTestId('todo-comment-input');
        expect(screen.getByTestId('todo-comment-submit')).toBeDisabled();
        await user.type(input, '1 行目{Enter}2 行目');
        expect(input).toHaveValue('1 行目\n2 行目');
        expect(lastRequest(spy, 'POST')).toBeUndefined();
        await user.clear(input);
        await user.type(input, '   ');
        expect(screen.getByTestId('todo-comment-submit')).toBeDisabled();
    });

    it('残り文字数を示し、4,000 文字を超えると投稿できない', async () => {
        const user = userEvent.setup();
        renderTodoDetail();
        const input = await screen.findByTestId('todo-comment-input');
        await user.type(input, 'あいうえおかきくけこ');
        expect(screen.getByText(/残り 3,990 文字/)).toBeInTheDocument();
        await user.clear(input);
        await user.click(input);
        await user.paste('a'.repeat(4001));
        expect(screen.getByText(/1 文字超えています/)).toBeInTheDocument();
        expect(screen.getByTestId('todo-comment-submit')).toBeDisabled();
    });

    it('投稿に失敗したら入力を残し、role="alert" で知らせる', async () => {
        const user = userEvent.setup();
        renderTodoDetail({ replies: { [`POST ${COMMENTS_PATH}`]: problemReply(500, 'internal_error') } });
        const input = await screen.findByTestId('todo-comment-input');
        await user.type(input, '失敗する');
        await user.click(screen.getByTestId('todo-comment-submit'));
        expect(await screen.findByTestId('todo-comments-error')).toHaveAttribute('role', 'alert');
        expect(input).toHaveValue('失敗する');
    });
});

describe('コメント: 編集と削除', () => {
    it('編集して保存すると、コメントの版を If-Match に付けて本文を送り、「編集済み」にする', async () => {
        const user = userEvent.setup();
        const edited = commentOf({ ...MINE, body: '修正しました', version: 2, edited_at: '2026-10-05T00:00:00Z' });
        const spy = renderTodoDetail({ comments: [MINE], replies: { [`PATCH ${COMMENTS_PATH}/${COMMENT_ID}`]: commentReply(edited) } });
        await user.click(await screen.findByTestId(`todo-comment-${COMMENT_ID}-edit`));
        const input = screen.getByTestId(`todo-comment-${COMMENT_ID}-input`);
        expect(input).toHaveFocus();
        expect(screen.getByTestId(`todo-comment-${COMMENT_ID}-save`)).toBeDisabled();
        await user.clear(input);
        await user.type(input, '修正しました');
        await user.click(screen.getByTestId(`todo-comment-${COMMENT_ID}-save`));
        expect(await screen.findByTestId(`todo-comment-${COMMENT_ID}-edited`)).toBeInTheDocument();
        expect(screen.getByTestId(`todo-comment-${COMMENT_ID}-body`)).toHaveTextContent('修正しました');
        const request = lastRequest(spy, 'PATCH');
        expect(request?.headers.get('If-Match')).toBe('"1"');
        expect(await request?.json()).toEqual({ body: '修正しました' });
        expect(screen.getByTestId(`todo-comment-${COMMENT_ID}-edit`)).toHaveFocus();
    });

    it('Esc で編集を取り消す (送信しない)', async () => {
        const user = userEvent.setup();
        const spy = renderTodoDetail({ comments: [MINE] });
        await user.click(await screen.findByTestId(`todo-comment-${COMMENT_ID}-edit`));
        await user.type(screen.getByTestId(`todo-comment-${COMMENT_ID}-input`), '追記{Escape}');
        expect(screen.queryByTestId(`todo-comment-${COMMENT_ID}-input`)).toBeNull();
        expect(screen.getByTestId(`todo-comment-${COMMENT_ID}-body`)).toHaveTextContent('確認しました');
        expect(lastRequest(spy, 'PATCH')).toBeUndefined();
    });

    it('削除は確認ダイアログを経由し (初期フォーカスはキャンセル)、確認すると If-Match 付きで削除して件数を減らす。他人のコメントも tenant_admin は削除できる', async () => {
        const user = userEvent.setup();
        const spy = renderTodoDetail({
            comments: [MINE, THEIRS],
            detail: { comment_count: 2 },
            replies: { [`DELETE ${COMMENTS_PATH}/${OTHER_COMMENT_ID}`]: { status: 204 } },
        });
        await user.click(await screen.findByTestId(`todo-comment-${OTHER_COMMENT_ID}-delete`));
        const dialog = await screen.findByRole('dialog', { name: 'コメントを削除しますか' });
        expect(dialog).toHaveTextContent('Taro Yamada');
        await vi.waitFor(() => expect(screen.getByTestId('todo-comment-delete-dialog-cancel')).toHaveFocus());
        // キャンセルでは削除しない
        await user.click(screen.getByTestId('todo-comment-delete-dialog-cancel'));
        await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        expect(lastRequest(spy, 'DELETE')).toBeUndefined();

        await user.click(screen.getByTestId(`todo-comment-${OTHER_COMMENT_ID}-delete`));
        await user.click(await screen.findByTestId('todo-comment-delete-dialog-confirm'));
        await vi.waitFor(() => expect(screen.queryByTestId(`todo-comment-${OTHER_COMMENT_ID}`)).toBeNull());
        expect(lastRequest(spy, 'DELETE')?.headers.get('If-Match')).toBe('"3"');
        expect(screen.getByTestId('todo-tab-comments')).toHaveTextContent('コメント (1)');
        expect(screen.getByTestId(`todo-comment-${COMMENT_ID}`)).toBeInTheDocument();
    });

    it('削除に失敗したら、ダイアログの中に role="alert" で出す', async () => {
        const user = userEvent.setup();
        renderTodoDetail({ comments: [MINE], replies: { [`DELETE ${COMMENTS_PATH}/${COMMENT_ID}`]: problemReply(412, 'todo_comment_version_conflict') } });
        await user.click(await screen.findByTestId(`todo-comment-${COMMENT_ID}-delete`));
        await user.click(await screen.findByTestId('todo-comment-delete-dialog-confirm'));
        const alert = await screen.findByTestId('todo-comment-delete-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(within(screen.getByRole('dialog')).getByTestId('todo-comment-delete-error-reload')).toBeInTheDocument();
    });
});
