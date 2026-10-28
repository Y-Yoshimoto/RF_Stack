// コントロールプレーン (CP) の API 契約 (`/api/v1/cp`、tags: cp)
// 正は FastAPI の OpenAPI (`GET /openapi.json`)。本ファイルはそれを手書きで写したもの。
// OpenAPI からの型生成を導入した時点で生成物に置き換える (docs/architecture/03-conventions.md §8)。
//
// - 認証は CP セッション (Cookie rf_sid_cp) と saas_admin / saas_viewer。変更系はさらに saas_admin (saas_viewer は 403)。
// - 変更系メソッドには X-Requested-With: rf-stack が必須 (FetchComponents の requestFetch が付与する)。
// - 停止・再開・削除は If-Match が必須 (無ければ 428 precondition_required、不一致は 412 tenant_version_conflict、
//   形式不正は 400 invalid_if_match)。値は GET の ETag ヘッダー、またはレスポンスの version から ifMatchOf で作る。
// - 日時は UTC の ISO 8601 (`Z` 付き)、日付は `YYYY-MM-DD`。メトリクスの値は 10 進数の文字列。
// - エラーは Problem Details (FetchComponents/problem.ts)。CP 固有の code は CP_PROBLEM_CODE。

//// エンドポイントのパス (Vite proxy は /api をそのまま FastAPI に転送する)
export const CP_API_PATHS = {
    TENANTS: '/api/v1/cp/tenants',
    METRICS_SUMMARY: '/api/v1/cp/metrics/summary',
    tenant: (tenant_id: string) => `/api/v1/cp/tenants/${encodeURIComponent(tenant_id)}`,
    tenantSuspend: (tenant_id: string) => `/api/v1/cp/tenants/${encodeURIComponent(tenant_id)}/suspend`,
    tenantResume: (tenant_id: string) => `/api/v1/cp/tenants/${encodeURIComponent(tenant_id)}/resume`,
    tenantProvisioningRetry: (tenant_id: string) => `/api/v1/cp/tenants/${encodeURIComponent(tenant_id)}/provisioning/retry`,
    tenantMetrics: (tenant_id: string) => `/api/v1/cp/tenants/${encodeURIComponent(tenant_id)}/metrics`,
} as const;

//// CP 固有のエラーコード (control_plane_app/problems.py、modules/api_common/etag.py)
export const CP_PROBLEM_CODE = {
    // 400 / 412: 楽観ロック
    INVALID_IF_MATCH: 'invalid_if_match',
    TENANT_VERSION_CONFLICT: 'tenant_version_conflict',
    // 404
    TENANT_NOT_FOUND: 'tenant_not_found',
    // 409 (invalid_tenant_transition は拡張メンバー operation / current_status を持つ)
    TENANT_CODE_ALREADY_EXISTS: 'tenant_code_already_exists',
    INVALID_TENANT_TRANSITION: 'invalid_tenant_transition',
    DELETION_GRACE_PERIOD_NOT_ELAPSED: 'deletion_grace_period_not_elapsed',
    TENANT_OPERATION_IN_PROGRESS: 'tenant_operation_in_progress',
    // 422 (errors に項目)
    INVALID_TENANT_INPUT: 'invalid_tenant_input',
    INVALID_TENANT_CODE: 'invalid_tenant_code',
    // 502 (拡張メンバー tenant_id / step)
    TENANT_PROVISIONING_FAILED: 'tenant_provisioning_failed',
    TENANT_REALM_OPERATION_FAILED: 'tenant_realm_operation_failed',
    TENANT_DEPROVISIONING_FAILED: 'tenant_deprovisioning_failed',
    TENANT_EXTERNAL_OPERATION_FAILED: 'tenant_external_operation_failed',
} as const;

/**
 * If-Match ヘッダーの値を作る関数
 * @param {number} version テナントの version (ETag と同じ値)
 * @returns {string} `"<version>"` 形式の値
*/
export const ifMatchOf = (version: number): string => `"${version}"`;

// 列挙値 ///////////////////////////////////////////////////////////////////////

/** テナントの状態 (OpenAPI: TenantStatus。CP のテナント状態のみ大文字)。 */
export type TenantStatus = 'PROVISIONING' | 'ACTIVE' | 'FAILED' | 'SUSPENDED' | 'PENDING_DELETION' | 'DEPROVISIONING' | 'DELETED';

/** 払い出しの種類 (OpenAPI: ProvisioningType)。 */
export type ProvisioningType = 'onboard' | 'offboard';

/** 払い出しの実行状態 (OpenAPI: RunStatus)。 */
export type RunStatus = 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'SKIPPED';

/** 一覧の並び順。先頭に `-` で降順 (既定 `-created_at`)。 */
export type TenantSortKey = 'created_at' | '-created_at' | 'tenant_code' | '-tenant_code' | 'name' | '-name';

// テナント /////////////////////////////////////////////////////////////////////

/**
 * テナント (OpenAPI: TenantRead)。停止・再開・削除要求のレスポンス。
 */
export type TenantRead = {
    id: string;
    tenant_code: string;
    name: string;
    status: TenantStatus;
    /** 楽観ロックのバージョン (ETag と同じ値)。 */
    version: number;
    created_at: string;
    updated_at: string;
    deletion_requested_at: string | null;
    deleted_at: string | null;
};

