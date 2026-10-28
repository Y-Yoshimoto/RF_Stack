// 組織詳細画面のテスト (member は閲覧のみ・名前変更・メンバーの設定・削除して一覧へ戻る・メンバー名の全ページ取得)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledKeys, calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { ORGANIZATION_ID, OTHER_USER_ID, SELF_USER_ID, organizationDetailOf, organizationOf } from '@/main_app/testing/app_test_support';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { SAMPLE_USERS, THIRD_USER_ID, pageOf } from '@/main_app/testing/story_data';
import { AppOrganizationDetailPage } from '.';

const DETAIL_KEY = `GET /api/v1/organizations/${ORGANIZATION_ID}`;
const USERS_KEY = 'GET /api/v1/users';

afterEach(() => {
    vi.restoreAllMocks();
});

const renderDetail = (replies: Record<string, MockHandler> = {}, roles?: string[]) => {
    const spy = mockFetch({
        [DETAIL_KEY]: { status: 200, body: organizationDetailOf({ member_ids: [SELF_USER_ID, OTHER_USER_ID] }), headers: { ETag: '"3"' } },
        [USERS_KEY]: { status: 200, body: pageOf(SAMPLE_USERS) },
        ...replies,
    });
    renderAppScreen(
        <>
            <Route path="/alpha/organizations/:organizationId" element={<AppOrganizationDetailPage />} />
            <Route path="/alpha/organizations" element={<p data-testid="organization-list-stub">一覧</p>} />
        </>,
        { path: `/alpha/organizations/${ORGANIZATION_ID}`, roles },
    );
    return spy;
};

