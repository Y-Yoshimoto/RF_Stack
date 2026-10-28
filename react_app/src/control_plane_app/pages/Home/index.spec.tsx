// ダッシュボードのテスト (状態別のテナント数・指標の合計・viewer の表示・エラー)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { screen } from '@testing-library/react';
import { Route } from 'react-router-dom';
import { mockFetch, problemReply } from '@/shared/testing/fetch_mock';
import { renderCpScreen } from '@/control_plane_app/testing/render_screen';
import { SAMPLE_SUMMARY } from '@/control_plane_app/testing/story_data';
import { CpHomePage, countActiveTenants } from '.';

const SUMMARY_KEY = 'GET /api/v1/cp/metrics/summary';

afterEach(() => {
    vi.restoreAllMocks();
});

const renderHome = (roles?: string[]) => renderCpScreen(<Route path="/cp" element={<CpHomePage />} />, { path: '/cp', roles });

describe('ダッシュボード', () => {
    it('countActiveTenants は、削除済みを除いて合計する', () => {
        expect(countActiveTenants(SAMPLE_SUMMARY.tenants_by_status)).toBe(11);
    });

    it('状態別のテナント数と、指標の合計を表示する', async () => {
        mockFetch({ [SUMMARY_KEY]: { status: 200, body: SAMPLE_SUMMARY } });
        renderHome();
        expect(await screen.findByTestId('cp-home-summary-total-count')).toHaveTextContent('11');
        expect(screen.getByTestId('cp-home-summary-active-count')).toHaveTextContent('8');
        expect(screen.getByTestId('cp-home-summary-provisioning-count')).toHaveTextContent('0');
        expect(screen.getByTestId('cp-home-summary-deleted-count')).toHaveTextContent('3');
        expect(screen.getByTestId('cp-home-metric-todo_count-value')).toHaveTextContent('12,800');
        expect(screen.getByTestId('cp-home-as-of')).toHaveTextContent('2026-10-27');
    });

    it('状態のカードは、その状態で絞り込んだ一覧へのリンクになる', async () => {
        mockFetch({ [SUMMARY_KEY]: { status: 200, body: SAMPLE_SUMMARY } });
        renderHome();
        const card = await screen.findByTestId('cp-home-summary-suspended');
        expect(card.querySelector('a')).toHaveAttribute('href', '/cp/tenants?status=SUSPENDED');
    });

    it('集計前は、指標が無い旨を表示する', async () => {
        mockFetch({ [SUMMARY_KEY]: { status: 200, body: { tenants_by_status: {}, metrics: [], as_of: null } } });
        renderHome();
        expect(await screen.findByTestId('cp-home-metrics-empty')).toBeInTheDocument();
        expect(screen.getByTestId('cp-home-summary-total-count')).toHaveTextContent('0');
    });

    it('saas_viewer には、参照のみであることを知らせる', async () => {
        mockFetch({ [SUMMARY_KEY]: { status: 200, body: SAMPLE_SUMMARY } });
        renderHome(['saas_viewer']);
        expect(await screen.findByTestId('cp-home-viewer-notice')).toBeInTheDocument();
        expect(screen.getByTestId('cp-home-page')).toHaveAttribute('data-can-write', 'false');
    });

    it('取得の失敗は、role="alert" で通知する', async () => {
        mockFetch({ [SUMMARY_KEY]: problemReply(503, 'service_unavailable') });
        renderHome();
        expect(await screen.findByTestId('cp-home-error')).toHaveAttribute('role', 'alert');
    });
});
