import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { Route } from 'react-router-dom';
import { OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { withAppAuth } from '@/main_app/testing/auth_decorators';
import { AppStoryFrame, appApiBeforeEach, problemStoryReply, type AppApiStoryParameters } from '@/main_app/testing/story_api';
import { ASSIGNEE_TODO_PERMISSIONS, CHECKLIST_ITEM_ID, COMMENT_ID, SECOND_CHECKLIST_ITEM_ID, TODO_ID, VIEWER_TODO_PERMISSIONS, activityOf, activityPageOf, checklistItemOf, checklistOf, commentOf, todoDetailOf, todoUserRefOf } from '@/main_app/testing/todo_test_data';
import { todoStoryApiOf } from '@/main_app/pages/TodoCommon/story_support';
import type { TodoChecklistRead, TodoCommentRead, TodoDetail } from '@/main_app/api/contract';
import { pageOf } from '@/main_app/testing/story_data';
import { withMemoryRouter } from '@/shared/testing/story_decorators';
import { AppTodoDetailPage } from '.';

const NO_PERMISSIONS = { can_edit_fields: false, can_change_status: false, can_change_visibility: false, can_change_assignees: false, can_delete: false, can_comment: true, can_edit_checklist: false, can_check_checklist: false };

const meta = {
    title: 'AP/TodoDetail',
    component: AppTodoDetailPage,
    parameters: { layout: 'fullscreen', initial_path: `/alpha/todos/${TODO_ID}` },
    decorators: [withAppAuth, withMemoryRouter],
    beforeEach: appApiBeforeEach,
    render: () => (
        <AppStoryFrame>
            <Route path="todos/:todoId" element={<AppTodoDetailPage />} />
        </AppStoryFrame>
    ),
} satisfies Meta<typeof AppTodoDetailPage>;

export default meta;
type Story = StoryObj<typeof meta>;

const ACTIVITIES = activityPageOf([
    activityOf({ id: 'a3', action: 'status_changed', payload: { changes: { status: { before: 'open', after: 'in_progress' } } }, created_at: '2026-10-03T00:00:00Z' }),
    activityOf({ id: 'a2', action: 'assignees_changed', payload: { added: [OTHER_USER_ID], removed: [] }, actor_display_name: 'Hanako Admin', created_at: '2026-10-02T00:00:00Z' }),
    activityOf({ id: 'a1', action: 'created', payload: { values: {} }, actor_display_name: 'Hanako Admin', created_at: '2026-10-01T00:00:00Z' }),
], {
    [SELF_USER_ID]: { display_name: 'Hanako Admin', is_active: true },
    [OTHER_USER_ID]: { display_name: 'Taro Yamada', is_active: false },
});

/**
 * ストーリーの parameters を作る関数
 * @param {Partial<TodoDetail>} detail 詳細の上書き
 * @param {string[]} roles ログイン中のロール
 * @param {AppApiStoryParameters} extra 追加の応答
 * @returns {object} parameters
*/
const parametersOf = (detail: Partial<TodoDetail> = {}, roles: string[] = ['tenant_admin', 'member'], extra: AppApiStoryParameters = {}, checklist: TodoChecklistRead = checklistOf([]), comments: TodoCommentRead[] = []) => {
    const body = todoDetailOf({ created_by: SELF_USER_ID, ...detail });
    return {
        app_auth: { roles },
        app_api: todoStoryApiOf(roles, {
            [`GET /api/v1/todos/${TODO_ID}`]: { status: 200, body, headers: { ETag: `"${body.version}"` } },
            [`GET /api/v1/todos/${TODO_ID}/activities`]: { status: 200, body: ACTIVITIES },
            [`GET /api/v1/todos/${TODO_ID}/checklist`]: { status: 200, body: checklist, headers: { ETag: `"${checklist.version}"` } },
            [`GET /api/v1/todos/${TODO_ID}/comments`]: { status: 200, body: pageOf(comments) },
            ...extra,
        }),
    };
};

/** テナント管理者 (すべての項目を編集でき、削除もできる) */
export const TenantAdmin: Story = {
    parameters: parametersOf(),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-fields-submit')).toBeInTheDocument();
        await expect(canvas.getByTestId('todo-detail-delete')).toBeInTheDocument();
    },
};

