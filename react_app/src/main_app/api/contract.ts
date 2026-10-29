// アプリケーションプレーン (AP) の API 契約 (`/api/v1`、tags: app)
// 正は FastAPI の OpenAPI (`GET /openapi.json`)。本ファイルはそれを手書きで写したもの。
// OpenAPI からの型生成を導入した時点で生成物に置き換える (docs/architecture/03-conventions.md §8)。
//
// - 認証は AP セッション (Cookie rf_sid_app)。未認証・CP のセッションは 401、テナント停止中は 403 (tenant_inactive)、
//   それ以外のテナント不整合は 403 (tenant_unavailable)。エラーは Problem Details (FetchComponents/problem.ts)。
// - 変更系メソッドには X-Requested-With: rf-stack が必須 (FetchComponents の requestFetch が付与する)。
// - /api/v1 全体で、無効化されたユーザーは 401 (user_deactivated。セッションは削除され、以後は session_expired)。
// - 参照は tenant_admin / member、変更 (POST / PATCH / PUT / DELETE) は tenant_admin のみ (member は 403 forbidden)。
//   ToDo (`/api/v1/todos`) は例外で、どちらのロールも使え、ToDo ごとの閲覧範囲 (404) と操作の権限 (403) をサーバーが判定する。
// - PATCH / PUT / DELETE は If-Match が必須 (無ければ 428 precondition_required、不一致は 412 user_version_conflict /
//   organization_version_conflict、形式不正は 400 invalid_if_match)。値は GET の ETag ヘッダー、または version から ifMatchOf で作る。
// - 一覧はカーソル方式 (limit / cursor / sort)。include_total は無い (total は常に null)。不正な sort・cursor は 422。
// - 日時は UTC の ISO 8601 (`Z` 付き)。

//// エンドポイントのパス (Vite proxy は /api をそのまま FastAPI に転送する)
export const APP_API_PATHS = {
    ME: '/api/v1/me',
    USERS: '/api/v1/users',
    ORGANIZATIONS: '/api/v1/organizations',
    user: (user_id: string) => `/api/v1/users/${encodeURIComponent(user_id)}`,
    organization: (organization_id: string) => `/api/v1/organizations/${encodeURIComponent(organization_id)}`,
    organizationMembers: (organization_id: string) => `/api/v1/organizations/${encodeURIComponent(organization_id)}/members`,
    // ToDo (テーマ固有。docs/spec/ToDoApp.md §6・§9.5。型は todo_contract.ts)
    TODOS: '/api/v1/todos',
    todo: (todo_id: string) => `/api/v1/todos/${encodeURIComponent(todo_id)}`,
    todoAssignees: (todo_id: string) => `/api/v1/todos/${encodeURIComponent(todo_id)}/assignees`,
    todoActivities: (todo_id: string) => `/api/v1/todos/${encodeURIComponent(todo_id)}/activities`,
} as const;

