/**
 * @description:
 * AP の認証状態を参照するカスタムフック
*/
import { use } from 'react';
import { useParams } from 'react-router-dom';
import { AppAuthContext, type AppAuthValue } from './context';
import type { AppSession } from './session';

/**
 * AP の認証状態と操作を返すカスタムフック (AppAuthProvider の内側で使う)
 * @returns {AppAuthValue} 認証状態と操作
*/
export const useAppAuth = (): AppAuthValue => {
    const value = use(AppAuthContext);
    if (value === null) throw new Error('useAppAuth は AppAuthProvider の内側で使ってください');
    return value;
};

/**
 * 認証済みの AP セッションを返すカスタムフック (RequireAppSession の内側の画面で使う)
 * @returns {AppSession} セッション
*/
export const useAppSession = (): AppSession => {
    const { state } = useAppAuth();
    if (state.status !== 'authenticated') throw new Error('useAppSession は RequireAppSession の内側で使ってください');
    return state.session;
};

/**
 * URL のテナントコード (`/:tenantCode/*`) を返すカスタムフック
 * @returns {string} テナントコード (ルート外では空文字)
*/
export const useUrlTenantCode = (): string => {
    const { tenantCode } = useParams();
    return tenantCode ?? '';
};
