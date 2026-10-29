/**
 * テストの前提データの用意に使う API 呼び出し。
 *
 * 画面操作で検証したいのは「そのシナリオ」であり、前提 (例: ToDo の公開先にする組織) は API で用意する。
 * 認証は呼び出し元の Page / コンテキストのセッション Cookie を使うため、そのプロファイルの権限で実行される。
 * テストが作ったデータの後片付けはここでは行わない (実行後に cleanup.teardown.ts が開発専用の API でまとめて削除する)。
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
