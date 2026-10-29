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
 * サンプル画面のパスを返す (`/{tenant_code}/sample/{name}`)。
 * @deprecated サンプル画面はルーティングから外れており、このパスを開くと NotFound になる。サンプルに依存する E2E (sample_*.test.ts) は
 * playwright.config.ts の SAMPLE_TESTS で実行対象から外している。新しいテストでは使わない (サンプルを復活させる場合のために残している)。
 */
export const samplePath = (name: string): string => `${APP_HOME_PATH}sample/${name}`;


/**
 * 開発用ログインのプロファイル (FastAPI: modules/auth/dev_profiles.py)。
 * auth.setup.ts が各プロファイルの認証状態 (storageState) を作り、テストは fixtures.ts の `openAs` で選んで使う。
 * plane は 'app' (AP。Cookie rf_sid_app) か 'cp' (CP。Cookie rf_sid_cp)。tenant_code は AP のみ。
 */
export const PROFILES = {
    'alpha-admin': { plane: 'app', tenant_code: 'alpha' },
    'alpha-member': { plane: 'app', tenant_code: 'alpha' },
    'beta-member': { plane: 'app', tenant_code: 'beta' },
    'cp-admin': { plane: 'cp', tenant_code: null },
    'cp-viewer': { plane: 'cp', tenant_code: null },
} as const;

export type ProfileName = keyof typeof PROFILES;

/** 認証状態の保存先のディレクトリ (playwright の実行ディレクトリ (react_app) からの相対パス) */
export const AUTH_STATE_DIR = './playwright-test/.auth';

/**
 * プロファイルごとの認証状態の保存先を返す関数
 * @param profile プロファイル名
 */
export const authStatePath = (profile: ProfileName): string => `${AUTH_STATE_DIR}/${profile}.json`;

/** CP のホーム (ログイン成功後の遷移先。01 §11.1) */
export const CP_HOME_PATH = '/cp/';

/** CP のテナント一覧 */
export const CP_TENANTS_PATH = '/cp/tenants';

/** CP のテナント作成 (saas_admin のみ) */
export const CP_TENANT_CREATE_PATH = '/cp/tenant-create';

/**
 * AP の画面のパスを返す (`/{tenant_code}/{sub_path}`)
 * @param sub_path テナントコードより後ろのパス (例: todos, organizations/{id})
 * @param tenant_code テナントコード (既定は alpha)
 */
export const appPath = (sub_path: string, tenant_code: string = TENANT_CODE): string => `/${tenant_code}/${sub_path}`;

/**
 * テストで作るデータに付ける、実行ごとに一意な接尾辞を返す (小文字英数字 8 桁)
 */
export const uniqueSuffix = (): string => Math.random().toString(36).slice(2, 10).padEnd(8, '0');


/**
 * 新しい画面の E2E (playwright-test/screens/) の対象 URL。既定は Vite の dev サーバー。
 * 変更系の API は Origin ヘッダーが FRONTEND_URL (http://localhost:5173) か CSRF_TRUSTED_ORIGINS のものでないと 403 になるため、
 * preview (4173) ではなく dev サーバーを使う。preview で動かす場合は、FastAPI の CSRF_TRUSTED_ORIGINS に http://localhost:4173 を追加した上で、
 * 環境変数 E2E_SCREEN_BASEURL で指定する。
 */
export const SCREEN_BASEURL = process.env.E2E_SCREEN_BASEURL ?? 'http://localhost:5173';