/** メンバー (他人が作成した ToDo の担当者のみ: ステータスと担当者だけ変えられる) */
export const AssigneeOnly: Story = {
    parameters: parametersOf({ created_by: OTHER_USER_ID, permissions: ASSIGNEE_TODO_PERMISSIONS }, ['member']),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-fields-readonly')).toBeInTheDocument();
        await expect(canvas.getByTestId('todo-edit-title')).toBeDisabled();
        await expect(canvas.queryByTestId('todo-fields-submit')).toBeNull();
        await expect(canvas.queryByTestId('todo-detail-delete')).toBeNull();
        await expect(canvas.getByTestId('todo-status-done')).toBeEnabled();
    },
};

/** メンバー (自分が作成した ToDo: すべての項目を編集でき、削除もできる) */
export const MemberCreator: Story = { parameters: parametersOf({}, ['member']) };

/** メンバー (閲覧のみ: 何も変更できない) */
export const ViewOnly: Story = {
    parameters: parametersOf({ created_by: OTHER_USER_ID, permissions: NO_PERMISSIONS }, ['member']),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-status-readonly')).toBeInTheDocument();
        await expect(canvas.getByTestId('todo-status-done')).toBeDisabled();
    },
};

/** 公開先の組織がすべて削除された (非公開と同じ扱いで、再指定を促す) */
export const NeedsOrganizationReselect: Story = {
    parameters: parametersOf({ visibility: 'organization', effective_visibility: 'private', organizations: [] }),
    play: async ({ canvasElement: canvas_element }) => {
        await expect(await within(canvas_element).findByTestId('todo-reselect-notice')).toBeInTheDocument();
    },
};

/** 読み込み中 */
export const Loading: Story = {
    parameters: { app_api: todoStoryApiOf(['tenant_admin'], { [`GET /api/v1/todos/${TODO_ID}`]: { status: 200, never_settles: true } }) },
};

/** 閲覧できない・削除済みの ToDo (404。存在を明かさない) */
export const NotFound: Story = {
    parameters: { app_api: todoStoryApiOf(['tenant_admin'], { [`GET /api/v1/todos/${TODO_ID}`]: problemStoryReply(404, 'todo_not_found') }) },
};

/** 他の操作で更新されていた (412。再読み込みを促す) */
export const VersionConflict: Story = {
    parameters: parametersOf({}, ['tenant_admin', 'member'], { [`PATCH /api/v1/todos/${TODO_ID}`]: problemStoryReply(412, 'todo_version_conflict') }),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await userEvent.click(await canvas.findByTestId('todo-status-done'));
        await expect(await canvas.findByTestId('todo-detail-action-error-reload')).toBeInTheDocument();
    },
};

/** 削除の確認ダイアログ (初期フォーカスは「キャンセル」) */
export const DeleteConfirm: Story = {
    parameters: parametersOf(),
    play: async ({ canvasElement: canvas_element }) => {
        await userEvent.click(await within(canvas_element).findByTestId('todo-detail-delete'));
        await expect(await within(document.body).findByRole('dialog', { name: 'ToDo を削除しますか' })).toBeInTheDocument();
    },
};

const CHECKLIST_ITEMS = [
    checklistItemOf({ id: CHECKLIST_ITEM_ID, title: '見積書の雛形を探す', position: 0, is_done: true, done_at: '2026-10-03T01:00:00Z', done_by: todoUserRefOf(SELF_USER_ID, 'Hanako Admin'), version: 2 }),
    checklistItemOf({ id: SECOND_CHECKLIST_ITEM_ID, title: '金額を確認する', position: 1 }),
    checklistItemOf({ id: 'item-3', title: '先方へ送付する (宛先は営業部の共有アドレスを使う。件名に案件番号を入れること)', position: 2 }),
];

/** チェックリスト (編集できる: ドラッグハンドル・名前変更・メニュー・追加欄が出る) */
export const ChecklistEditable: Story = {
    parameters: parametersOf({ checklist: { done_count: 1, total_count: 3 } }, ['tenant_admin', 'member'], {}, checklistOf(CHECKLIST_ITEMS)),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId(`todo-checklist-item-${CHECKLIST_ITEM_ID}-handle`)).toBeInTheDocument();
        await expect(canvas.getByTestId('todo-checklist-progress-text')).toHaveTextContent('1 / 3 完了');
        await expect(canvas.getByTestId('todo-checklist-add-input')).toBeEnabled();
    },
};