//// AP 固有のエラーコード (main_app/problems.py)。共通のコードは FetchComponents/problem.ts の PROBLEM_CODE
export const APP_PROBLEM_CODE = {
    // 401 (セッションは削除され、以後の同じ Cookie は session_expired)
    USER_DEACTIVATED: 'user_deactivated',
    USER_NOT_SYNCED: 'user_not_synced',
    // 404 (他テナント・存在しない・削除済みを区別しない)
    USER_NOT_FOUND: 'user_not_found',
    ORGANIZATION_NOT_FOUND: 'organization_not_found',
    // 409 (user_self_modification_forbidden は拡張メンバー operation: SelfModificationOperation)
    USER_ALREADY_EXISTS: 'user_already_exists',
    ORGANIZATION_NAME_ALREADY_EXISTS: 'organization_name_already_exists',
    USER_SELF_MODIFICATION_FORBIDDEN: 'user_self_modification_forbidden',
    // 412
    USER_VERSION_CONFLICT: 'user_version_conflict',
    ORGANIZATION_VERSION_CONFLICT: 'organization_version_conflict',
    // 422 (errors に項目。invalid_organization_members は拡張メンバー user_ids)
    INVALID_USER_INPUT: 'invalid_user_input',
    INVALID_USER_ROLE: 'invalid_user_role',
    INVALID_ORGANIZATION_INPUT: 'invalid_organization_input',
    INVALID_ORGANIZATION_MEMBERS: 'invalid_organization_members',
    // 502 (AP の DB は変更していない)
    IDENTITY_PROVIDER_OPERATION_FAILED: 'identity_provider_operation_failed',
    // ToDo: 404 (他テナント・存在しない・削除済み・閲覧範囲外を区別しない)
    TODO_NOT_FOUND: 'todo_not_found',
    // ToDo: 403 (拡張メンバー operation: TodoOperation。権限の無い項目が実際に変わる更新)
    TODO_OPERATION_FORBIDDEN: 'todo_operation_forbidden',
    // ToDo: 412
    TODO_VERSION_CONFLICT: 'todo_version_conflict',
    // ToDo: 422 (invalid_todo_assignees は拡張メンバー user_ids・errors[].code は not_found / inactive、
    // invalid_todo_organizations は拡張メンバー organization_ids)
    INVALID_TODO_INPUT: 'invalid_todo_input',
    INVALID_TODO_ASSIGNEES: 'invalid_todo_assignees',
    INVALID_TODO_ORGANIZATIONS: 'invalid_todo_organizations',
} as const;

// If-Match ヘッダーの値を作る関数 (一覧の要素の version から `"<version>"` を作る。実体は shared/api/etag.ts)
export { ifMatchOf } from '@/shared/api/etag';

// ToDo の型 (500 行の上限のため別ファイルに置き、ここから再公開する。利用側は contract から import する)
export * from './todo_contract';

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
    /**
     * AP のユーザー ID (`t_user.id`、UUIDv7)。`GET /api/v1/users` の `id`・組織のメンバー ID と同じ値。
     * 認証基盤の `sub` ではない (`sub` は `/api/auth/app/status` の user.sub)。
     */
    id: string;
    /** ユーザー名。 */
    username: string | null;
    /** メールアドレス。 */
    email: string | null;
    /** テナント内のロール (`tenant_admin` / `member`)。 */
    roles: string[];
};

/**
 * ログイン中のユーザーが所属する組織 (OpenAPI: MeOrganization)。
 */
export type MeOrganization = {
    /** 組織 ID (UUIDv7。`GET /api/v1/organizations` の id と同じ値)。 */
    id: string;
    /** 組織名。 */
    name: string;
};

/**
 * `GET /api/v1/me` のレスポンス (OpenAPI: MeRead)。
 */
export type MeRead = {
    /** テナント。 */
    tenant: MeTenant;
    /** ユーザー。 */
    user: MeUser;
    /** 所属する有効な組織 (組織名順。論理削除済みを除く。所属が無ければ空配列。常にある)。 */
    organizations: MeOrganization[];
};

// ロール ///////////////////////////////////////////////////////////////////////

/** テナントのロール (01 §7.5)。 */
export type AppRole = 'tenant_admin' | 'member';

/** ロールの名前 */
export const APP_ROLE = {
    TENANT_ADMIN: 'tenant_admin',
    MEMBER: 'member',
} as const satisfies Record<string, AppRole>;

/**
 * テナントの既定ロール (レルムの既定ロール。ユーザーには常に付く)。
 * ロールの写し (UserRead.roles) は「直接付与したロール + 既定ロール」になる (POST の roles の省略時も member)。
 */
export const APP_DEFAULT_ROLES: readonly AppRole[] = [APP_ROLE.MEMBER];

/** 自分自身に対して拒否される操作 (409 user_self_modification_forbidden の拡張メンバー operation)。 */
export type SelfModificationOperation = 'deactivate' | 'remove_tenant_admin';

// ユーザー /////////////////////////////////////////////////////////////////////

/** ユーザー一覧の並び順。先頭に `-` で降順 (既定 `display_name`)。 */
export type UserSortKey = 'display_name' | '-display_name' | 'created_at' | '-created_at';

