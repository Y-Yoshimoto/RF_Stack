/**
 * @desc 認証状態に基づくルートガードコンポーネント
 */
import { use } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { AuthNZContext } from '@/store/AuthNZ';

/**
 * 認証が必要なルートのガード
 * - isAuthN=undefined : null（ローディング中）
 * - isAuthN=false     : /login へリダイレクト
 * - isAuthN=true      : 子ルートをレンダリング
 */
export const RequireAuth = () => {
    const { authStatus } = use(AuthNZContext);
    if (authStatus.isAuthN === undefined) return null;
    if (!authStatus.isAuthN) return <Navigate to="/login" replace />;
    return <Outlet />;
};

/**
 * 認証済みの場合にリダイレクトするガード（ログインページ用）
 * - isAuthN=undefined : null（ローディング中）
 * - isAuthN=true      : /button へリダイレクト
 * - isAuthN=false     : 子ルートをレンダリング
 */
export const RedirectIfAuthed = () => {
    const { authStatus } = use(AuthNZContext);
    if (authStatus.isAuthN === undefined) return null;
    if (authStatus.isAuthN) return <Navigate to="/button" replace />;
    return <Outlet />;
};
