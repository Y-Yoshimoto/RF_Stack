/**
 * E2E テストで共有する定数。
 * setup ファイル (auth.setup.ts) を他のテストから import すると setup のテストが重複登録されるため、定数はここに置く。
 */

/** 開発用ログインのプロファイル (FastAPI: modules/auth/dev_profiles.py) */
export const DEV_PROFILE = 'alpha-admin';

/** DEV_PROFILE のテナントコード */
export const TENANT_CODE = 'alpha';

/** AP のホーム (ログイン成功後の遷移先。01 §11.1) */
export const APP_HOME_PATH = `/${TENANT_CODE}/`;

/**
 * サンプル画面のパスを返す (`/{tenant_code}/sample/{name}`。AP の認証後画面)
 * @param name サンプル名 (例: button)
 */
export const samplePath = (name: string): string => `${APP_HOME_PATH}sample/${name}`;
