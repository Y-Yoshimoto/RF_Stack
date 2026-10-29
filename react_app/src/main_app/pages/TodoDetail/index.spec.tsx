// ToDo 詳細・編集画面のテスト (permissions による項目単位の出し分け・更新の送信内容・412 / 403 の再読み込み・公開先組織の再指定・削除の確認・アクティビティ)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { TodoDetail } from '@/main_app/api/contract';
import { calledKeys, calledRequests, mockFetch, problemReply, type MockReply } from '@/shared/testing/fetch_mock';
import { ORGANIZATION_ID, OTHER_USER_ID, SELF_USER_ID } from '@/main_app/testing/app_test_support';
import { ACTIVITIES_KEY, DETAIL_KEY, PATCH_KEY, detailReply, renderTodoDetail } from '@/main_app/testing/todo_detail_support';
import { THIRD_USER_ID } from '@/main_app/testing/story_data';
import { ASSIGNEE_TODO_PERMISSIONS, TODO_ID, activityOf, activityPageOf } from '@/main_app/testing/todo_test_data';

const NO_PERMISSIONS = { can_edit_fields: false, can_change_status: false, can_change_visibility: false, can_change_assignees: false, can_delete: false, can_comment: true, can_edit_checklist: false, can_check_checklist: false };

afterEach(() => {
    vi.restoreAllMocks();
});

const renderDetail = renderTodoDetail;

const updated = (overrides: Partial<TodoDetail>): MockReply => detailReply({ version: 4, ...overrides });
const lastRequest = (spy: ReturnType<typeof mockFetch>, method: string) => calledRequests(spy).filter((request) => request.method === method).at(-1);

