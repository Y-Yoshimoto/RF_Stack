// ユーザー詳細・編集画面のテスト (member に変更 UI が無い・ロール/姓名の更新・自分自身の禁止操作が無効・無効化の確認・412)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledKeys, calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { OTHER_USER_ID, SELF_USER_ID, userDetailOf, userOf } from '@/main_app/testing/app_test_support';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { meBodyOf } from '@/main_app/testing/story_data';
import { AppUserDetailPage } from '.';

const ME_KEY = 'GET /api/v1/me';
const detailKey = (user_id: string) => `GET /api/v1/users/${user_id}`;
const patchKey = (user_id: string) => `PATCH /api/v1/users/${user_id}`;

afterEach(() => {
    vi.restoreAllMocks();
});

/**
 * 詳細画面を描画する関数
 * @param {{ user_id?: string; detail?: Record<string, unknown>; replies?: Record<string, MockHandler>; roles?: string[] }} options 対象のユーザー・詳細の本文・追加の応答・ログイン中のロール
 * @returns {ReturnType<typeof mockFetch>} fetch の spy
*/
const renderDetail = ({ user_id = OTHER_USER_ID, detail = {}, replies = {}, roles }: { user_id?: string; detail?: Record<string, unknown>; replies?: Record<string, MockHandler>; roles?: string[] } = {}) => {
    const spy = mockFetch({
        [ME_KEY]: { status: 200, body: meBodyOf(SELF_USER_ID, roles ?? ['tenant_admin']) },
        [detailKey(user_id)]: { status: 200, body: userDetailOf({ id: user_id, version: 3, roles: ['member'], ...detail }), headers: { ETag: '"3"' } },
        ...replies,
    });
    renderAppScreen(<Route path="/alpha/users/:userId" element={<AppUserDetailPage />} />, { path: `/alpha/users/${user_id}`, roles });
    return spy;
};

const UPDATED = { status: 200, body: userOf({ version: 4 }), headers: { ETag: '"4"' } };
/** 更新の応答 (姓・名・ロールを含む UserDetail) を作る関数 */
const updatedOf = (overrides: Record<string, unknown>) => ({ status: 200, body: userDetailOf({ version: 4, ...overrides }), headers: { ETag: '"4"' } });