/**
 * テナント内のユーザー (OpenAPI: UserRead)。一覧の要素。
 * 姓・名・ロールは AP の DB の写し (最後に同期した時点の値。ログイン時・作成・更新・詳細の取得で更新される)。
 * 最新の値は詳細 (`GET /api/v1/users/{user_id}`。IdP から取り直す) で取得する。
 */
export type UserRead = {
    /** ユーザー ID (UUIDv7)。`/api/v1/me` の user.id、組織のメンバー ID と同じ値。 */
    id: string;
    /** メールアドレス (テナント内で一意)。 */
    email: string | null;
    /** 表示名 (`"{名} {姓}"`)。 */
    display_name: string;
    /** 名 (写し。未同期・未設定なら null)。 */
    first_name: string | null;
    /** 姓 (写し。未同期・未設定なら null)。 */
    last_name: string | null;
    /** テナントのロール (写し。`tenant_admin` / `member` の順。未同期なら空配列)。 */
    roles: AppRole[];
    /** 有効か。無効化されたユーザーはログインできない。 */
    is_active: boolean;
    /** 最終ログイン日時。一度もログインしていなければ null。 */
    last_login_at: string | null;
    /** 楽観ロックのバージョン (ETag と同じ値)。 */
    version: number;
    created_at: string;
    updated_at: string;
};

/**
 * ユーザーの詳細 (OpenAPI: UserDetail)。`UserRead` と同じ項目。ETag ヘッダー付き。
 * - `GET /api/v1/users/{user_id}`: 姓・名・ロールを IdP から取り直した値 (失敗は 502)。写しと違えば写しを更新するため、
 *   一覧の version より新しい version (と ETag) が返ることがある。If-Match には常にこの応答の ETag を使う。
 * - `PATCH` の応答・`POST` の user: 変更した項目は IdP に設定した値、変更しない項目は写しの値。
 */
export type UserDetail = UserRead;

/**
 * `GET /api/v1/users` のレスポンス (OpenAPI: UserPage)。姓・名・ロールは写しの値。
 */
export type UserPage = {
    items: UserRead[];
    /** 次のページのカーソル。最後のページでは null。 */
    next_cursor: string | null;
    /** 総件数 (AP の一覧は include_total を受け付けないため常に null)。 */
    total?: number | null;
};

/**
 * `GET /api/v1/users` のクエリ (API に送る形)。
 */
export type UserListQuery = {
    /** 1 ページの件数 (既定 50、1〜200)。ids の件数が limit を超える場合は next_cursor で続きを取得する。 */
    limit?: number;
    /** 前回のレスポンスの next_cursor (中身は解釈しない)。並び順を変えると 422。 */
    cursor?: string;
    sort?: UserSortKey;
    /** true で有効なユーザーのみ、false で無効化されたユーザーのみ。省略時は両方。 */
    is_active?: boolean;
    /**
     * ユーザー ID で絞り込む (カンマ区切りの UUID。重複を除いて最大 USER_IDS_QUERY_MAX 件)。
     * 存在しない ID・他テナントの ID は結果に含まれないだけ。空文字は 0 件 (items: [])。
     * UUID でない値・上限超は 422 invalid_user_input (errors[0].field は `ids`、code は USER_IDS_ERROR_CODE)。
     */
    ids?: string;
};

/** `GET /api/v1/users` の ids で一度に指定できる件数 (重複を除いた数)。 */
export const USER_IDS_QUERY_MAX = 100;

/** 422 invalid_user_input (errors[0].field: `ids`) の errors[].code。 */
export const USER_IDS_ERROR_CODE = {
    /** UUID でない値を含む。 */
    FORMAT: 'format',
    /** 重複を除いて USER_IDS_QUERY_MAX 件を超える。 */
    TOO_MANY: 'too_many',
} as const;

/**
 * `POST /api/v1/users` のリクエスト (OpenAPI: UserCreate)。
 */
