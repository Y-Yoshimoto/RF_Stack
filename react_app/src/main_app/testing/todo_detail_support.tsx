// テスト用: ToDo の詳細画面を描画する補助 (アプリのコードからは import しない)
import { Route } from 'react-router-dom';
import type { TodoChecklistRead, TodoCommentRead, TodoDetail } from '@/main_app/api/contract';
import { AppTodoDetailPage } from '@/main_app/pages/TodoDetail';
import { mockFetch, type MockHandler, type MockReply } from '@/shared/testing/fetch_mock';
import { organizationOf } from './app_test_support';
import { renderAppScreen } from './render_screen';
import { SAMPLE_USERS, pageOf } from './story_data';
import { TODO_ID, checklistOf, todoDetailOf } from './todo_test_data';

export const DETAIL_KEY = `GET /api/v1/todos/${TODO_ID}`;
export const PATCH_KEY = `PATCH /api/v1/todos/${TODO_ID}`;
export const ACTIVITIES_KEY = `GET /api/v1/todos/${TODO_ID}/activities`;
export const COMMENTS_KEY = `GET /api/v1/todos/${TODO_ID}/comments`;
export const CHECKLIST_KEY = `GET /api/v1/todos/${TODO_ID}/checklist`;

/**
 * 詳細の応答を作る関数
 * @param {Partial<TodoDetail>} overrides 上書きする項目
 * @returns {MockReply} 応答 (ETag は version)
*/
export const detailReply = (overrides: Partial<TodoDetail> = {}): MockReply => {
    const body = todoDetailOf(overrides);
    return { status: 200, body, headers: { ETag: `"${body.version}"` } };
};

/**
 * チェックリストの応答を作る関数 (ETag はチェックリストの版)
 * @param {TodoChecklistRead} checklist チェックリスト
 * @param {number} status ステータス (追加は 201)
 * @returns {MockReply} 応答
*/
export const checklistReply = (checklist: TodoChecklistRead, status: number = 200): MockReply => ({ status, body: checklist, headers: { ETag: `"${checklist.version}"` } });

/**
 * コメントの応答を作る関数 (ETag はコメントの版)
 * @param {TodoCommentRead} comment コメント
 * @param {number} status ステータス (投稿は 201)
 * @returns {MockReply} 応答
*/
export const commentReply = (comment: TodoCommentRead, status: number = 200): MockReply => ({ status, body: comment, headers: { ETag: `"${comment.version}"` } });

export type RenderTodoDetailOptions = {
    detail?: Partial<TodoDetail>;
    /** 追加・上書きの応答。 */
    replies?: Record<string, MockHandler>;
    roles?: string[];
    /** コメントの一覧 (既定は空)。 */
    comments?: TodoCommentRead[];
    /** チェックリスト (既定は項目なし・すべて可)。 */
    checklist?: TodoChecklistRead;
};

/**
 * 詳細画面を描画する関数
 * @param {RenderTodoDetailOptions} options 詳細の上書き・追加の応答・ロール・コメント・チェックリスト
 * @returns {ReturnType<typeof mockFetch>} fetch の spy
*/
export const renderTodoDetail = ({ detail = {}, replies = {}, roles = ['tenant_admin'], comments = [], checklist = checklistOf([]) }: RenderTodoDetailOptions = {}) => {
    const spy = mockFetch({
        [DETAIL_KEY]: detailReply(detail),
        [ACTIVITIES_KEY]: { status: 200, body: pageOf([]) },
        [COMMENTS_KEY]: { status: 200, body: pageOf(comments) },
        [CHECKLIST_KEY]: checklistReply(checklist),
        'GET /api/v1/users': { status: 200, body: pageOf(SAMPLE_USERS) },
        'GET /api/v1/organizations': { status: 200, body: pageOf([organizationOf()]) },
        ...replies,
    });
    renderAppScreen(<Route path="/alpha/todos/:todoId" element={<AppTodoDetailPage />} />, { path: `/alpha/todos/${TODO_ID}`, roles });
    return spy;
};
