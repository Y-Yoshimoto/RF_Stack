// Storybook と vitest で共有する AP のサンプルデータ (アプリ本体からは import しない)
import type { MeOrganization, MeRead, OrganizationDetail, OrganizationRead, UserDetail, UserRead } from '@/main_app/api/contract';
import { OTHER_USER_ID, SELF_USER_ID, organizationDetailOf, organizationOf, userDetailOf, userOf } from '@/main_app/testing/app_test_support';

/** 自分以外のサンプルユーザー ID (2 人目) */
export const THIRD_USER_ID = '01900000-0000-7000-8000-00000000a003';
/** サンプルの 2 つ目の組織 ID */
export const SECOND_ORGANIZATION_ID = '01900000-0000-7000-8000-00000000b002';

/** サンプルのユーザー (自分 = テナント管理者、メンバー、無効なユーザー) */
export const SAMPLE_USERS: UserRead[] = [
    userOf({ id: SELF_USER_ID, display_name: 'Hanako Admin', first_name: 'Hanako', last_name: 'Admin', roles: ['tenant_admin', 'member'], email: 'alpha-admin@alpha.example', last_login_at: '2026-10-27T01:30:00Z', version: 7 }),
    userOf({ id: OTHER_USER_ID, display_name: 'Taro Yamada', first_name: 'Taro', last_name: 'Yamada', roles: ['member'], email: 'taro@alpha.example', last_login_at: null, version: 3 }),
    userOf({ id: THIRD_USER_ID, display_name: 'Jiro Suzuki', first_name: 'Jiro', last_name: 'Suzuki', roles: ['member'], email: 'jiro@alpha.example', is_active: false, last_login_at: '2026-09-01T09:00:00Z', version: 2 }),
];

/** サンプルのユーザー詳細 (ID → 詳細) */
export const SAMPLE_USER_DETAILS: Record<string, UserDetail> = {
    [SELF_USER_ID]: userDetailOf({ ...SAMPLE_USERS[0], roles: ['tenant_admin', 'member'] }),
    [OTHER_USER_ID]: userDetailOf({ ...SAMPLE_USERS[1], roles: ['member'] }),
    [THIRD_USER_ID]: userDetailOf({ ...SAMPLE_USERS[2], roles: ['member'] }),
};

/** サンプルの組織 */
export const SAMPLE_ORGANIZATIONS: OrganizationRead[] = [
    organizationOf(),
    organizationOf({ id: SECOND_ORGANIZATION_ID, name: '開発部', version: 1 }),
];

/** サンプルの組織の詳細 (ID → 詳細。営業部は 2 人、開発部はメンバー無し) */
export const SAMPLE_ORGANIZATION_DETAILS: Record<string, OrganizationDetail> = {
    [SAMPLE_ORGANIZATIONS[0].id]: organizationDetailOf({ member_ids: [SELF_USER_ID, OTHER_USER_ID] }),
    [SECOND_ORGANIZATION_ID]: organizationDetailOf({ ...SAMPLE_ORGANIZATIONS[1], member_ids: [] }),
};

/**
 * 一覧 API の応答の本文を作る関数
 * @param {T[]} items 要素
 * @param {string | null} next_cursor 次のページのカーソル
 * @returns {{ items: T[]; next_cursor: string | null; total: null }} 本文
*/
export const pageOf = <T,>(items: T[], next_cursor: string | null = null) => ({ items, next_cursor, total: null });

/**
 * サンプルの組織のうち、ユーザーが所属するもの (`/api/v1/me` の organizations と同じ形。組織名順)
 * @param {string} user_id ユーザー ID
 * @returns {MeOrganization[]} 所属組織
*/
export const sampleOrganizationsOf = (user_id: string): MeOrganization[] => Object.values(SAMPLE_ORGANIZATION_DETAILS)
    .filter((detail) => detail.member_ids.includes(user_id))
    .map(({ id, name }) => ({ id, name }))
    .sort((a, b) => a.name.localeCompare(b.name));

/**
 * `/api/v1/me` の応答の本文を作る関数
 * @param {string} user_id ユーザー ID
 * @param {string[]} roles ロール
 * @param {MeOrganization[]} organizations 所属組織 (省略時はサンプルの組織のうち所属するもの)
 * @returns {MeRead} 本文
*/
export const meBodyOf = (user_id: string = SELF_USER_ID, roles: string[] = ['tenant_admin', 'member'], organizations: MeOrganization[] = sampleOrganizationsOf(user_id)): MeRead => ({
    tenant: { id: '01900000-0000-7000-8000-00000000c001', tenant_code: 'alpha' },
    user: { id: user_id, username: 'alpha-admin', email: 'alpha-admin@alpha.example', roles },
    organizations,
});

/**
 * `GET /api/v1/users` の応答を作る関数を作る関数 (`ids` を指定されたらその ID のユーザーだけを返す。サーバーと同じく、存在しない ID は含めない)
 * @param {UserRead[]} users テナントのユーザー
 * @returns {(request: Request) => { status: 200; body: ReturnType<typeof pageOf<UserRead>> }} リクエストから応答を決める関数
*/
export const usersReplyOf = (users: UserRead[] = SAMPLE_USERS) => (request: Request) => {
    const ids = new URL(request.url).searchParams.get('ids');
    const wanted = ids === null ? null : new Set(ids.split(',').filter((id) => id !== ''));
    return { status: 200 as const, body: pageOf(wanted === null ? users : users.filter((user) => wanted.has(user.id))) };
};
