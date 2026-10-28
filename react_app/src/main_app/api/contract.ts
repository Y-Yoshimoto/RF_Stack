// アプリケーションプレーン (AP) の API 契約 (`/api/v1`、tags: app)
// 正は FastAPI の OpenAPI (`GET /openapi.json`)。本ファイルはそれを手書きで写したもの。
// OpenAPI からの型生成を導入した時点で生成物に置き換える (docs/architecture/03-conventions.md §8)。
//
// - 認証は AP セッション (Cookie rf_sid_app)。未認証・CP のセッションは 401、テナント停止中は 403 (tenant_inactive)、
//   それ以外のテナント不整合は 403 (tenant_unavailable)。エラーは Problem Details (FetchComponents/problem.ts)。
// - 変更系メソッドには X-Requested-With: rf-stack が必須 (FetchComponents の requestFetch が付与する)。

//// エンドポイントのパス (Vite proxy は /api をそのまま FastAPI に転送する)
export const APP_API_PATHS = {
    ME: '/api/v1/me',
} as const;

//// 公開 API (`/api/v1/public`、tags: public。認証なし)。ログイン前の AP 画面が使う。
export const PUBLIC_API_PATHS = {
    tenant: (tenant_code: string) => `/api/v1/public/tenants/${encodeURIComponent(tenant_code)}`,
} as const;

/**
 * `GET /api/v1/public/tenants/{tenant_code}` のレスポンス (OpenAPI: PublicTenantRead)。
 * 存在しない・削除済み・形式不正・予約語は区別せず 404 (not_found)。レート制限を超えると 429 (Retry-After)。
 */
export type PublicTenantRead = {
    /** テナントコード。 */
    tenant_code: string;
    /** ライフサイクル状態。ログインできるのは `ACTIVE` のみ。 */
    status: 'PROVISIONING' | 'ACTIVE' | 'FAILED' | 'SUSPENDED' | 'PENDING_DELETION' | 'DEPROVISIONING' | 'DELETED';
};

/**
 * ログイン中のテナント (OpenAPI: MeTenant)。
 */
export type MeTenant = {
    /** テナント ID (UUIDv7)。 */
    id: string;
    /** テナントコード (URL に使う識別子)。 */
    tenant_code: string;
};

/**
 * ログイン中のユーザー (OpenAPI: MeUser)。
 */
export type MeUser = {
    /** ユーザーの識別子 (認証基盤の `sub`)。 */
    id: string;
    /** ユーザー名。 */
    username: string | null;
    /** メールアドレス。 */
    email: string | null;
    /** テナント内のロール (`tenant_admin` / `member`)。 */
    roles: string[];
};

/**
 * `GET /api/v1/me` のレスポンス (OpenAPI: MeRead)。
 */
export type MeRead = {
    /** テナント。 */
    tenant: MeTenant;
    /** ユーザー。 */
    user: MeUser;
};
