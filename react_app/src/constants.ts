// 定数設定関数

// Webストレージのキー定数
export const STORAGE_KEY = {
    // 認可情報
    ROLES: 'auth_roles',
    PERMISSIONS: 'auth_permissions',
};

// CSRF 対策のカスタムヘッダー (docs/architecture/03-conventions.md §1)。
// 変更系メソッド (POST / PUT / PATCH / DELETE) には必ず付与する。FastAPI 側は modules/auth/csrf.py で検証する。
export const CSRF_HEADER = {
    NAME: 'X-Requested-With',
    VALUE: 'rf-stack',
};

// BFF 認証 API のエンドポイント (プレーン別。docs/architecture/01-platform-concepts.md §10.2)
export const AUTH_API = {
    // アプリケーションプレーン (テナント)
    APP_LOGIN: '/api/auth/app/login',
    APP_STATUS: '/api/auth/app/status',
    APP_LOGOUT: '/api/auth/app/logout',
    // コントロールプレーン (SaaS 管理者)
    CP_LOGIN: '/api/auth/cp/login',
    CP_STATUS: '/api/auth/cp/status',
    CP_LOGOUT: '/api/auth/cp/logout',
};
