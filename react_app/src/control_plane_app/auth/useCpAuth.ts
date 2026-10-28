/**
 * @description:
 * CP の認証状態・権限を参照するカスタムフック
*/
import { use } from 'react';
import { ControlPlaneAuthContext, type CpAuthValue } from './context';
import { cpPermissionsOf, NO_CP_PERMISSIONS, type CpPermissions } from './guard';
import type { CpSession } from './session';

/**
 * CP の認証状態と操作を返すカスタムフック (ControlPlaneAuthProvider の内側で使う)
 * @returns {CpAuthValue} 認証状態と操作
*/
export const useCpAuth = (): CpAuthValue => {
    const value = use(ControlPlaneAuthContext);
    if (value === null) throw new Error('useCpAuth は ControlPlaneAuthProvider の内側で使ってください');
    return value;
};

/**
 * 認証済みの CP セッションを返すカスタムフック (RequireCpSession の内側の画面で使う)
 * @returns {CpSession} セッション
*/
export const useCpSession = (): CpSession => {
    const { state } = useCpAuth();
    if (state.status !== 'authenticated') throw new Error('useCpSession は RequireCpSession の内側で使ってください');
    return state.session;
};

/**
 * CP の権限を返すカスタムフック
 * saas_viewer (is_viewer / can_write=false) には変更操作の UI を表示しないこと (01 §11.2)。
 * @returns {CpPermissions} 権限 (未認証・読み込み中はすべて false)
*/
export const useCpPermissions = (): CpPermissions => {
    const { state } = useCpAuth();
    return state.status === 'authenticated' ? cpPermissionsOf(state.session.user.roles) : NO_CP_PERMISSIONS;
};
