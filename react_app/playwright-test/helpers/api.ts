/**
 * テストの前提データの用意と後片付けに使う API 呼び出し。
 *
 * 画面操作で検証したいのは「そのシナリオ」であり、前提 (例: ToDo の公開先にする組織) や、テストが失敗した場合の後片付けは API で行う。
 * 認証は呼び出し元の Page / コンテキストのセッション Cookie を使うため、そのプロファイルの権限で実行される。
 * 後片付け (cleanup*) は best effort で、失敗してもテストの結果は変えず、警告を出す。
 */
import { expect, type APIRequestContext } from '@playwright/test';
import { SCREEN_BASEURL } from '../constants';

/**
 * 変更系の API が要求する CSRF 対策ヘッダー。
 * X-Requested-With は src/constants.ts の CSRF_HEADER。Origin はブラウザが自動で付けるが、API 呼び出し (APIRequestContext) は付けないため、
 * FastAPI が許可するオリジン (FRONTEND_URL。これが画面のテストを dev サーバーで動かす理由) を明示する。
 */
const CSRF_HEADERS = { 'X-Requested-With': 'rf-stack', Origin: new URL(SCREEN_BASEURL).origin };

type PageOf<T> = { items: T[]; next_cursor: string | null };

/** 一覧 API を最後のページまで読む */
async function listAll<T>(request: APIRequestContext, url: string): Promise<T[]> {
    const items: T[] = [];
    let cursor: string | null = null;
    do {
        const separator = url.includes('?') ? '&' : '?';
        const response = await request.get(`${url}${separator}limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`);
        expect(response.ok(), `GET ${url} が失敗しました (HTTP ${response.status()})`).toBeTruthy();
        const body = (await response.json()) as PageOf<T>;
        items.push(...body.items);
        cursor = body.next_cursor;
    } while (cursor !== null);
    return items;
}

const ifMatchOf = (version: number): string => `"${version}"`;

//// AP: ユーザー ////////////////////////////////////////////////////////////////

export type UserSummary = { id: string; display_name: string; email: string | null; is_active: boolean; version: number };

/** メールアドレスでテナントのユーザーを探す (無ければ null) */
export async function findUserByEmail(request: APIRequestContext, email: string): Promise<UserSummary | null> {
    const users = await listAll<UserSummary>(request, '/api/v1/users');
    return users.find((user) => user.email === email) ?? null;
}

/** ログイン中のユーザー自身の ID を返す */
export async function fetchSelfUserId(request: APIRequestContext): Promise<string> {
    const response = await request.get('/api/v1/me');
    expect(response.ok()).toBeTruthy();
    return (await response.json()).user.id as string;
}

/** (後片付け) メールアドレスのユーザーが有効なら無効化する。Keycloak のユーザーも無効になる */
export async function cleanupDeactivateUser(request: APIRequestContext, email: string): Promise<void> {
    try {
        const user = await findUserByEmail(request, email);
        if (user === null || !user.is_active) return;
        const response = await request.patch(`/api/v1/users/${user.id}`, { data: { is_active: false }, headers: { ...CSRF_HEADERS, 'If-Match': ifMatchOf(user.version) } });
        if (!response.ok()) console.warn(`[cleanup] ユーザー ${email} を無効化できませんでした (HTTP ${response.status()})`);
    } catch (error) {
        console.warn(`[cleanup] ユーザー ${email} の無効化に失敗しました`, error);
    }
}

//// AP: 組織 ////////////////////////////////////////////////////////////////////

export type OrganizationSummary = { id: string; name: string; version: number };

/** 組織を作成する (前提データ)。tenant_admin のセッションで呼ぶ */
export async function createOrganization(request: APIRequestContext, name: string, member_ids: string[] = []): Promise<OrganizationSummary> {
    const created = await request.post('/api/v1/organizations', { data: { name }, headers: CSRF_HEADERS });
    expect(created.status(), `組織「${name}」を作成できませんでした`).toBe(201);
    let organization = (await created.json()) as OrganizationSummary;
    if (member_ids.length > 0) {
        const replaced = await request.put(`/api/v1/organizations/${organization.id}/members`, {
            data: { user_ids: member_ids },
            headers: { ...CSRF_HEADERS, 'If-Match': ifMatchOf(organization.version) },
        });
        expect(replaced.ok(), `組織「${name}」のメンバーを設定できませんでした`).toBeTruthy();
        organization = (await replaced.json()) as OrganizationSummary;
    }
    return organization;
}

/** (後片付け) 名前が一致する組織を削除する (既に無ければ何もしない) */
export async function cleanupDeleteOrganizations(request: APIRequestContext, name: string): Promise<void> {
    try {
        const organizations = await listAll<OrganizationSummary>(request, '/api/v1/organizations');
        for (const organization of organizations.filter((item) => item.name === name)) {
            const response = await request.delete(`/api/v1/organizations/${organization.id}`, { headers: { ...CSRF_HEADERS, 'If-Match': ifMatchOf(organization.version) } });
            if (!response.ok()) console.warn(`[cleanup] 組織「${name}」を削除できませんでした (HTTP ${response.status()})`);
        }
    } catch (error) {
        console.warn(`[cleanup] 組織「${name}」の削除に失敗しました`, error);
    }
}

//// AP: ToDo ////////////////////////////////////////////////////////////////////

type TodoSummary = { id: string; title: string; version: number };

/** (後片付け) タイトルが一致する ToDo を削除する (論理削除。既に無ければ何もしない)。tenant_admin のセッションで呼ぶ */
export async function cleanupDeleteTodos(request: APIRequestContext, title: string): Promise<void> {
    try {
        const todos = await listAll<TodoSummary>(request, `/api/v1/todos?q=${encodeURIComponent(title)}`);
        for (const todo of todos.filter((item) => item.title === title)) {
            const response = await request.delete(`/api/v1/todos/${todo.id}`, { headers: { ...CSRF_HEADERS, 'If-Match': ifMatchOf(todo.version) } });
            if (!response.ok()) console.warn(`[cleanup] ToDo「${title}」を削除できませんでした (HTTP ${response.status()})`);
        }
    } catch (error) {
        console.warn(`[cleanup] ToDo「${title}」の削除に失敗しました`, error);
    }
}

//// CP: テナント ////////////////////////////////////////////////////////////////

type TenantSummary = { id: string; tenant_code: string; status: string; version: number };

/** (後片付け) テナントコードのテナントが ACTIVE / SUSPENDED / FAILED なら削除を要求する (PENDING_DELETION になる)。cp-admin のセッションで呼ぶ */
export async function cleanupRequestTenantDeletion(request: APIRequestContext, tenant_code: string): Promise<void> {
    try {
        const tenants = await listAll<TenantSummary>(request, '/api/v1/cp/tenants');
        const tenant = tenants.find((item) => item.tenant_code === tenant_code);
        if (tenant === undefined || !['ACTIVE', 'SUSPENDED', 'FAILED'].includes(tenant.status)) return;
        const response = await request.delete(`/api/v1/cp/tenants/${tenant.id}`, { headers: { ...CSRF_HEADERS, 'If-Match': ifMatchOf(tenant.version) } });
        if (!response.ok()) console.warn(`[cleanup] テナント ${tenant_code} の削除を要求できませんでした (HTTP ${response.status()})`);
    } catch (error) {
        console.warn(`[cleanup] テナント ${tenant_code} の削除要求に失敗しました`, error);
    }
}