describe('ToDo 詳細画面: 権限による出し分け', () => {
    it('作成者・tenant_admin (すべて可) には、すべての項目の編集・保存・削除を出す', async () => {
        renderDetail();
        expect(await screen.findByTestId('todo-fields-form')).toHaveAttribute('data-editable', 'true');
        expect(screen.getByTestId('todo-edit-title')).toBeEnabled();
        expect(screen.getByTestId('todo-edit-due-date')).toBeEnabled();
        expect(screen.getByTestId('todo-fields-submit')).toBeInTheDocument();
        expect(screen.getByTestId('todo-audience-submit')).toBeInTheDocument();
        expect(screen.getByTestId('todo-assignees-submit')).toBeInTheDocument();
        expect(screen.getByTestId('todo-detail-delete')).toBeInTheDocument();
        expect(screen.getByTestId('todo-status-in_progress')).toBeEnabled();
    });

    it('担当者のみ (ステータスと担当者だけ可) には、項目・閲覧範囲を無効にして理由を示し、保存と削除を出さない', async () => {
        renderDetail({ detail: { permissions: ASSIGNEE_TODO_PERMISSIONS }, roles: ['member'] });
        expect(await screen.findByTestId('todo-fields-form')).toHaveAttribute('data-editable', 'false');
        expect(screen.getByTestId('todo-fields-readonly')).toHaveTextContent('作成者とテナント管理者だけ');
        expect(screen.getByTestId('todo-edit-title')).toBeDisabled();
        expect(screen.getByTestId('todo-edit-description')).toBeDisabled();
        expect(screen.getByTestId('todo-edit-due-date')).toBeDisabled();
        expect(screen.queryByTestId('todo-fields-submit')).toBeNull();
        expect(screen.getByTestId('todo-audience-readonly')).toBeInTheDocument();
        expect(screen.getByTestId('todo-edit-audience-visibility-tenant')).toBeDisabled();
        expect(screen.queryByTestId('todo-audience-submit')).toBeNull();
        expect(screen.queryByTestId('todo-detail-delete')).toBeNull();
        // ステータスと担当者は変えられる
        expect(screen.getByTestId('todo-status-done')).toBeEnabled();
        expect(screen.getByTestId('todo-assignees-submit')).toBeInTheDocument();
    });

    it('権限がまったく無い (閲覧のみ) なら、ステータス・担当者も操作できず、理由を示す', async () => {
        renderDetail({ detail: { permissions: NO_PERMISSIONS }, roles: ['member'] });
        await screen.findByTestId('todo-fields-form');
        expect(screen.getByTestId('todo-status-done')).toBeDisabled();
        expect(screen.getByTestId('todo-status-readonly')).toBeInTheDocument();
        expect(screen.getByTestId('todo-assignees-readonly')).toBeInTheDocument();
        expect(screen.queryByTestId('todo-assignees-submit')).toBeNull();
        expect(screen.getByRole('combobox', { name: '担当者' })).toBeDisabled();
    });

    it('閲覧できない ToDo (404) は、存在を明かさずに見つからないとだけ表示する', async () => {
        renderDetail({ replies: { [DETAIL_KEY]: problemReply(404, 'todo_not_found') } });
        const alert = await screen.findByTestId('todo-detail-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(alert).toHaveTextContent('ToDo が見つかりません');
        expect(screen.queryByTestId('todo-fields-form')).toBeNull();
    });
});

describe('ToDo 詳細画面: 更新', () => {
    it('変更が無い間は保存できず、タイトルを変えると変わった項目だけを If-Match 付きで送る', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ replies: { [PATCH_KEY]: updated({ title: '新しいタイトル' }) } });
        await screen.findByTestId('todo-fields-form');
        expect(screen.getByTestId('todo-fields-submit')).toBeDisabled();
        await user.clear(screen.getByTestId('todo-edit-title'));
        await user.type(screen.getByTestId('todo-edit-title'), '新しいタイトル');
        await user.click(screen.getByTestId('todo-fields-submit'));
        expect(await screen.findByTestId('todo-detail-notice')).toHaveTextContent('変更を保存しました');
        const request = lastRequest(spy, 'PATCH');
        expect(request?.headers.get('If-Match')).toBe('"3"');
        expect(await request?.json()).toEqual({ title: '新しいタイトル' });
        expect(screen.getByTestId('todo-detail-title')).toHaveTextContent('新しいタイトル');
        // 変更の後はアクティビティを取り直す
        await vi.waitFor(() => expect(calledKeys(spy).filter((key) => key === ACTIVITIES_KEY)).toHaveLength(2));
    });

    it('タイトルを空にして保存すると、送信せずにエラーを表示する', async () => {
        const user = userEvent.setup();
        const spy = renderDetail();
        await screen.findByTestId('todo-fields-form');
        await user.clear(screen.getByTestId('todo-edit-title'));
        await user.click(screen.getByTestId('todo-fields-submit'));
        expect(await screen.findByText('タイトルを入力してください。')).toBeInTheDocument();
        expect(lastRequest(spy, 'PATCH')).toBeUndefined();
    });

    it('担当者は、ステータスだけを status で送って変更できる', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ detail: { permissions: ASSIGNEE_TODO_PERMISSIONS }, roles: ['member'], replies: { [PATCH_KEY]: updated({ status: 'done', permissions: ASSIGNEE_TODO_PERMISSIONS }) } });
        await screen.findByTestId('todo-status-control');
        await user.click(screen.getByTestId('todo-status-done'));
        expect(await screen.findByTestId('todo-detail-notice')).toHaveTextContent('ステータスを「完了」に変更しました');
        expect(await lastRequest(spy, 'PATCH')?.json()).toEqual({ status: 'done' });
        expect(screen.getByTestId('todo-status-done')).toHaveAttribute('aria-pressed', 'true');
    });

    it('閲覧範囲を tenant に変えて保存すると、visibility だけを送り、組織の選択欄は消える', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ replies: { [PATCH_KEY]: updated({ visibility: 'tenant', effective_visibility: 'tenant', organizations: [] }) } });
        await screen.findByTestId('todo-audience-form');
        expect(screen.getByTestId(`todo-edit-audience-organization-${ORGANIZATION_ID}`)).toBeChecked();
        await user.click(screen.getByTestId('todo-edit-audience-visibility-tenant'));
        expect(screen.queryByTestId('todo-edit-audience-organizations')).toBeNull();
        await user.click(screen.getByTestId('todo-audience-submit'));
        expect(await screen.findByTestId('todo-detail-notice')).toHaveTextContent('閲覧範囲を保存しました');
        expect(await lastRequest(spy, 'PATCH')?.json()).toEqual({ visibility: 'tenant' });
    });

    it('閲覧範囲を organization にして組織を 1 つも選ばないと、送信せずにエラーにする', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ detail: { visibility: 'private', effective_visibility: 'private', organizations: [] } });
        await screen.findByTestId('todo-audience-form');
        await user.click(screen.getByTestId('todo-edit-audience-visibility-organization'));
        await user.click(screen.getByTestId('todo-audience-submit'));
        expect(await screen.findByTestId('todo-edit-audience-organizations-help')).toHaveTextContent('公開先の組織を 1 つ以上選んでください。');
        expect(lastRequest(spy, 'PATCH')).toBeUndefined();
    });

    it('公開先の組織がすべて削除されている場合は再指定を促し、組織を選び直すと organization_ids を送る', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ detail: { visibility: 'organization', effective_visibility: 'private', organizations: [] }, replies: { [PATCH_KEY]: updated({}) } });
        expect(await screen.findByTestId('todo-reselect-notice')).toHaveTextContent('公開先に指定していた組織がすべて削除された');
        // 変更が無い間は保存できない
        expect(screen.getByTestId('todo-audience-submit')).toBeDisabled();
        await user.click(await screen.findByTestId(`todo-edit-audience-organization-${ORGANIZATION_ID}`));
        await user.click(screen.getByTestId('todo-audience-submit'));
        await vi.waitFor(() => expect(lastRequest(spy, 'PATCH')).toBeDefined());
        expect(await lastRequest(spy, 'PATCH')?.json()).toEqual({ visibility: 'organization', organization_ids: [ORGANIZATION_ID] });
    });

    it('担当者を置き換えると、user_ids の全件を PUT で送る', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ replies: { [`PUT /api/v1/todos/${TODO_ID}/assignees`]: updated({ assignees: [] }) } });
        await screen.findByTestId('todo-assignees-form');
        expect(screen.getByTestId('todo-assignees-submit')).toBeDisabled();
        await user.click(within(screen.getByTestId(`todo-edit-assignees-chip-${OTHER_USER_ID}`)).getByTestId('CancelIcon'));
        await user.click(screen.getByTestId('todo-assignees-submit'));
        expect(await screen.findByTestId('todo-detail-notice')).toHaveTextContent('担当者を保存しました');
        const request = lastRequest(spy, 'PUT');
        expect(request?.headers.get('If-Match')).toBe('"3"');
        expect(await request?.json()).toEqual({ user_ids: [] });
    });
});