/**
 * 一覧の要素 (OpenAPI: TenantListItem)。直近の日次メトリクスのユーザー数を含む (無ければ null)。
 */
export type TenantListItem = TenantRead & {
    users_total?: number | null;
    users_active?: number | null;
    /** ユーザー数の集計日 (`YYYY-MM-DD`)。 */
    metrics_date?: string | null;
};

/**
 * `GET /api/v1/cp/tenants` のレスポンス (OpenAPI: TenantPage)。
 */
export type TenantPage = {
    items: TenantListItem[];
    /** 次のページのカーソル。最後のページでは null。 */
    next_cursor: string | null;
    /** 総件数 (`include_total=true` のときのみ)。 */
    total?: number | null;
};

/**
 * `GET /api/v1/cp/tenants` のクエリ。
 */
export type TenantListQuery = {
    /** 1 ページの件数 (既定 50、1〜200)。 */
    limit?: number;
    /** 前回のレスポンスの next_cursor (中身は解釈しない)。並び順を変えると 422。 */
    cursor?: string;
    include_total?: boolean;
    sort?: TenantSortKey;
    /** 状態の絞り込み。複数はカンマ区切り (例: `ACTIVE,SUSPENDED`)。省略時は削除済みを含む全件。 */
    status?: string;
};

/**
 * 払い出しの履歴 (OpenAPI: ProvisioningHistoryRead)。
 */
export type ProvisioningHistoryRead = {
    id: string;
    type: ProvisioningType;
    status: RunStatus;
    step: string | null;
    error: string | null;
    started_at: string;
    finished_at: string | null;
};

/**
 * `GET /api/v1/cp/tenants/{tenant_id}` のレスポンス (OpenAPI: TenantDetail)。ETag ヘッダー付き。
 */
export type TenantDetail = TenantRead & {
    provisioning_history: ProvisioningHistoryRead[];
};

/**
 * 初期管理者の入力 (OpenAPI: InitialAdminInput)。
 */
export type InitialAdminInput = {
    /** メールアドレス (3〜254 文字)。 */
    email: string;
    /** ユーザー名 (1〜100 文字)。 */
    username?: string | null;
    first_name?: string | null;
    last_name?: string | null;
};

/**
 * `POST /api/v1/cp/tenants` のリクエスト (OpenAPI: TenantCreate)。
 */
export type TenantCreate = {
    /** テナントコード (英小文字・数字・ハイフンの 3〜32 文字。予約語は不可。違反は 422 invalid_tenant_code)。 */
    tenant_code: string;
    /** 表示名 (1〜100 文字)。 */
    name: string;
    initial_admin: InitialAdminInput;
};

/**
 * `POST /api/v1/cp/tenants/{tenant_id}/provisioning/retry` のリクエスト (OpenAPI: ProvisioningRetryRequest)。
 */
export type ProvisioningRetryRequest = {
    initial_admin: InitialAdminInput;
};

/**
 * 初期管理者の認証情報 (OpenAPI: InitialAdminCredentials)。一時パスワードは一度だけ返る (Cache-Control: no-store)。
 */
export type InitialAdminCredentials = {
    username: string;
    temporary_password: string;
};

/**
 * 払い出しの結果 (OpenAPI: TenantProvisioned)。作成 (201、Location / ETag 付き) と再実行 (200) のレスポンス。
 * 払い出しの失敗は 502 で、Problem Details の拡張メンバー tenant_id / step を返す (tenant_id で再実行できる)。
 */
export type TenantProvisioned = {
    tenant: TenantRead;
    initial_admin: InitialAdminCredentials;
    provisioning_history_id: string;
};

// メトリクス ///////////////////////////////////////////////////////////////////

/**
 * 日次メトリクスの 1 件 (OpenAPI: DailyMetricRead)。
 */
export type DailyMetricRead = {
    /** 集計日 (`YYYY-MM-DD`)。 */
    date: string;
    metric_key: string;
    /** 値 (10 進数の文字列。浮動小数点に変換しないこと)。 */
    value: string;
};

/**
 * `GET /api/v1/cp/tenants/{tenant_id}/metrics` のクエリ (既定は直近 30 日、最大 366 日)。
 */
export type TenantMetricsQuery = {
    /** 開始日 (含む。`YYYY-MM-DD`)。 */
    from?: string;
    /** 終了日 (含む。`YYYY-MM-DD`)。 */
    to?: string;
};

/**
 * `GET /api/v1/cp/tenants/{tenant_id}/metrics` のレスポンス (OpenAPI: TenantMetricsRead)。データが無ければ items は空。
 */
export type TenantMetricsRead = {
    tenant_id: string;
    from_date: string;
    to_date: string;
    items: DailyMetricRead[];
};

/**
 * 指標ごとの合計 (OpenAPI: MetricTotalRead)。
 */
export type MetricTotalRead = {
    metric_key: string;
    /** 値 (10 進数の文字列)。 */
    value: string;
};

/**
 * `GET /api/v1/cp/metrics/summary` のレスポンス (OpenAPI: MetricsSummaryRead)。
 */
export type MetricsSummaryRead = {
    /** 状態ごとのテナント数。 */
    tenants_by_status: Partial<Record<TenantStatus, number>>;
    /** 指標ごとの最新値の合計 (削除済みを除く)。 */
    metrics: MetricTotalRead[];
    /** 集計の基準日 (`YYYY-MM-DD`)。データが無ければ null。 */
    as_of: string | null;
};
