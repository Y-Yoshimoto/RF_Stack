// テナント詳細画面のテスト (viewer に変更操作が無い・状態ごとの操作・確認ダイアログ・412 / 409 の表示・再実行の一時パスワード)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route } from 'react-router-dom';
import { calledKeys, calledRequests, mockFetch, problemReply, type MockHandler } from '@/shared/testing/fetch_mock';
import type { TenantRead } from '@/control_plane_app/api/contract';
import { renderCpScreen } from '@/control_plane_app/testing/render_screen';
import { sampleDetail, sampleTenant, SAMPLE_METRIC_ITEMS, SAMPLE_TENANT_ID } from '@/control_plane_app/testing/story_data';
import { CpTenantDetailPage } from '.';

const BASE = `/api/v1/cp/tenants/${SAMPLE_TENANT_ID}`;
const DETAIL_KEY = `GET ${BASE}`;
const METRICS_KEY = `GET ${BASE}/metrics`;
const SUSPEND_KEY = `POST ${BASE}/suspend`;
const RESUME_KEY = `POST ${BASE}/resume`;
const DELETE_KEY = `DELETE ${BASE}`;
const RETRY_KEY = `POST ${BASE}/provisioning/retry`;
const SECRET = 'Retry-Temp-1!';

afterEach(() => {
    vi.restoreAllMocks();
});

/**
 * 詳細画面を描画する関数
 * @param {Partial<TenantRead>} overrides テナントの上書き項目
 * @param {Record<string, MockHandler>} replies 追加の API の応答
 * @param {string[]} roles ロール
 * @returns {Promise<ReturnType<typeof mockFetch>>} fetch の spy
*/
const renderDetail = async (overrides: Partial<TenantRead>, replies: Record<string, MockHandler> = {}, roles?: string[]) => {
    const spy = mockFetch({
        [DETAIL_KEY]: { status: 200, body: sampleDetail(overrides), headers: { ETag: '"3"' } },
        [METRICS_KEY]: { status: 200, body: { tenant_id: SAMPLE_TENANT_ID, from_date: '2026-10-01', to_date: '2026-10-28', items: SAMPLE_METRIC_ITEMS } },
        ...replies,
    });
    renderCpScreen(<Route path="/cp/tenants/:tenant_id" element={<CpTenantDetailPage />} />, { path: `/cp/tenants/${SAMPLE_TENANT_ID}`, roles });
    // 詳細とメトリクスの取得が終わるまで待つ (テストの後始末で fetch のモックが外れる前に、取得を終わらせる)
    await screen.findByTestId('tenant-metrics-table');
    return spy;
};

describe('テナント詳細画面: 表示', () => {
    it('基本情報・メトリクス推移・払い出し履歴を表示する', async () => {
        await renderDetail({});
        expect(await screen.findByTestId('tenant-detail-heading')).toHaveTextContent('Alpha 株式会社');
        expect(screen.getByTestId('tenant-detail-tenant-code')).toHaveTextContent('alpha');
        // メトリクス: 日付 × 指標の表 (新しい日付が先頭。値は桁区切り)
        const table = await screen.findByTestId('tenant-metrics-table');
        const rows = within(table).getAllByRole('row');
        expect(rows[1]).toHaveTextContent('2026-10-27');
        expect(rows[1]).toHaveTextContent('1,280');
        expect(within(table).getByRole('columnheader', { name: 'ToDo 数' })).toBeInTheDocument();
        // 払い出し履歴 (失敗のエラー情報も出る)
        expect(screen.getByTestId('tenant-history-row-h2')).toHaveTextContent('失敗');
        expect(screen.getByTestId('tenant-history-row-h2')).toHaveTextContent('create_realm');
    });

    it('存在しないテナント (404) は、一覧への導線を表示する', async () => {
        mockFetch({ [DETAIL_KEY]: problemReply(404, 'tenant_not_found') });
        renderCpScreen(<Route path="/cp/tenants/:tenant_id" element={<CpTenantDetailPage />} />, { path: `/cp/tenants/${SAMPLE_TENANT_ID}` });
        expect(await screen.findByTestId('tenant-detail-not-found')).toBeInTheDocument();
        expect(screen.getByTestId('tenant-detail-back-to-list')).toHaveAttribute('href', '/cp/tenants');
    });

    it('取得の失敗は、role="alert" で通知し再試行できる', async () => {
        mockFetch({ [DETAIL_KEY]: problemReply(503, 'service_unavailable') });
        renderCpScreen(<Route path="/cp/tenants/:tenant_id" element={<CpTenantDetailPage />} />, { path: `/cp/tenants/${SAMPLE_TENANT_ID}` });
        expect(await screen.findByRole('alert')).toBeInTheDocument();
        expect(screen.getByTestId('tenant-detail-error-reload')).toBeInTheDocument();
    });

    it('メトリクスの期間を切り替えると、取り直す', async () => {
        const user = userEvent.setup();
        const spy = await renderDetail({});
        await screen.findByTestId('tenant-metrics-table');
        await user.click(screen.getByTestId('tenant-metrics-range-7'));
        await vi.waitFor(() => expect(calledKeys(spy).filter((key) => key === METRICS_KEY)).toHaveLength(2));
        const urls = calledRequests(spy).map((request) => new URL(request.url)).filter((url) => url.pathname.endsWith('/metrics'));
        expect(urls[1].searchParams.get('from')).not.toBe(urls[0].searchParams.get('from'));
    });
});

