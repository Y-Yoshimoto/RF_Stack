// テナント一覧画面のテスト (viewer に作成の導線が無い・表・絞り込み・さらに読み込む・空・エラー)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import { renderCpScreen } from '@/control_plane_app/testing/render_screen';
import { SAMPLE_LIST_ITEMS, sampleListItem } from '@/control_plane_app/testing/story_data';
import { CpTenantListPage } from '.';

const LIST_KEY = 'GET /api/v1/cp/tenants';

afterEach(() => {
    vi.restoreAllMocks();
});

/**
 * 一覧画面を描画する関数
 * @param {MockHandler} reply 一覧 API の応答
 * @param {{ path?: string; roles?: string[] }} options 最初のパス・ロール
 * @returns {ReturnType<typeof mockFetch>} fetch の spy
*/
const renderList = (reply: MockHandler, { path = '/cp/tenants', roles }: { path?: string; roles?: string[] } = {}) => {
    const spy = mockFetch({ [LIST_KEY]: reply });
    renderCpScreen(<Route path="/cp/tenants" element={<CpTenantListPage />} />, { path, roles });
    return spy;
};

const PAGE = { status: 200, body: { items: SAMPLE_LIST_ITEMS, next_cursor: null, total: 3 } };

describe('テナント一覧画面', () => {
    it('表に、コード・名前・状態・ユーザー数・主要指標・作成日時を表示し、見出しを th にする', async () => {
        renderList(PAGE);
        const table = await screen.findByTestId('tenant-table');
        expect(within(table).getAllByRole('columnheader').map((header) => header.textContent)).toEqual(['テナントコード', '名前', '状態', 'ユーザー数 (有効 / 総数)', '主要指標', '作成日時']);
        expect(screen.getByTestId('tenant-status-alpha')).toHaveTextContent('稼働中');
        expect(screen.getByTestId('tenant-status-beta')).toHaveTextContent('停止中');
        expect(screen.getByTestId('tenant-users-alpha')).toHaveTextContent('9 / 12');
        expect(screen.getByTestId('tenant-metrics-alpha')).toHaveTextContent('ToDo 数: 1,280');
        // 集計前は「—」
        expect(screen.getByTestId('tenant-users-gamma')).toHaveTextContent('—');
        expect(screen.getByTestId('tenant-metrics-gamma')).toHaveTextContent('ToDo 数: —');
        expect(screen.getByTestId('tenant-list-count')).toHaveTextContent('全 3 件のうち 3 件');
    });

    it('行を押すと、詳細へ移る', async () => {
        const user = userEvent.setup();
        renderList(PAGE);
        await user.click(await screen.findByTestId('tenant-row-beta'));
        expect(await screen.findByTestId('location-probe')).toHaveTextContent('/cp/tenants/01900000-0000-7000-8000-000000000002');
    });

    it('saas_admin にだけ、テナント作成の導線を表示する', async () => {
        renderList(PAGE);
        expect(await screen.findByTestId('tenant-list-create')).toHaveAttribute('href', '/cp/tenant-create');
    });

    it('saas_viewer には、テナント作成の導線を表示しない', async () => {
        renderList(PAGE, { roles: ['saas_viewer'] });
        await screen.findByTestId('tenant-table');
        expect(screen.queryByTestId('tenant-list-create')).toBeNull();
        expect(screen.getByTestId('cp-tenant-list-page')).toHaveAttribute('data-can-write', 'false');
    });

    it('URL のクエリの絞り込み・並び順を API に渡す', async () => {
        const spy = renderList(PAGE, { path: '/cp/tenants?status=SUSPENDED&sort=name' });
        await screen.findByTestId('tenant-table');
        const url = new URL(calledRequests(spy)[0].url);
        expect(url.searchParams.get('status')).toBe('SUSPENDED');
        expect(url.searchParams.get('sort')).toBe('name');
        expect(screen.getByTestId('tenant-sort-name').closest('th')).toHaveAttribute('aria-sort', 'ascending');
    });

    it('列の見出しを押すと、並び順を変えて取り直す', async () => {
        const user = userEvent.setup();
        const spy = renderList(PAGE);
        await screen.findByTestId('tenant-table');
        await user.click(screen.getByTestId('tenant-sort-tenant_code'));
        await vi.waitFor(() => expect(calledRequests(spy).some((request) => new URL(request.url).searchParams.get('sort') === 'tenant_code')).toBe(true));
    });

    it('「さらに読み込む」で次のページを連結する', async () => {
        const user = userEvent.setup();
        renderList((request) => (new URL(request.url).searchParams.has('cursor')
            ? { status: 200, body: { items: [sampleListItem({ id: 'more', tenant_code: 'delta', name: 'Delta' })], next_cursor: null } }
            : { status: 200, body: { items: SAMPLE_LIST_ITEMS, next_cursor: 'c1', total: 4 } }));
        await user.click(await screen.findByTestId('tenant-list-load-more'));
        expect(await screen.findByTestId('tenant-row-delta')).toBeInTheDocument();
        expect(screen.queryByTestId('tenant-list-load-more')).toBeNull();
    });

    it('テナントが無ければ、空の表示を出す (saas_admin には最初の作成への導線)', async () => {
        renderList({ status: 200, body: { items: [], next_cursor: null, total: 0 } });
        expect(await screen.findByTestId('tenant-list-empty')).toHaveTextContent('テナントはまだありません');
        expect(screen.getByTestId('tenant-list-empty-create')).toBeInTheDocument();
    });

    it('絞り込みの結果が空なら、その旨を出す', async () => {
        renderList({ status: 200, body: { items: [], next_cursor: null, total: 0 } }, { path: '/cp/tenants?status=DELETED' });
        expect(await screen.findByTestId('tenant-list-empty')).toHaveTextContent('条件に一致するテナントはありません');
        expect(screen.queryByTestId('tenant-list-empty-create')).toBeNull();
    });

    it('取得の失敗は、role="alert" で通知し再試行できる', async () => {
        renderList(problemReply(503, 'service_unavailable'));
        const alert = await screen.findByTestId('tenant-list-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(within(alert).getByTestId('tenant-list-error-reload')).toBeInTheDocument();
    });
});
