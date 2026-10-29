// コントロールプレーン (CP) の画面のパス (01 §11.1)
// FastAPI の modules/auth/redirects.py (CP_HOME_PATH / CP_LOGIN_PATH) と揃える。
// トップレベルのルーター (routes/) からも参照するため、画面を import しない。

/** CP のルートの第 1 セグメント (予約語) */
export const CP_SEGMENT = 'cp';

/** CP のホーム (ログイン成功後の遷移先) */
export const CP_HOME_PATH = `/${CP_SEGMENT}/`;

/** CP のログイン画面 (ログアウト後の遷移先) */
export const CP_LOGIN_PATH = `/${CP_SEGMENT}/login`;

/** CP のルート内の相対パス (control_plane_app/routes.tsx) */
export const CP_ROUTE = {
    LOGIN: 'login',
    TENANTS: 'tenants',
    TENANT_CREATE: 'tenant-create',
    TENANT_DETAIL: 'tenants/:tenant_id',
} as const;

/** テナント一覧 (CP_ROUTE.TENANTS) */
export const CP_TENANTS_PATH = `/${CP_SEGMENT}/${CP_ROUTE.TENANTS}`;

/** テナント作成 (CP_ROUTE.TENANT_CREATE。saas_admin のみ。ナビゲーションの現在地が一覧と重ならないよう、`tenants/` の配下には置かない) */
export const CP_TENANT_CREATE_PATH = `/${CP_SEGMENT}/${CP_ROUTE.TENANT_CREATE}`;

/**
 * テナント詳細のパスを作る関数 (CP_ROUTE.TENANT_DETAIL)
 * @param {string} tenant_id テナント ID
 * @returns {string} パス
*/
export const cpTenantPathOf = (tenant_id: string): string => `${CP_TENANTS_PATH}/${encodeURIComponent(tenant_id)}`;
