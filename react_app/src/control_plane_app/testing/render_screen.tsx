// テスト用: CP の画面を、認証済みの状態 (ロール指定) とルーターの中で描画する補助 (アプリのコードからは import しない)
import type { ReactNode } from 'react';
import { vi } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ControlPlaneAuthContext, type CpAuthValue } from '@/control_plane_app/auth/context';

/** 現在のパスを表示するルート (遷移の確認に使う) */
export const LocationProbe = () => {
    const location = useLocation();
    return <p data-testid="location-probe">{`${location.pathname}${location.search}`}</p>;
};

export type RenderCpScreenOptions = {
    /** 最初のパス。 */
    path: string;
    /** ロール (既定は saas_admin)。 */
    roles?: string[];
};

/**
 * CP の画面を描画する関数
 * @param {ReactNode} routes `<Route>` の並び (どれにも当たらないパスは LocationProbe)
 * @param {RenderCpScreenOptions} options 最初のパス・ロール
 * @returns {ReturnType<typeof render>} 描画結果
*/
export const renderCpScreen = (routes: ReactNode, { path, roles = ['saas_admin'] }: RenderCpScreenOptions) => {
    const value: CpAuthValue = {
        state: { status: 'authenticated', session: { user: { sub: 'test-sub', preferred_username: 'cp-user', email: 'cp-user@example.com', roles } } },
        refresh: vi.fn(),
        login: vi.fn(),
        logout: () => Promise.resolve(),
        reportApiError: vi.fn(),
    };
    return render(
        <ControlPlaneAuthContext value={value}>
            <MemoryRouter initialEntries={[path]}>
                <Routes>
                    {routes}
                    <Route path="*" element={<LocationProbe />} />
                </Routes>
            </MemoryRouter>
        </ControlPlaneAuthContext>,
    );
};
