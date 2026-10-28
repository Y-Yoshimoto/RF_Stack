// 組織一覧画面のテスト (member に変更 UI が無い・表・作成・削除の確認・空・エラー)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledKeys, calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { ORGANIZATION_ID, organizationDetailOf } from '@/main_app/testing/app_test_support';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { SAMPLE_ORGANIZATIONS, SECOND_ORGANIZATION_ID, pageOf } from '@/main_app/testing/story_data';
import { AppOrganizationListPage } from '.';

const LIST_KEY = 'GET /api/v1/organizations';

afterEach(() => {
    vi.restoreAllMocks();
});

const renderList = (replies: Record<string, MockHandler> = {}, roles?: string[]) => {
    const spy = mockFetch({ [LIST_KEY]: { status: 200, body: pageOf(SAMPLE_ORGANIZATIONS) }, ...replies });
    renderAppScreen(<Route path="/alpha/organizations" element={<AppOrganizationListPage />} />, { path: '/alpha/organizations', roles });
    return spy;
};

describe('組織一覧画面', () => {
    it('表に、組織名・作成日時・更新日時を表示し、見出しを th にする', async () => {
        renderList();
        const table = await screen.findByTestId('organization-table');
        expect(within(table).getAllByRole('columnheader').map((header) => header.textContent)).toEqual(['組織名', '作成日時', '更新日時', '操作']);
        expect(screen.getByTestId(`organization-link-${ORGANIZATION_ID}`)).toHaveTextContent('営業部');
        expect(screen.getByTestId(`organization-link-${ORGANIZATION_ID}`)).toHaveAttribute('href', `/alpha/organizations/${ORGANIZATION_ID}`);
        expect(screen.getByTestId('organization-list-count')).toHaveTextContent('2 件を表示');
    });

    it('member には、作成・削除の導線を表示せず、閲覧のみであることを案内する', async () => {
        renderList({}, ['member']);
        const table = await screen.findByTestId('organization-table');
        expect(screen.queryByTestId('organization-list-create')).toBeNull();
        expect(screen.queryByTestId(`organization-delete-${ORGANIZATION_ID}`)).toBeNull();
        expect(within(table).getAllByRole('columnheader').map((header) => header.textContent)).toEqual(['組織名', '作成日時', '更新日時']);
        expect(screen.getByTestId('organization-list-readonly')).toBeInTheDocument();
    });

    it('組織を作成すると、一覧を取り直し、完了を知らせる', async () => {
        const user = userEvent.setup();
        const spy = renderList({ 'POST /api/v1/organizations': { status: 201, body: organizationDetailOf({ id: SECOND_ORGANIZATION_ID, name: '総務部', member_ids: [] }), headers: { ETag: '"1"' } } });
        await user.click(await screen.findByTestId('organization-list-create'));
        const dialog = await screen.findByRole('dialog', { name: '組織を作成' });
        expect(within(dialog).getByTestId('organization-create-name')).toHaveFocus();
        await user.type(within(dialog).getByTestId('organization-create-name'), ' 総務部 ');
        await user.click(within(dialog).getByTestId('organization-create-submit'));
        expect(await screen.findByTestId('organization-list-notice')).toHaveTextContent('組織「総務部」を作成しました');
        const request = calledRequests(spy).find((candidate) => candidate.method === 'POST');
        expect(await request?.json()).toEqual({ name: '総務部' });
        await vi.waitFor(() => expect(calledKeys(spy).filter((key) => key === LIST_KEY)).toHaveLength(2));
        expect(screen.queryByTestId('organization-create-dialog')).toBeNull();
    });

    it('組織名が空なら、エラーを表示して API を呼ばない', async () => {
        const user = userEvent.setup();
        const spy = renderList();
        await user.click(await screen.findByTestId('organization-list-create'));
        await user.click(await screen.findByTestId('organization-create-submit'));
        expect(screen.getByText('組織名を入力してください。')).toBeInTheDocument();
        expect(calledKeys(spy).some((key) => key.startsWith('POST'))).toBe(false);
    });

    it('組織名が重複すると (409)、ダイアログの中に role="alert" で理由を表示する', async () => {
        const user = userEvent.setup();
        renderList({ 'POST /api/v1/organizations': problemReply(409, 'organization_name_already_exists') });
        await user.click(await screen.findByTestId('organization-list-create'));
        await user.type(await screen.findByTestId('organization-create-name'), '営業部');
        await user.click(screen.getByTestId('organization-create-submit'));
        const alert = await within(screen.getByTestId('organization-create-dialog')).findByTestId('organization-create-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(alert).toHaveTextContent('この組織名は既に使われています');
    });

    it('削除は、確認ダイアログを経て If-Match 付きで実行し、一覧から外す', async () => {
        const user = userEvent.setup();
        const spy = renderList({ [`DELETE /api/v1/organizations/${ORGANIZATION_ID}`]: { status: 204 } });
        await user.click(await screen.findByTestId(`organization-delete-${ORGANIZATION_ID}`));
        const dialog = await screen.findByRole('dialog', { name: '組織を削除しますか？' });
        expect(dialog).toHaveTextContent('営業部');
        expect(within(dialog).getByTestId('organization-delete-dialog-cancel')).toHaveFocus();
        expect(calledKeys(spy).some((key) => key.startsWith('DELETE'))).toBe(false);
        await user.click(within(dialog).getByTestId('organization-delete-dialog-confirm'));
        expect(await screen.findByTestId('organization-list-notice')).toHaveTextContent('組織「営業部」を削除しました');
        expect(calledRequests(spy).find((candidate) => candidate.method === 'DELETE')?.headers.get('If-Match')).toBe('"3"');
        expect(screen.queryByTestId(`organization-row-${ORGANIZATION_ID}`)).toBeNull();
        expect(screen.getByTestId(`organization-row-${SECOND_ORGANIZATION_ID}`)).toBeInTheDocument();
    });

    it('削除の確認でキャンセルすると、API を呼ばない', async () => {
        const user = userEvent.setup();
        const spy = renderList();
        await user.click(await screen.findByTestId(`organization-delete-${ORGANIZATION_ID}`));
        await user.click(await screen.findByTestId('organization-delete-dialog-cancel'));
        expect(calledKeys(spy).some((key) => key.startsWith('DELETE'))).toBe(false);
        expect(screen.getByTestId(`organization-row-${ORGANIZATION_ID}`)).toBeInTheDocument();
    });

    it('他の操作で更新済み (412) の場合は、削除せずに再読み込みを促す', async () => {
        const user = userEvent.setup();
        renderList({ [`DELETE /api/v1/organizations/${ORGANIZATION_ID}`]: problemReply(412, 'organization_version_conflict') });
        await user.click(await screen.findByTestId(`organization-delete-${ORGANIZATION_ID}`));
        await user.click(await screen.findByTestId('organization-delete-dialog-confirm'));
        const alert = await screen.findByTestId('organization-list-action-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(screen.getByTestId('organization-list-action-error-reload')).toBeInTheDocument();
    });

    it('組織が無ければ空の案内を表示する', async () => {
        renderList({ [LIST_KEY]: { status: 200, body: pageOf([]) } });
        expect(await screen.findByTestId('organization-list-empty')).toHaveTextContent('組織がありません');
    });

    it('取得に失敗すると、role="alert" のエラーを表示する', async () => {
        renderList({ [LIST_KEY]: problemReply(503, 'service_unavailable') });
        const alert = await screen.findByTestId('organization-list-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(screen.getByTestId('organization-list-error-reload')).toBeInTheDocument();
    });
});
