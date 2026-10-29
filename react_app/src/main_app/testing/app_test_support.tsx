// テスト用: AP のフックを AppAuthProvider の内側で動かす補助とテストデータ (アプリのコードからは import しない)
import type { ReactNode } from 'react';
import { AppAuthProvider } from '@/main_app/auth/AppAuthProvider';
import type { OrganizationDetail, OrganizationRead, UserDetail, UserRead } from '@/main_app/api/contract';
import type { MockReply } from '@/shared/testing/fetch_mock';

/** AP の認証ステータス API のキー (mockFetch に渡す) */
export const APP_STATUS_KEY = 'GET /api/auth/app/status';

/** テストで使う自分のユーザー ID (AP のユーザー ID。sub とは別の値) */
export const SELF_USER_ID = '01900000-0000-7000-8000-00000000a001';
/** テストで使う他のユーザー ID */
export const OTHER_USER_ID = '01900000-0000-7000-8000-00000000a002';
/** テストで使う組織 ID */
export const ORGANIZATION_ID = '01900000-0000-7000-8000-00000000b001';

/**
 * AP の認証ステータス API の応答を作る関数
 * @param {string[]} roles ロール (tenant_admin / member)
 * @returns {MockReply} 応答
*/
export const appStatusReply = (roles: string[] = ['tenant_admin', 'member']): MockReply => ({
    status: 200,
    body: { authenticated: true, plane: 'app', tenant_code: 'alpha', user: { sub: 'kc-sub-1', preferred_username: 'alpha-admin', email: null, roles } },
});

/**
 * renderHook の wrapper (AppAuthProvider。遷移は何もしない)
 * @param {{ children: ReactNode }} props 子要素
 * @returns {JSX.Element} プロバイダー
*/
export const AppTestProvider = ({ children }: { children: ReactNode }) => <AppAuthProvider assignLocation={() => undefined}>{children}</AppAuthProvider>;

/**
 * ユーザーのテストデータを作る関数
 * @param {Partial<UserRead>} overrides 上書きする項目
 * @returns {UserRead} ユーザー
*/
export const userOf = (overrides: Partial<UserRead> = {}): UserRead => ({
    id: OTHER_USER_ID,
    email: 'taro@alpha.example',
    display_name: 'Taro Yamada',
    first_name: 'Taro',
    last_name: 'Yamada',
    roles: ['member'],
    is_active: true,
    last_login_at: null,
    version: 3,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...overrides,
});

/**
 * ユーザー詳細のテストデータを作る関数 (UserDetail は UserRead と同じ項目)
 * @param {Partial<UserDetail>} overrides 上書きする項目
 * @returns {UserDetail} 詳細
*/
export const userDetailOf = (overrides: Partial<UserDetail> = {}): UserDetail => userOf(overrides);

/**
 * 組織のテストデータを作る関数
 * @param {Partial<OrganizationRead>} overrides 上書きする項目
 * @returns {OrganizationRead} 組織
*/
export const organizationOf = (overrides: Partial<OrganizationRead> = {}): OrganizationRead => ({
    id: ORGANIZATION_ID,
    name: '営業部',
    version: 3,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...overrides,
});

/**
 * 組織の詳細のテストデータを作る関数
 * @param {Partial<OrganizationDetail>} overrides 上書きする項目
 * @returns {OrganizationDetail} 詳細
*/
export const organizationDetailOf = (overrides: Partial<OrganizationDetail> = {}): OrganizationDetail => ({ ...organizationOf(), member_ids: [SELF_USER_ID], ...overrides });