describe('組織詳細画面', () => {
    it('member には、メンバーの名前を一覧で表示し、変更の UI を表示しない', async () => {
        renderDetail({}, ['member']);
        await screen.findByTestId('organization-members-list');
        expect(screen.getByTestId(`organization-member-${SELF_USER_ID}`)).toHaveTextContent('Hanako Admin');
        expect(screen.getByTestId(`organization-member-${OTHER_USER_ID}`)).toHaveTextContent('Taro Yamada');
        expect(screen.getByTestId('organization-info-name')).toHaveTextContent('営業部');
        expect(screen.queryByTestId('organization-rename-form')).toBeNull();
        expect(screen.queryByTestId('organization-members-select')).toBeNull();
        expect(screen.queryByTestId('organization-members-save')).toBeNull();
        expect(screen.queryByTestId('organization-delete')).toBeNull();
        expect(screen.getByTestId('organization-detail-readonly')).toBeInTheDocument();
    });

    it('ユーザー一覧が複数ページに渡っても、全ページを取得してメンバーの名前を表示する', async () => {
        const spy = renderDetail({
            [USERS_KEY]: (request) => (new URL(request.url).searchParams.get('cursor') === null
                ? { status: 200, body: pageOf(SAMPLE_USERS.slice(0, 1), 'next-1') }
                : { status: 200, body: pageOf(SAMPLE_USERS.slice(1), null) }),
        }, ['member']);
        await screen.findByTestId('organization-members-list');
        expect(screen.getByTestId(`organization-member-${OTHER_USER_ID}`)).toHaveTextContent('Taro Yamada');
        expect(calledKeys(spy).filter((key) => key === USERS_KEY)).toHaveLength(2);
    });

    it('一覧に無いメンバーは、不明なユーザーとして表示する', async () => {
        renderDetail({ [DETAIL_KEY]: { status: 200, body: organizationDetailOf({ member_ids: ['01900000-0000-7000-8000-0000000000ff'] }), headers: { ETag: '"3"' } } }, ['member']);
        expect(await screen.findByTestId('organization-members-list')).toHaveTextContent('不明なユーザー');
    });

    it('メンバーがいなければ、その旨を表示する', async () => {
        renderDetail({ [DETAIL_KEY]: { status: 200, body: organizationDetailOf({ member_ids: [] }), headers: { ETag: '"3"' } } }, ['member']);
        expect(await screen.findByTestId('organization-members-empty')).toBeInTheDocument();
    });

    it('組織名を変更すると、If-Match 付きで更新し、完了を知らせる', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ [`PATCH /api/v1/organizations/${ORGANIZATION_ID}`]: { status: 200, body: organizationOf({ name: '第一営業部', version: 4 }), headers: { ETag: '"4"' } } });
        const input = await screen.findByTestId('organization-rename-name');
        expect(screen.getByTestId('organization-rename-submit')).toBeDisabled();
        await user.clear(input);
        await user.type(input, '第一営業部');
        await user.click(screen.getByTestId('organization-rename-submit'));
        expect(await screen.findByTestId('organization-detail-notice')).toHaveTextContent('組織名を変更しました');
        const request = calledRequests(spy).find((candidate) => candidate.method === 'PATCH');
        expect(request?.headers.get('If-Match')).toBe('"3"');
        expect(await request?.json()).toEqual({ name: '第一営業部' });
        expect(screen.getByTestId('organization-detail-title')).toHaveTextContent('第一営業部');
    });

    it('メンバーを選び直して保存すると、ユーザー ID の全件で置き換える', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({
            [`PUT /api/v1/organizations/${ORGANIZATION_ID}/members`]: { status: 200, body: organizationDetailOf({ version: 4, member_ids: [SELF_USER_ID, OTHER_USER_ID, THIRD_USER_ID] }), headers: { ETag: '"4"' } },
        });
        await screen.findByTestId('organization-members-select');
        expect(screen.getByTestId('organization-members-save')).toBeDisabled();
        await user.click(screen.getByRole('combobox', { name: 'メンバー' }));
        await user.click(await screen.findByRole('option', { name: /Jiro Suzuki/ }));
        await user.click(screen.getByTestId('organization-members-save'));
        expect(await screen.findByTestId('organization-detail-notice')).toHaveTextContent('メンバーを保存しました');
        const request = calledRequests(spy).find((candidate) => candidate.method === 'PUT');
        expect(request?.headers.get('If-Match')).toBe('"3"');
        expect(((await request?.json()) as { user_ids: string[] }).user_ids.sort()).toEqual([SELF_USER_ID, OTHER_USER_ID, THIRD_USER_ID].sort());
    });

    it('存在しないユーザーが含まれる (422) と、メンバーの再選択を促す', async () => {
        const user = userEvent.setup();
        renderDetail({ [`PUT /api/v1/organizations/${ORGANIZATION_ID}/members`]: problemReply(422, 'invalid_organization_members') });
        await screen.findByTestId('organization-members-select');
        await user.click(screen.getByRole('combobox', { name: 'メンバー' }));
        await user.click(await screen.findByRole('option', { name: /Jiro Suzuki/ }));
        await user.click(screen.getByTestId('organization-members-save'));
        expect(await screen.findByTestId('organization-detail-action-error')).toHaveTextContent('メンバーに指定できないユーザー');
    });

    it('削除は、確認ダイアログを経て実行し、一覧へ戻る', async () => {
        const user = userEvent.setup();
        const spy = renderDetail({ [`DELETE /api/v1/organizations/${ORGANIZATION_ID}`]: { status: 204 } });
        await user.click(await screen.findByTestId('organization-delete'));
        const dialog = await screen.findByRole('dialog', { name: '組織を削除しますか？' });
        expect(calledKeys(spy).some((key) => key.startsWith('DELETE'))).toBe(false);
        await user.click(within(dialog).getByTestId('organization-delete-dialog-confirm'));
        expect(await screen.findByTestId('organization-list-stub')).toBeInTheDocument();
        expect(calledRequests(spy).find((candidate) => candidate.method === 'DELETE')?.headers.get('If-Match')).toBe('"3"');
    });

    it('組織が見つからない場合は、エラーを表示する', async () => {
        renderDetail({ [DETAIL_KEY]: problemReply(404, 'organization_not_found') });
        expect(await screen.findByTestId('organization-detail-error')).toHaveTextContent('組織が見つかりません');
    });
});
