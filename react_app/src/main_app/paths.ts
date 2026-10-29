// アプリケーションプレーン (AP) の画面のパス (01 §11.1)
// FastAPI の modules/auth/redirects.py (ログイン成功後・ログアウト後の遷移先) と揃える。
// ルートの定義 (main_app/routes.tsx) とトップレベルのルーター (routes/) から参照するため、画面を import しない。

/** ランディング (テナントコード入力) */
export const LANDING_PATH = '/';

/** AP のルート内の相対パス (main_app/routes.tsx) */
export const APP_ROUTE = {
    LOGIN: 'login',
    USERS: 'users',
    USER_NEW: 'users/new',
    USER: 'users/:userId',
    ORGANIZATIONS: 'organizations',
    ORGANIZATION: 'organizations/:organizationId',
    PROFILE: 'profile',
    TODOS: 'todos',
    TODO_NEW: 'todos/new',
    TODO: 'todos/:todoId',
} as const;

/**
 * AP のホーム (ログイン成功後の遷移先) のパスを返す関数
 * @param {string} tenant_code テナントコード
 * @returns {string} `/{tenant_code}/`
*/
export const appHomePath = (tenant_code: string): string => `/${encodeURIComponent(tenant_code)}/`;

/**
 * AP のログイン画面 (ログアウト後の遷移先) のパスを返す関数
 * @param {string} tenant_code テナントコード
 * @returns {string} `/{tenant_code}/login`
*/
export const appLoginPath = (tenant_code: string): string => `/${encodeURIComponent(tenant_code)}/${APP_ROUTE.LOGIN}`;

/**
 * AP のユーザー一覧のパスを返す関数
 * @param {string} tenant_code テナントコード
 * @returns {string} `/{tenant_code}/users`
*/
export const appUsersPath = (tenant_code: string): string => `/${encodeURIComponent(tenant_code)}/${APP_ROUTE.USERS}`;

/**
 * AP のユーザー作成画面のパスを返す関数
 * @param {string} tenant_code テナントコード
 * @returns {string} `/{tenant_code}/users/new`
*/
export const appUserCreatePath = (tenant_code: string): string => `/${encodeURIComponent(tenant_code)}/${APP_ROUTE.USER_NEW}`;

/**
 * AP のユーザー詳細のパスを返す関数
 * @param {string} tenant_code テナントコード
 * @param {string} user_id ユーザー ID
 * @returns {string} `/{tenant_code}/users/{user_id}`
*/
export const appUserPath = (tenant_code: string, user_id: string): string => `/${encodeURIComponent(tenant_code)}/${APP_ROUTE.USERS}/${encodeURIComponent(user_id)}`;

/**
 * AP の組織一覧のパスを返す関数
 * @param {string} tenant_code テナントコード
 * @returns {string} `/{tenant_code}/organizations`
*/
export const appOrganizationsPath = (tenant_code: string): string => `/${encodeURIComponent(tenant_code)}/${APP_ROUTE.ORGANIZATIONS}`;

/**
 * AP の組織詳細のパスを返す関数
 * @param {string} tenant_code テナントコード
 * @param {string} organization_id 組織 ID
 * @returns {string} `/{tenant_code}/organizations/{organization_id}`
*/
export const appOrganizationPath = (tenant_code: string, organization_id: string): string => `/${encodeURIComponent(tenant_code)}/${APP_ROUTE.ORGANIZATIONS}/${encodeURIComponent(organization_id)}`;

/**
 * AP のプロフィール画面のパスを返す関数
 * @param {string} tenant_code テナントコード
 * @returns {string} `/{tenant_code}/profile`
*/
export const appProfilePath = (tenant_code: string): string => `/${encodeURIComponent(tenant_code)}/${APP_ROUTE.PROFILE}`;

/**
 * AP の ToDo 一覧のパスを返す関数
 * @param {string} tenant_code テナントコード
 * @returns {string} `/{tenant_code}/todos`
*/
export const appTodosPath = (tenant_code: string): string => `/${encodeURIComponent(tenant_code)}/${APP_ROUTE.TODOS}`;

/**
 * AP の ToDo 作成画面のパスを返す関数
 * @param {string} tenant_code テナントコード
 * @returns {string} `/{tenant_code}/todos/new`
*/
export const appTodoCreatePath = (tenant_code: string): string => `/${encodeURIComponent(tenant_code)}/${APP_ROUTE.TODO_NEW}`;

/**
 * AP の ToDo 詳細のパスを返す関数
 * @param {string} tenant_code テナントコード
 * @param {string} todo_id ToDo ID
 * @returns {string} `/{tenant_code}/todos/{todo_id}`
*/
export const appTodoPath = (tenant_code: string, todo_id: string): string => `/${encodeURIComponent(tenant_code)}/${APP_ROUTE.TODOS}/${encodeURIComponent(todo_id)}`;