export type UserCreate = {
    /** メールアドレス (1〜254 文字。テナント内で一意。重複は 409 user_already_exists)。 */
    email: string;
    /** 名 (1〜100 文字)。 */
    first_name: string;
    /** 姓 (1〜100 文字)。 */
    last_name: string;
    /** 付与するロール (1 件以上)。省略時は member。 */
    roles?: AppRole[];
    /** ログインに使うユーザー名 (英数字と `. _ @ + -` の 3 文字以上)。省略時はメールアドレス。 */
    username?: string | null;
};

/**
 * `PATCH /api/v1/users/{user_id}` のリクエスト (OpenAPI: UserUpdate)。送った項目だけを更新する。
 * null は指定できない (422)。first_name と last_name は両方を指定する。
 * 自分自身の無効化・自分の tenant_admin の解除は 409 (user_self_modification_forbidden)。
 * 応答は UserDetail (ETag 付き)。変更しない項目の姓・名・ロールは写しの値。
 */
export type UserUpdate = {
    first_name?: string;
    last_name?: string;
    /** 直接付与するロールの集合 (置き換え。1 件以上)。 */
    roles?: AppRole[];
    /** false で無効化、true で再有効化。 */
    is_active?: boolean;
};

/**
 * 作成したユーザーのログイン情報 (OpenAPI: UserCredentials)。一時パスワードは一度だけ返る (Cache-Control: no-store)。
 */
export type UserCredentials = {
    username: string;
    temporary_password: string;
};

/**
 * `POST /api/v1/users` のレスポンス (OpenAPI: UserCreated)。201、Location / ETag 付き。user の姓・名・ロールは作成時に設定した値。
 */
export type UserCreated = {
    user: UserDetail;
    credentials: UserCredentials;
};

// 組織 /////////////////////////////////////////////////////////////////////////

/** 組織一覧の並び順。先頭に `-` で降順 (既定 `name`)。 */
export type OrganizationSortKey = 'name' | '-name' | 'created_at' | '-created_at';

/**
 * 組織 (OpenAPI: OrganizationRead)。一覧の要素・`PATCH` のレスポンス (メンバーを含まない)。
 */
export type OrganizationRead = {
    id: string;
    /** 組織名 (有効な組織の中で一意。大文字小文字を区別しない)。 */
    name: string;
    /** 楽観ロックのバージョン (ETag と同じ値)。 */
    version: number;
    created_at: string;
    updated_at: string;
};

/**
 * 組織の詳細 (OpenAPI: OrganizationDetail)。`GET` / `POST` / `PUT .../members` のレスポンス。ETag ヘッダー付き。
 */
export type OrganizationDetail = OrganizationRead & {
    /** メンバーのユーザー ID (ID 順)。ユーザーの情報は `GET /api/v1/users` で取得する。 */
    member_ids: string[];
};

/**
 * `GET /api/v1/organizations` のレスポンス (OpenAPI: OrganizationPage)。論理削除済みを除く。メンバーは含まない。
 */
export type OrganizationPage = {
    items: OrganizationRead[];
    next_cursor: string | null;
    /** 総件数 (AP の一覧は include_total を受け付けないため常に null)。 */
    total?: number | null;
};

/**
 * `GET /api/v1/organizations` のクエリ。
 */
export type OrganizationListQuery = {
    limit?: number;
    cursor?: string;
    sort?: OrganizationSortKey;
};

/**
 * `POST /api/v1/organizations` のリクエスト (OpenAPI: OrganizationCreate)。メンバーは空で作られる。
 */
export type OrganizationCreate = {
    /** 組織名 (1〜100 文字。重複は 409 organization_name_already_exists)。 */
    name: string;
};

/**
 * `PATCH /api/v1/organizations/{organization_id}` のリクエスト (OpenAPI: OrganizationUpdate)。
 */
export type OrganizationUpdate = {
    name: string;
};

/**
 * `PUT /api/v1/organizations/{organization_id}/members` のリクエスト (OpenAPI: OrganizationMembersReplace)。全置換。
 * 最大 1000 件。テナント内に存在しないユーザーは 422 (invalid_organization_members、拡張メンバー user_ids)。
 */
export type OrganizationMembersReplace = {
    user_ids: string[];
};
