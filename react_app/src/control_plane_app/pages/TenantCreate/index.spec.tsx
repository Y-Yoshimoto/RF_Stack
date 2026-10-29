// テナント作成画面のテスト (viewer には出さない・事前チェック・一時パスワードのダイアログ・502 の誘導)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledKeys, mockFetch, problemReply } from '@/shared/testing/fetch_mock';
import { renderCpScreen } from '@/control_plane_app/testing/render_screen';
import { sampleTenant } from '@/control_plane_app/testing/story_data';
import { CpTenantCreatePage } from '.';

const CREATE_KEY = 'POST /api/v1/cp/tenants';
const SECRET = 'Secret-Temp-1!';
const PROVISIONED = {
    status: 201,
    body: { tenant: sampleTenant({ id: 'new-id', tenant_code: 'acme-1', version: 1 }), initial_admin: { username: 'admin@example.com', temporary_password: SECRET }, provisioning_history_id: 'h1' },
    headers: { ETag: '"1"' },
};

afterEach(() => {
    vi.restoreAllMocks();
});

const renderCreate = (roles?: string[]) => renderCpScreen(<Route path="/cp/tenant-create" element={<CpTenantCreatePage />} />, { path: '/cp/tenant-create', roles });

/**
 * 入力して送信する関数
 * @param {ReturnType<typeof userEvent.setup>} user ユーザー操作
 * @param {string} tenant_code テナントコード
 * @returns {Promise<void>} 送信まで
*/
const fillAndSubmit = async (user: ReturnType<typeof userEvent.setup>, tenant_code: string): Promise<void> => {
    await user.type(screen.getByTestId('tenant-create-tenant-code'), tenant_code);
    await user.type(screen.getByTestId('tenant-create-name'), 'ACME');
    await user.type(screen.getByTestId('tenant-create-email'), 'admin@example.com');
    await user.click(screen.getByTestId('tenant-create-submit'));
};

describe('テナント作成画面', () => {
    it('saas_viewer には、フォームを出さずに NotFound を表示する', () => {
        renderCreate(['saas_viewer']);
        expect(screen.getByTestId('not-found-page')).toBeInTheDocument();
        expect(screen.queryByTestId('tenant-create-form')).toBeNull();
    });

    it('予約語のテナントコードは、API を呼ばずにエラーを表示して欄にフォーカスする', async () => {
        const user = userEvent.setup();
        const spy = mockFetch({});
        renderCreate();
        await fillAndSubmit(user, 'admin');
        expect(await screen.findByText(/予約語/)).toBeInTheDocument();
        expect(screen.getByTestId('tenant-create-tenant-code')).toHaveFocus();
        expect(screen.getByTestId('tenant-create-tenant-code')).toHaveAttribute('aria-invalid', 'true');
        expect(calledKeys(spy)).toEqual([]);
    });

    it('成功すると一時パスワードをダイアログに表示し、閉じると消えて詳細へ移る', async () => {
        const user = userEvent.setup();
        const spy = mockFetch({ [CREATE_KEY]: PROVISIONED });
        renderCreate();
        await fillAndSubmit(user, 'Acme-1');
        const dialog = await screen.findByTestId('credentials-dialog');
        expect(within(dialog).getByTestId('credentials-dialog-password')).toHaveTextContent(SECRET);
        // テナントコードは小文字に整えて送る
        const request = spy.mock.calls[0][0] as Request;
        expect(await request.clone().json()).toMatchObject({ tenant_code: 'acme-1', name: 'ACME', initial_admin: { email: 'admin@example.com' } });
        await user.click(within(dialog).getByTestId('credentials-dialog-close'));
        expect(screen.queryByTestId('credentials-dialog')).toBeNull();
        expect(document.body).not.toHaveTextContent(SECRET);
        expect(await screen.findByTestId('location-probe')).toHaveTextContent('/cp/tenants/new-id');
    });

    it('テナントコードの重複 (409) は、欄のエラーと通知を表示する', async () => {
        const user = userEvent.setup();
        mockFetch({ [CREATE_KEY]: problemReply(409, 'tenant_code_already_exists') });
        renderCreate();
        await fillAndSubmit(user, 'alpha');
        expect(await screen.findByTestId('tenant-create-error')).toHaveAttribute('role', 'alert');
        expect(screen.getByTestId('tenant-create-tenant-code')).toHaveAttribute('aria-invalid', 'true');
        expect(screen.queryByTestId('credentials-dialog')).toBeNull();
    });

    it('払い出しの失敗 (502) は、tenant_id を使って詳細への誘導を表示する', async () => {
        const user = userEvent.setup();
        mockFetch({ [CREATE_KEY]: { status: 502, body: { ...problemReply(502, 'tenant_provisioning_failed').body as object, tenant_id: 'failed-id', step: 'create_realm' } } });
        renderCreate();
        await fillAndSubmit(user, 'alpha');
        const link = await screen.findByTestId('tenant-create-error-detail-link');
        expect(link).toHaveAttribute('href', '/cp/tenants/failed-id');
        await waitFor(() => expect(screen.getByTestId('tenant-create-error-details')).toHaveTextContent('create_realm'));
    });
});
