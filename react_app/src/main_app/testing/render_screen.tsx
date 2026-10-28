// テスト用: AP の画面を、認証済みの状態 (ロール指定) とルーターの中で描画する補助 (アプリのコードからは import しない)
import type { ReactNode } from 'react';
import { vi } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { AppAuthContext, type AppAuthValue } from '@/main_app/auth/context';

/** 現在のパスを表示するルート (遷移の確認に使う) */
export const LocationProbe = () => {
    const location = useLocation();
    return <p data-testid="location-probe">{`${location.pathname}${location.search}`}</p>;
};

export type RenderAppScreenOptions = {
    /** 最初のパス。 */
    path: string;
    /** ロール (既定は tenant_admin)。 */
    roles?: string[];
};

/**
 * AP の画面を描画する関数
 * @param {ReactNode} routes `<Route>` の並び (どれにも当たらないパスは LocationProbe)
 * @param {RenderAppScreenOptions} options 最初のパス・ロール
 * @returns {ReturnType<typeof render>} 描画結果
*/
export const renderAppScreen = (routes: ReactNode, { path, roles = ['tenant_admin'] }: RenderAppScreenOptions) => {
    const value: AppAuthValue = {
        state: { status: 'authenticated', session: { tenant_code: 'alpha', user: { sub: 'test-sub', preferred_username: 'alpha-admin', email: 'alpha-admin@example.com', roles } } },
        blocked: null,
        refresh: vi.fn(),
        login: vi.fn(),
        logout: () => Promise.resolve(),
        reportApiError: vi.fn(),
    };
    return render(
        <AppAuthContext value={value}>
            <MemoryRouter initialEntries={[path]}>
                <Routes>
                    {routes}
                    <Route path="*" element={<LocationProbe />} />
                </Routes>
            </MemoryRouter>
        </AppAuthContext>,
    );
};
