// AP の認証後レイアウトのテスト (狭い幅でページ全体が横にはみ出さない。ナビゲーションは自身の中でスクロールする)
import { afterEach, describe, expect, it } from 'vitest';
import '@testing-library/jest-dom';
import { screen } from '@testing-library/react';
import { Route } from 'react-router-dom';
import { renderAppScreen } from '@/main_app/testing/render_screen';
import { pageOverflowOf, resetViewport, useMobileViewport } from '@/shared/testing/page_overflow';
import { AppLayout } from '.';

afterEach(async () => {
    await resetViewport();
});

describe('AppLayout', () => {
    it('狭い幅 (Pixel 5 相当) でも、ヘッダーとナビゲーションでページ全体が横にはみ出さない', async () => {
        await useMobileViewport();
        renderAppScreen(<Route path="/:tenantCode/*" element={<AppLayout />}><Route index element={<p>本文</p>} /></Route>, { path: '/alpha/', roles: ['tenant_admin'] });
        expect(await screen.findByTestId('app-shell')).toBeInTheDocument();
        expect(pageOverflowOf()).toMatchObject({ ok: true });
    });
});