describe('ToDo 詳細画面: 失敗と再読み込み', () => {
    it('412 で最新の内容を取り直せなかったときは、role="alert" で再読み込みを促し、再読み込みで詳細を取り直す', async () => {
        const user = userEvent.setup();
        let detail_calls = 0;
        const spy = renderDetail({
            replies: {
                [PATCH_KEY]: problemReply(412, 'todo_version_conflict'),
                // 1 回目 (表示) は成功、2 回目 (自動の再表示) は失敗、3 回目 (手動の再読み込み) は成功
                [DETAIL_KEY]: () => {
                    detail_calls += 1;
                    return detail_calls === 2 ? problemReply(503, 'service_unavailable') : detailReply();
                },
            },
        });
        await screen.findByTestId('todo-fields-form');
        await user.clear(screen.getByTestId('todo-edit-title'));
        await user.type(screen.getByTestId('todo-edit-title'), 'x');
        await user.click(screen.getByTestId('todo-fields-submit'));
        const alert = await screen.findByTestId('todo-detail-action-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(alert).toHaveAttribute('data-error-code', 'todo_version_conflict');
        expect(alert).toHaveTextContent('他の操作で更新されています');
        expect(screen.queryByTestId('todo-detail-refreshed')).toBeNull();
        await user.click(screen.getByTestId('todo-detail-action-error-reload'));
        await vi.waitFor(() => expect(calledKeys(spy).filter((key) => key === DETAIL_KEY)).toHaveLength(3));
        expect(await screen.findByTestId('todo-fields-form')).toBeInTheDocument();
        expect(screen.queryByTestId('todo-detail-action-error')).toBeNull();
    });

    it('API の 403 todo_operation_forbidden (権限が変わった) では、最新の内容を取り直す。取り直せなければ再読み込みを促す', async () => {
        const user = userEvent.setup();
        const forbidden = problemReply(403, 'todo_operation_forbidden');
        let detail_calls = 0;
        renderDetail({
            detail: { permissions: ASSIGNEE_TODO_PERMISSIONS },
            roles: ['member'],
            replies: {
                [PATCH_KEY]: { ...forbidden, body: { ...(forbidden.body as object), operation: 'change_status' } },
                [DETAIL_KEY]: () => {
                    detail_calls += 1;
                    return detail_calls === 1 ? detailReply({ permissions: ASSIGNEE_TODO_PERMISSIONS }) : problemReply(503, 'service_unavailable');
                },
            },
        });
        await screen.findByTestId('todo-status-control');
        await user.click(screen.getByTestId('todo-status-done'));
        const alert = await screen.findByTestId('todo-detail-action-error');
        expect(alert).toHaveTextContent('ステータスの変更はできません');
        expect(alert).toHaveTextContent('再読み込みして');
        expect(screen.getByTestId('todo-detail-action-error-reload')).toBeInTheDocument();
    });

    it('担当者の不正 (422 invalid_todo_assignees) は、再読み込みではなく入力のやり直しを案内する', async () => {
        const user = userEvent.setup();
        renderDetail({ replies: { [`PUT /api/v1/todos/${TODO_ID}/assignees`]: problemReply(422, 'invalid_todo_assignees') } });
        await screen.findByTestId('todo-assignees-form');
        await user.click(within(screen.getByTestId(`todo-edit-assignees-chip-${OTHER_USER_ID}`)).getByTestId('CancelIcon'));
        await user.click(screen.getByTestId('todo-assignees-submit'));
        const alert = await screen.findByTestId('todo-detail-action-error');
        expect(alert).toHaveTextContent('担当者に指定できないユーザーが含まれています');
        expect(screen.queryByTestId('todo-detail-action-error-reload')).toBeNull();
    });
});

describe('ToDo 詳細画面: 削除', () => {
    it('削除は確認ダイアログを経由し、初期フォーカスは「キャンセル」。キャンセルでは削除しない', async () => {
        const user = userEvent.setup();
        const spy = renderDetail();
        await screen.findByTestId('todo-detail-delete');
        await user.click(screen.getByTestId('todo-detail-delete'));
        const dialog = await screen.findByRole('dialog', { name: 'ToDo を削除しますか' });
        expect(dialog).toHaveTextContent('見積もりを作る');
        await vi.waitFor(() => expect(screen.getByTestId('todo-delete-dialog-cancel')).toHaveFocus());
        await user.click(screen.getByTestId('todo-delete-dialog-cancel'));
        await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        expect(lastRequest(spy, 'DELETE')).toBeUndefined();
    });

    it('確認すると If-Match 付きで削除し、一覧へ遷移する', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ replies: { [`DELETE /api/v1/todos/${TODO_ID}`]: { status: 204 } } });
        await screen.findByTestId('todo-detail-delete');
        await user.click(screen.getByTestId('todo-detail-delete'));
        await user.click(await screen.findByTestId('todo-delete-dialog-confirm'));
        expect(await screen.findByTestId('location-probe')).toHaveTextContent('/alpha/todos');
        expect(lastRequest(spy, 'DELETE')?.headers.get('If-Match')).toBe('"3"');
    });

    it('削除が 412 で失敗すると、ダイアログの中に再読み込みを促すエラーを出す', async () => {
        const user = userEvent.setup();
        renderDetail({ replies: { [`DELETE /api/v1/todos/${TODO_ID}`]: problemReply(412, 'todo_version_conflict') } });
        await screen.findByTestId('todo-detail-delete');
        await user.click(screen.getByTestId('todo-detail-delete'));
        await user.click(await screen.findByTestId('todo-delete-dialog-confirm'));
        const alert = await screen.findByTestId('todo-delete-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(within(screen.getByRole('dialog')).getByTestId('todo-delete-error-reload')).toBeInTheDocument();
    });
});

