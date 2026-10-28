// アプリケーションプレーン (AP) の画面のパス (01 §11.1)
// FastAPI の modules/auth/redirects.py (ログイン成功後・ログアウト後の遷移先) と揃える。
// ルートの定義 (main_app/routes.tsx) とトップレベルのルーター (routes/) から参照するため、画面を import しない。

/** ランディング (テナントコード入力) */
export const LANDING_PATH = '/';

/** AP のルート内の相対パス (main_app/routes.tsx) */
export const APP_ROUTE = {
    LOGIN: 'login',
    SAMPLE: 'sample/*',
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
 * AP のサンプル画面のパスを返す関数 (基盤の実装が進んだ段階で sample/ ごと削除する)
 * @param {string} tenant_code テナントコード
 * @param {string} name サンプル名 (例: button)
 * @returns {string} `/{tenant_code}/sample/{name}`
*/
export const appSamplePath = (tenant_code: string, name: string): string => `/${encodeURIComponent(tenant_code)}/sample/${name}`;