describe('テナント詳細画面: saas_viewer', () => {
    it('変更操作の UI を一切表示しない', async () => {
        await renderDetail({ status: 'ACTIVE' }, {}, ['saas_viewer']);
        expect(await screen.findByTestId('tenant-detail-viewer-notice')).toBeInTheDocument();
        expect(screen.getByTestId('cp-tenant-detail-page')).toHaveAttribute('data-can-write', 'false');
        expect(screen.queryByTestId('tenant-detail-actions')).toBeNull();
        for (const name of ['suspend', 'resume', 'delete', 'retry']) expect(screen.queryByTestId(`tenant-action-${name}`)).toBeNull();
        expect(screen.queryByRole('button', { name: /停止|再開|削除|再実行/ })).toBeNull();
    });
});

describe('テナント詳細画面: 状態ごとの操作 (saas_admin)', () => {
    it.each([
        ['ACTIVE', ['suspend', 'delete']],
        ['SUSPENDED', ['resume', 'delete']],
        ['FAILED', ['retry', 'delete']],
        ['PENDING_DELETION', []],
    ] as const)('%s で出す操作', async (status, expected) => {
        await renderDetail({ status });
        await screen.findByTestId('tenant-detail-actions');
        for (const name of ['suspend', 'resume', 'delete', 'retry']) {
            if (expected.includes(name as never)) expect(screen.getByTestId(`tenant-action-${name}`)).toBeInTheDocument();
            else expect(screen.queryByTestId(`tenant-action-${name}`)).toBeNull();
        }
    });
});