describe('ToDo 詳細画面: アクティビティ', () => {
    it('時系列 (新しい順) で、作成・ステータス変更・担当者の変更・閲覧範囲の変更を文にして表示する', async () => {
        const items = [
            activityOf({ id: 'a4', action: 'visibility_changed', payload: { changes: { visibility: { before: 'private', after: 'organization' } }, organization_ids: { added: [ORGANIZATION_ID], removed: [] } }, created_at: '2026-10-04T00:00:00Z' }),
            activityOf({ id: 'a3', action: 'assignees_changed', payload: { added: [OTHER_USER_ID], removed: [] }, created_at: '2026-10-03T00:00:00Z' }),
            activityOf({ id: 'a2', action: 'status_changed', payload: { changes: { status: { before: 'open', after: 'done' } } }, created_at: '2026-10-02T00:00:00Z' }),
            activityOf({ id: 'a1', action: 'created', payload: { values: {} }, created_at: '2026-10-01T00:00:00Z' }),
        ];
        const users = { [SELF_USER_ID]: { display_name: 'Hanako Suzuki', is_active: true }, [OTHER_USER_ID]: { display_name: 'Taro Yamada', is_active: true } };
        renderDetail({ replies: { [ACTIVITIES_KEY]: { status: 200, body: activityPageOf(items, users) } } });
        await userEvent.click(await screen.findByTestId('todo-tab-activities'));
        const list = await screen.findByTestId('todo-activities-list');
        expect(within(list).getAllByRole('listitem')).toHaveLength(4);
        expect(screen.getByTestId('todo-activity-a4')).toHaveTextContent('閲覧範囲: 非公開 → 組織');
        expect(screen.getByTestId('todo-activity-a4')).toHaveTextContent('公開先の組織を追加: 営業部');
        expect(screen.getByTestId('todo-activity-a3')).toHaveTextContent('担当者を追加: Taro Yamada');
        expect(screen.getByTestId('todo-activity-a2')).toHaveTextContent('ステータス: 未着手 → 完了');
        expect(screen.getByTestId('todo-activity-a1')).toHaveTextContent('ToDo を作成しました');
        expect(screen.getByTestId('todo-activity-actor-a1')).toHaveTextContent('Hanako Suzuki');
    });

    it('担当者から外れたユーザー・無効なユーザーも名前で表示し、無効は「(無効)」と文字で示す。引けないユーザーは「不明なユーザー」', async () => {
        const unknown_id = '01900000-0000-7000-8000-00000000a999';
        const items = [
            activityOf({ id: 'a2', action: 'assignees_changed', actor_id: THIRD_USER_ID, actor_display_name: 'Jiro Suzuki', payload: { added: [SELF_USER_ID], removed: [OTHER_USER_ID, unknown_id] }, created_at: '2026-10-02T00:00:00Z' }),
            activityOf({ id: 'a1', action: 'created', actor_id: unknown_id, actor_display_name: null, payload: { values: { assignee_ids: [OTHER_USER_ID] } }, created_at: '2026-10-01T00:00:00Z' }),
        ];
        const users = {
            [SELF_USER_ID]: { display_name: 'Hanako Suzuki', is_active: true },
            [OTHER_USER_ID]: { display_name: 'Taro Yamada', is_active: false },
            [THIRD_USER_ID]: { display_name: 'Jiro Suzuki', is_active: false },
        };
        const spy = renderDetail({ replies: { [ACTIVITIES_KEY]: { status: 200, body: activityPageOf(items, users) } } });
        await screen.findByTestId('todo-activities-list');
        const a2 = screen.getByTestId('todo-activity-a2');
        expect(a2).toHaveTextContent('担当者を追加: Hanako Suzuki');
        expect(a2).toHaveTextContent('担当者を削除: Taro Yamada (無効)、不明なユーザー');
        expect(screen.getByTestId('todo-activity-actor-a2')).toHaveTextContent('Jiro Suzuki (無効)');
        expect(screen.getByTestId('todo-activity-a1')).toHaveTextContent('担当者: Taro Yamada (無効)');
        expect(screen.getByTestId('todo-activity-actor-a1')).toHaveTextContent('不明なユーザー');
        // 名前の解決のために、ユーザーを ID 指定で取りに行かない
        expect(calledRequests(spy).some((request) => new URL(request.url).searchParams.get('ids') !== null)).toBe(false);
    });

    it('アクティビティが無ければ、空の案内を表示する', async () => {
        renderDetail();
        expect(await screen.findByTestId('todo-activities-empty')).toBeInTheDocument();
    });
});