describe('ユーザー詳細画面', () => {
    it('基本情報 (表示名・メール・ロール・状態・最終ログイン) を表示する', async () => {
        renderDetail({ detail: { roles: ['tenant_admin', 'member'] } });
        expect(await screen.findByTestId('user-info')).toBeInTheDocument();
        expect(screen.getByTestId('user-info-display-name')).toHaveTextContent('Taro Yamada');
        expect(screen.getByTestId('user-info-email')).toHaveTextContent('taro@alpha.example');
        expect(screen.getByTestId('user-info-roles')).toHaveTextContent('テナント管理者');
        expect(screen.getByTestId('user-info-roles')).toHaveTextContent('メンバー');
        expect(screen.getByTestId('user-info-status')).toHaveTextContent('有効');
        expect(screen.getByTestId('user-info-last-login')).toHaveTextContent('未ログイン');
        expect(screen.queryByTestId('user-detail-self')).toBeNull();
    });

    it('member には、編集フォームも有効/無効の操作も表示せず、閲覧のみであることを案内する', async () => {
        renderDetail({ roles: ['member'] });
        await screen.findByTestId('user-info');
        expect(screen.queryByTestId('user-edit')).toBeNull();
        expect(screen.queryByTestId('user-status-panel')).toBeNull();
        expect(screen.queryByTestId('user-deactivate')).toBeNull();
        expect(screen.getByTestId('user-detail-readonly')).toBeInTheDocument();
    });

    it('ロールを変更すると、ETag を If-Match に付けて更新し、応答のロールを反映する (詳細は取り直さない)', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ replies: { [patchKey(OTHER_USER_ID)]: updatedOf({ roles: ['tenant_admin', 'member'] }) } });
        await screen.findByTestId('user-edit');
        expect(screen.getByTestId('user-edit-submit')).toBeDisabled();
        await user.click(screen.getByTestId('user-edit-role-tenant_admin'));
        await user.click(screen.getByTestId('user-edit-submit'));
        expect(await screen.findByTestId('user-detail-notice')).toHaveTextContent('変更を保存しました');
        const request = calledRequests(spy).find((candidate) => candidate.method === 'PATCH');
        expect(request?.headers.get('If-Match')).toBe('"3"');
        expect(await request?.json()).toEqual({ roles: ['member', 'tenant_admin'] });
        // 更新の応答にロールが含まれるため、応答で基本情報を更新し、取り直さない
        await vi.waitFor(() => expect(screen.getByTestId('user-info-roles')).toHaveTextContent('テナント管理者'));
        expect(calledKeys(spy).filter((key) => key === detailKey(OTHER_USER_ID))).toHaveLength(1);
    });

    it('応答のロールが送ったロールと食い違うときだけ、詳細を取り直す', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ replies: { [patchKey(OTHER_USER_ID)]: updatedOf({ roles: ['member'] }) } });
        await screen.findByTestId('user-edit');
        await user.click(screen.getByTestId('user-edit-role-tenant_admin'));
        await user.click(screen.getByTestId('user-edit-submit'));
        await vi.waitFor(() => expect(calledKeys(spy).filter((key) => key === detailKey(OTHER_USER_ID))).toHaveLength(2));
    });

    it('姓名を変更したときだけ、姓名を送る (ロールは送らない)', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ replies: { [patchKey(OTHER_USER_ID)]: UPDATED } });
        await screen.findByTestId('user-edit');
        expect(screen.getByTestId('user-edit-first-name')).toHaveValue('Taro');
        expect(screen.getByTestId('user-edit-last-name')).toHaveValue('Yamada');
        await user.clear(screen.getByTestId('user-edit-first-name'));
        await user.type(screen.getByTestId('user-edit-first-name'), 'Tarou');
        await user.click(screen.getByTestId('user-edit-submit'));
        await screen.findByTestId('user-detail-notice');
        const request = calledRequests(spy).find((candidate) => candidate.method === 'PATCH');
        expect(await request?.json()).toEqual({ first_name: 'Tarou', last_name: 'Yamada' });
    });

    it('姓名の初期値は詳細の first_name / last_name から取り、表示名の分割に頼らない', async () => {
        renderDetail({ detail: { display_name: 'Yamada Taro (営業)', first_name: 'Taro', last_name: 'Yamada' } });
        await screen.findByTestId('user-edit');
        expect(screen.getByTestId('user-edit-first-name')).toHaveValue('Taro');
        expect(screen.getByTestId('user-edit-last-name')).toHaveValue('Yamada');
    });

    it('姓名が null (未同期・未設定) なら空欄で始め、ロールだけの変更では姓名を送らない', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ detail: { first_name: null, last_name: null }, replies: { [patchKey(OTHER_USER_ID)]: updatedOf({ first_name: null, last_name: null, roles: ['tenant_admin', 'member'] }) } });
        await screen.findByTestId('user-edit');
        expect(screen.getByTestId('user-edit-first-name')).toHaveValue('');
        expect(screen.getByTestId('user-edit-last-name')).toHaveValue('');
        await user.click(screen.getByTestId('user-edit-role-tenant_admin'));
        await user.click(screen.getByTestId('user-edit-submit'));
        await screen.findByTestId('user-detail-notice');
        const request = calledRequests(spy).find((candidate) => candidate.method === 'PATCH');
        expect(await request?.json()).toEqual({ roles: ['member', 'tenant_admin'] });
    });

    it('姓名が null のとき、片方だけ入力して保存しようとすると、もう一方のエラーを表示して API を呼ばない', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ detail: { first_name: null, last_name: null } });
        await screen.findByTestId('user-edit');
        await user.type(screen.getByTestId('user-edit-first-name'), 'Taro');
        await user.click(screen.getByTestId('user-edit-submit'));
        expect(screen.getByText('姓を入力してください。')).toBeInTheDocument();
        expect(calledKeys(spy).some((key) => key.startsWith('PATCH'))).toBe(false);
    });

    it('姓名を変更して保存すると、応答の姓名を入力欄に反映する', async () => {
        const user = userEvent.setup();
        renderDetail({ replies: { [patchKey(OTHER_USER_ID)]: updatedOf({ display_name: 'Tarou Yamada', first_name: 'Tarou', last_name: 'Yamada' }) } });
        await screen.findByTestId('user-edit');
        await user.clear(screen.getByTestId('user-edit-first-name'));
        await user.type(screen.getByTestId('user-edit-first-name'), 'Tarou');
        await user.click(screen.getByTestId('user-edit-submit'));
        await screen.findByTestId('user-detail-notice');
        expect(screen.getByTestId('user-info-display-name')).toHaveTextContent('Tarou Yamada');
        expect(screen.getByTestId('user-edit-first-name')).toHaveValue('Tarou');
        expect(screen.getByTestId('user-edit-submit')).toBeDisabled();
    });

    it('姓名を空にすると、エラーを表示してフォーカスし、API を呼ばない', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ replies: { [patchKey(OTHER_USER_ID)]: UPDATED } });
        await screen.findByTestId('user-edit');
        await user.clear(screen.getByTestId('user-edit-last-name'));
        await user.click(screen.getByTestId('user-edit-submit'));
        expect(screen.getByText('姓を入力してください。')).toBeInTheDocument();
        expect(screen.getByTestId('user-edit-last-name')).toHaveFocus();
        expect(calledKeys(spy).some((key) => key.startsWith('PATCH'))).toBe(false);
    });

    it('自分自身には、無効化と tenant_admin の解除を無効にして理由を表示する (API を呼ばない)', async () => {
        const spy = renderDetail({ user_id: SELF_USER_ID, detail: { roles: ['tenant_admin', 'member'] }, replies: { [patchKey(SELF_USER_ID)]: UPDATED } });
        await screen.findByTestId('user-edit');
        expect(screen.getByTestId('user-detail-self')).toHaveTextContent('あなた');
        expect(screen.getByTestId('user-deactivate')).toBeDisabled();
        expect(screen.getByTestId('user-deactivate')).toHaveAccessibleDescription(/自分自身は無効にできません/);
        expect(screen.getByTestId('user-deactivate-self-reason')).toBeInTheDocument();
        const admin_checkbox = screen.getByTestId('user-edit-role-tenant_admin');
        expect(admin_checkbox).toBeDisabled();
        expect(admin_checkbox).toBeChecked();
        expect(admin_checkbox).toHaveAccessibleDescription(/解除できません/);
        // メンバーなど、他のロールの変更は可能
        expect(screen.getByTestId('user-edit-role-member')).toBeEnabled();
        expect(calledKeys(spy).some((key) => key.startsWith('PATCH'))).toBe(false);
    });

    it('他のユーザーの無効化は、確認ダイアログを経て is_active: false を送る', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ replies: { [patchKey(OTHER_USER_ID)]: UPDATED } });
        await user.click(await screen.findByTestId('user-deactivate'));
        const dialog = await screen.findByRole('dialog', { name: 'ユーザーを無効にしますか？' });
        // 初期フォーカスは安全側のキャンセル
        expect(within(dialog).getByTestId('user-deactivate-dialog-cancel')).toHaveFocus();
        expect(calledKeys(spy).some((key) => key.startsWith('PATCH'))).toBe(false);
        await user.click(within(dialog).getByTestId('user-deactivate-dialog-confirm'));
        expect(await screen.findByTestId('user-detail-notice')).toHaveTextContent('ユーザーを無効にしました');
        const request = calledRequests(spy).find((candidate) => candidate.method === 'PATCH');
        expect(await request?.json()).toEqual({ is_active: false });
    });

    it('無効なユーザーは、「有効にする」で再有効化できる', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ detail: { is_active: false }, replies: { [patchKey(OTHER_USER_ID)]: UPDATED } });
        await user.click(await screen.findByTestId('user-reactivate'));
        await screen.findByTestId('user-detail-notice');
        const request = calledRequests(spy).find((candidate) => candidate.method === 'PATCH');
        expect(await request?.json()).toEqual({ is_active: true });
    });

    it('他の操作で更新済み (412) の場合は、role="alert" で再読み込みを促し、押すと取り直す', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ replies: { [patchKey(OTHER_USER_ID)]: problemReply(412, 'user_version_conflict') } });
        await user.click(await screen.findByTestId('user-edit-role-tenant_admin'));
        await user.click(screen.getByTestId('user-edit-submit'));
        const alert = await screen.findByTestId('user-detail-action-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(alert).toHaveTextContent('他の操作で更新されています');
        await user.click(screen.getByTestId('user-detail-action-error-reload'));
        await vi.waitFor(() => expect(calledKeys(spy).filter((key) => key === detailKey(OTHER_USER_ID))).toHaveLength(2));
        await vi.waitFor(() => expect(screen.queryByTestId('user-detail-action-error')).toBeNull());
    });

    it('ユーザーが見つからない場合は、エラーを表示する', async () => {
        renderDetail({ replies: { [detailKey(OTHER_USER_ID)]: problemReply(404, 'user_not_found') } });
        const alert = await screen.findByTestId('user-detail-error');
        expect(alert).toHaveTextContent('ユーザーが見つかりません');
        expect(screen.queryByTestId('user-edit')).toBeNull();
    });
});