/** チェックリスト (担当者: チェックだけできる。名前変更・並べ替え・追加の操作は出ない) */
export const ChecklistAssigneeOnly: Story = {
    parameters: parametersOf(
        { created_by: OTHER_USER_ID, permissions: ASSIGNEE_TODO_PERMISSIONS, checklist: { done_count: 1, total_count: 3 } },
        ['member'],
        {},
        checklistOf(CHECKLIST_ITEMS, { permissions: { can_edit: false, can_check: true } }),
    ),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId(`todo-checklist-item-${SECOND_CHECKLIST_ITEM_ID}-check`)).toBeEnabled();
        await expect(canvas.queryByTestId(`todo-checklist-item-${SECOND_CHECKLIST_ITEM_ID}-handle`)).toBeNull();
        await expect(canvas.queryByTestId('todo-checklist-add-form')).toBeNull();
    },
};

/** チェックリスト (閲覧のみ: チェックも無効) */
export const ChecklistViewOnly: Story = {
    parameters: parametersOf(
        { created_by: OTHER_USER_ID, permissions: VIEWER_TODO_PERMISSIONS, checklist: { done_count: 1, total_count: 3 } },
        ['member'],
        {},
        checklistOf(CHECKLIST_ITEMS, { permissions: { can_edit: false, can_check: false } }),
    ),
    play: async ({ canvasElement: canvas_element }) => {
        await expect(await within(canvas_element).findByTestId(`todo-checklist-item-${CHECKLIST_ITEM_ID}-check`)).toBeDisabled();
    },
};

/** チェックリスト (項目が上限の 100 件: 追加欄が無効) */
export const ChecklistFull: Story = {
    parameters: parametersOf(
        { checklist: { done_count: 0, total_count: 100 } },
        ['tenant_admin', 'member'],
        {},
        checklistOf(Array.from({ length: 100 }, (_, index) => checklistItemOf({ id: `item-${index}`, title: `項目 ${index + 1}`, position: index }))),
    ),
    play: async ({ canvasElement: canvas_element }) => {
        await expect(await within(canvas_element).findByTestId('todo-checklist-add-input')).toBeDisabled();
    },
};

/** チェックリスト (メニューの「上へ移動」「下へ移動」「削除」) */
export const ChecklistMenu: Story = {
    parameters: parametersOf({ checklist: { done_count: 1, total_count: 3 } }, ['tenant_admin', 'member'], {}, checklistOf(CHECKLIST_ITEMS)),
    play: async ({ canvasElement: canvas_element }) => {
        await userEvent.click(await within(canvas_element).findByTestId(`todo-checklist-item-${SECOND_CHECKLIST_ITEM_ID}-menu-button`));
        await expect(await within(document.body).findByTestId(`todo-checklist-item-${SECOND_CHECKLIST_ITEM_ID}-move-up`)).toBeVisible();
    },
};

const COMMENTS = [
    commentOf({ id: COMMENT_ID, body: '確認しました。\n明日までに返します。', created_at: '2026-10-02T00:00:00Z' }),
    commentOf({
        id: 'comment-2',
        author: { ...todoUserRefOf(OTHER_USER_ID, 'Taro Yamada'), is_active: false },
        body: '了解です。金額は別途ご相談させてください。',
        edited_at: '2026-10-03T01:00:00Z',
        created_at: '2026-10-03T00:00:00Z',
        permissions: { can_edit: false, can_delete: true },
    }),
];

/** コメント (古い順。自分のコメントは編集・削除、tenant_admin は他人のコメントの削除だけ。「編集済み」・無効なユーザー) */
export const CommentsAdmin: Story = {
    parameters: parametersOf({ comment_count: 2 }, ['tenant_admin', 'member'], {}, checklistOf([]), COMMENTS),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId(`todo-comment-${COMMENT_ID}-edit`)).toBeInTheDocument();
        await expect(canvas.queryByTestId('todo-comment-comment-2-edit')).toBeNull();
        await expect(canvas.getByTestId('todo-comment-comment-2-delete')).toBeInTheDocument();
        await expect(canvas.getByTestId('todo-comment-comment-2-edited')).toBeInTheDocument();
    },
};

