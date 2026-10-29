/**
 * Keycloak 経由のログイン E2E で使う開発用の認証情報。
 *
 * 正は FastAPI の `fastapi_app/src/modules/auth/dev_profiles.py` (シードと開発用ログインが読む)。
 * テストに値を複製しないよう、パスワードは次の順で解決する。
 *   1. 環境変数 `E2E_DEV_PASSWORD` (指定されていればそれを使う。別の環境に向ける場合の上書き用)
 *   2. dev_profiles.py の `_DEV_PASSWORD` を読む (リポジトリ全体が react_app コンテナの /work にマウントされている)
 * どちらも得られない場合は、原因が分かるメッセージで失敗する。
 *
 * ユーザー名はシードされたユーザー名そのもので、開発用ログインのプロファイル名 (`as`) と一致する。
 * ユーザーの追加・変更が必要な場合は dev_profiles.py を変更し、ここへ反映する。
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

/** dev_profiles.py の場所 (このファイルからの相対) */
const DEV_PROFILES_PATH = fileURLToPath(new URL('../../../fastapi_app/src/modules/auth/dev_profiles.py', import.meta.url));

/** 開発用ユーザー */
export type DevAccount = {
    /** Keycloak のユーザー名 */
    username: string;
    /** AP のテナントコード (CP は null) */
    tenant_code: string | null;
};

/** 使用するシードのユーザー (参照のみ。作成・変更はしない) */
export const DEV_ACCOUNTS = {
    alpha_admin: { username: 'alpha-admin', tenant_code: 'alpha' },
    /** 誤ったパスワードのテスト専用 (他のテストでは使わない。ブルートフォース検知のカウントを他へ波及させないため) */
    alpha_member2: { username: 'alpha-member2', tenant_code: 'alpha' },
    beta_member: { username: 'beta-member', tenant_code: 'beta' },
    cp_admin: { username: 'cp-admin', tenant_code: null },
    cp_viewer: { username: 'cp-viewer', tenant_code: null },
} as const satisfies Record<string, DevAccount>;

/** 誤ったパスワードのテストで使う値 (開発用パスワードとは一致しない) */
export const WRONG_PASSWORD = 'definitely-not-the-dev-password';

let cached_password: string | null = null;

/**
 * 開発用パスワードを返す関数
 * @returns {string} 開発用パスワード
 */
export const devPassword = (): string => {
    if (cached_password !== null) return cached_password;
    const from_env = process.env.E2E_DEV_PASSWORD;
    if (from_env) {
        cached_password = from_env;
        return cached_password;
    }
    let source: string;
    try {
        source = readFileSync(DEV_PROFILES_PATH, 'utf-8');
    } catch (error) {
        throw new Error(
            `開発用パスワードを読み込めません (${DEV_PROFILES_PATH})。リポジトリ全体がマウントされた環境で実行するか、環境変数 E2E_DEV_PASSWORD を指定してください。`,
            { cause: error },
        );
    }
    const matched = /^_DEV_PASSWORD\s*=\s*"([^"]+)"/m.exec(source);
    if (!matched) {
        throw new Error('dev_profiles.py から _DEV_PASSWORD を読み取れません。定義の形式が変わった場合は dev_credentials.ts を更新するか、環境変数 E2E_DEV_PASSWORD を指定してください。');
    }
    cached_password = matched[1];
    return cached_password;
};
