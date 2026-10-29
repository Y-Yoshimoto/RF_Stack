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
export const CSRF_HEADERS = { 'X-Requested-With': 'rf-stack', Origin: new URL(SCREEN_BASEURL).origin };

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


//// AP: ToDo ////////////////////////////////////////////////////////////////////

export type TodoSummary = { id: string; title: string; status: string; version: number };

export type TodoSeed = {
    /** タイトル。後片付けの対象にするため `E2E ToDo <8 文字>` の形にする (cleanup.teardown.ts) */
    title: string;
    description?: string;
    status?: 'open' | 'in_progress' | 'done';
    priority?: 'low' | 'medium' | 'high';
    /** 期限 (`YYYY-MM-DD`) */
    due_date?: string;
    visibility?: 'private' | 'tenant' | 'organization';
    organization_ids?: string[];
    assignee_ids?: string[];
};

/** ToDo を作成する (前提データ)。呼び出し元のセッションのユーザーが作成者になる。後片付けは cleanup.teardown.ts が行う */
export async function createTodo(request: APIRequestContext, seed: TodoSeed): Promise<TodoSummary> {
    const created = await request.post('/api/v1/todos', { data: seed, headers: CSRF_HEADERS });
    expect(created.status(), `ToDo「${seed.title}」を作成できませんでした`).toBe(201);
    return (await created.json()) as TodoSummary;
}

/** ToDo の詳細を取得する */
export async function fetchTodo(request: APIRequestContext, todo_id: string): Promise<TodoSummary> {
    const response = await request.get(`/api/v1/todos/${todo_id}`);
    expect(response.ok(), `ToDo ${todo_id} を取得できませんでした (HTTP ${response.status()})`).toBeTruthy();
    return (await response.json()) as TodoSummary;
}

/** ToDo にコメントを投稿する (前提データ) */
export async function createComment(request: APIRequestContext, todo_id: string, body: string): Promise<{ id: string }> {
    const created = await request.post(`/api/v1/todos/${todo_id}/comments`, { data: { body }, headers: CSRF_HEADERS });
    expect(created.status(), 'コメントを投稿できませんでした').toBe(201);
    return (await created.json()) as { id: string };
}

/** ToDo のチェックリストに項目を追加する (前提データ) */
export async function createChecklistItem(request: APIRequestContext, todo_id: string, title: string): Promise<{ id: string }> {
    const created = await request.post(`/api/v1/todos/${todo_id}/checklist/items`, { data: { title }, headers: CSRF_HEADERS });
    expect(created.status(), `チェックリスト項目「${title}」を追加できませんでした`).toBe(201);
    // 応答は項目ではなくチェックリスト全体
    const checklist = (await created.json()) as { items: { id: string; title: string }[] };
    const item = checklist.items.find((entry) => entry.title === title);
    expect(item, `追加した項目「${title}」が応答にありません`).toBeDefined();
    return { id: item!.id };
}