/** コメント (空。投稿欄に残り文字数と Ctrl/Cmd + Enter の案内) */
export const CommentsEmpty: Story = {
    parameters: parametersOf(),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await expect(await canvas.findByTestId('todo-comments-empty')).toBeInTheDocument();
        await userEvent.type(canvas.getByTestId('todo-comment-input'), '書きかけのコメント');
        await expect(canvas.getByTestId('todo-comment-submit')).toBeEnabled();
    },
};

/** コメントの削除の確認ダイアログ (初期フォーカスは「キャンセル」) */
export const CommentDeleteConfirm: Story = {
    parameters: parametersOf({ comment_count: 2 }, ['tenant_admin', 'member'], {}, checklistOf([]), COMMENTS),
    play: async ({ canvasElement: canvas_element }) => {
        await userEvent.click(await within(canvas_element).findByTestId('todo-comment-comment-2-delete'));
        await expect(await within(document.body).findByRole('dialog', { name: 'コメントを削除しますか' })).toBeInTheDocument();
    },
};

/** コメントの投稿権限が無い (入力欄の代わりに理由を示す) */
export const CommentsReadOnly: Story = {
    parameters: parametersOf({ created_by: OTHER_USER_ID, permissions: { ...VIEWER_TODO_PERMISSIONS, can_comment: false } }, ['member'], {}, checklistOf([], { permissions: { can_edit: false, can_check: false } }), COMMENTS.slice(0, 1)),
    play: async ({ canvasElement: canvas_element }) => {
        await expect(await within(canvas_element).findByTestId('todo-comment-readonly')).toBeInTheDocument();
    },
};

/** アクティビティのタブ (チェックリストの変更を含む) */
export const ActivitiesTab: Story = {
    parameters: parametersOf({}, ['tenant_admin', 'member'], {
        [`GET /api/v1/todos/${TODO_ID}/activities`]: {
            status: 200,
            body: activityPageOf([
                activityOf({ id: 'c2', action: 'checklist_changed', payload: { op: 'checked', item_id: CHECKLIST_ITEM_ID, title: '見積書の雛形を探す' }, created_at: '2026-10-03T01:00:00Z' }),
                activityOf({ id: 'c1', action: 'checklist_changed', payload: { op: 'added', item_id: CHECKLIST_ITEM_ID, title: '見積書の雛形を探す' }, created_at: '2026-10-02T00:00:00Z' }),
            ], { [SELF_USER_ID]: { display_name: 'Hanako Admin', is_active: true } }),
        },
    }),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        await userEvent.click(await canvas.findByTestId('todo-tab-activities'));
        await expect(await canvas.findByTestId('todo-activity-c2')).toHaveTextContent('チェックリストの「見積書の雛形を探す」を完了にしました');
    },
};

/** 保存が 412 になったが、最新の内容を自動で再表示した (入力は残し、重なった項目を知らせる。AP-UX-07) */
const conflict_state = { patched: false };
export const AutoRefreshedAfterConflict: Story = {
    beforeEach: () => {
        conflict_state.patched = false;
    },
    parameters: parametersOf({}, ['tenant_admin', 'member'], {
        [`GET /api/v1/todos/${TODO_ID}`]: () => {
            const latest = todoDetailOf({ created_by: SELF_USER_ID, version: conflict_state.patched ? 4 : 3, title: conflict_state.patched ? '他の人が変えたタイトル' : '見積もりを作る', description: conflict_state.patched ? '他の人が書いた説明' : '先方に送る' });
            return { status: 200, body: latest, headers: { ETag: `"${latest.version}"` } };
        },
        [`PATCH /api/v1/todos/${TODO_ID}`]: () => {
            conflict_state.patched = true;
            return problemStoryReply(412, 'todo_version_conflict');
        },
    }),
    play: async ({ canvasElement: canvas_element }) => {
        const canvas = within(canvas_element);
        const title = await canvas.findByTestId('todo-edit-title');
        await userEvent.clear(title);
        await userEvent.type(title, '自分が入力したタイトル');
        await userEvent.click(canvas.getByTestId('todo-fields-submit'));
        await expect(await canvas.findByTestId('todo-detail-refreshed')).toHaveTextContent('タイトルは他の人も変更しています');
        await expect(canvas.getByTestId('todo-edit-title')).toHaveValue('自分が入力したタイトル');
        await expect(canvas.getByTestId('todo-edit-description')).toHaveValue('他の人が書いた説明');
    },
};