describe('テナント詳細画面: 変更操作', () => {
    it('停止は確認ダイアログを経て、If-Match 付きで実行し、状態を更新する', async () => {
        const user = userEvent.setup();
        const spy = await renderDetail({}, { [SUSPEND_KEY]: { status: 200, body: sampleTenant({ status: 'SUSPENDED', version: 4 }), headers: { ETag: '"4"' } } });
        await user.click(await screen.findByTestId('tenant-action-suspend'));
        // 確認の前には API を呼ばない。キャンセルでも呼ばない
        expect(calledKeys(spy)).not.toContain(SUSPEND_KEY);
        await user.click(screen.getByTestId('tenant-suspend-dialog-cancel'));
        expect(calledKeys(spy)).not.toContain(SUSPEND_KEY);
        await user.click(screen.getByTestId('tenant-action-suspend'));
        await user.click(screen.getByTestId('tenant-suspend-dialog-confirm'));
        expect(await screen.findByTestId('tenant-action-resume')).toBeInTheDocument();
        expect(screen.queryByTestId('tenant-suspend-dialog')).toBeNull();
        const request = calledRequests(spy).find((item) => item.method === 'POST' && item.url.endsWith('/suspend'));
        expect(request?.headers.get('If-Match')).toBe('"3"');
    });

    it('削除要求は、テナントコードを入力するまで実行できない', async () => {
        const user = userEvent.setup();
        const spy = await renderDetail({}, { [DELETE_KEY]: { status: 200, body: sampleTenant({ status: 'PENDING_DELETION', version: 4, deletion_requested_at: '2026-10-28T00:00:00Z' }), headers: { ETag: '"4"' } } });
        await user.click(await screen.findByTestId('tenant-action-delete'));
        expect(screen.getByTestId('tenant-delete-dialog-confirm')).toBeDisabled();
        await user.type(screen.getByTestId('tenant-delete-confirm-input'), 'alph');
        expect(screen.getByTestId('tenant-delete-dialog-confirm')).toBeDisabled();
        await user.type(screen.getByTestId('tenant-delete-confirm-input'), 'a');
        await user.click(screen.getByTestId('tenant-delete-dialog-confirm'));
        expect(await screen.findByTestId('tenant-detail-no-actions')).toBeInTheDocument();
        expect(screen.getByTestId('tenant-detail-deletion-requested-at')).toBeInTheDocument();
        expect(calledKeys(spy)).toContain(DELETE_KEY);
    });

    it('412 は再読み込みを促し、押すと詳細を取り直す', async () => {
        const user = userEvent.setup();
        const spy = await renderDetail({}, { [SUSPEND_KEY]: problemReply(412, 'tenant_version_conflict') });
        await user.click(await screen.findByTestId('tenant-action-suspend'));
        await user.click(screen.getByTestId('tenant-suspend-dialog-confirm'));
        const alert = await screen.findByTestId('tenant-detail-action-error');
        expect(alert).toHaveAttribute('role', 'alert');
        expect(alert).toHaveAttribute('data-error-kind', 'version_conflict');
        await user.click(screen.getByTestId('tenant-detail-action-error-reload'));
        await vi.waitFor(() => expect(calledKeys(spy).filter((key) => key === DETAIL_KEY)).toHaveLength(2));
        await vi.waitFor(() => expect(screen.queryByTestId('tenant-detail-action-error')).toBeNull());
    });

    it('409 は、現在の状態と削除できる日時を表示する', async () => {
        const user = userEvent.setup();
        const conflict = { status: 409, body: { ...(problemReply(409, 'deletion_grace_period_not_elapsed').body as object), operation: 'delete', current_status: 'PENDING_DELETION', deletable_at: '2026-11-27T00:00:00Z' } };
        await renderDetail({}, { [RESUME_KEY]: conflict, [SUSPEND_KEY]: conflict });
        await user.click(await screen.findByTestId('tenant-action-suspend'));
        await user.click(screen.getByTestId('tenant-suspend-dialog-confirm'));
        const details = await screen.findByTestId('tenant-detail-action-error-details');
        expect(details).toHaveTextContent('現在の状態: 削除待ち');
        expect(details).toHaveTextContent('削除できるようになる日時: 2026/11/27');
    });

    it('払い出しの再実行は、初期管理者を入力して実行し、新しい一時パスワードを一度だけ表示する', async () => {
        const user = userEvent.setup();
        const spy = await renderDetail(
            { status: 'FAILED' },
            { [RETRY_KEY]: { status: 200, body: { tenant: sampleTenant({ status: 'ACTIVE', version: 5 }), initial_admin: { username: 'admin@example.com', temporary_password: SECRET }, provisioning_history_id: 'h3' }, headers: { ETag: '"5"' } } },
        );
        await user.click(await screen.findByTestId('tenant-action-retry'));
        // メールアドレスが空なら実行しない
        await user.click(screen.getByTestId('tenant-retry-dialog-confirm'));
        expect(calledKeys(spy)).not.toContain(RETRY_KEY);
        await user.type(screen.getByTestId('tenant-retry-email'), 'admin@example.com');
        await user.click(screen.getByTestId('tenant-retry-dialog-confirm'));
        const dialog = await screen.findByTestId('credentials-dialog');
        expect(within(dialog).getByTestId('credentials-dialog-password')).toHaveTextContent(SECRET);
        await user.click(within(dialog).getByTestId('credentials-dialog-close'));
        expect(screen.queryByTestId('credentials-dialog')).toBeNull();
        expect(document.body).not.toHaveTextContent(SECRET);
        // 履歴が増えるため、詳細を取り直す
        expect(calledKeys(spy).filter((key) => key === DETAIL_KEY).length).toBeGreaterThanOrEqual(2);
    });
});
