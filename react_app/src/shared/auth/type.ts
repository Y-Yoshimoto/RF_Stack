// BFF 認証 API (`/api/auth/*`) の型と、プレーン共通の認証状態の型
// 正は FastAPI の main_app/route/auth/schemas.py (AuthUser / AppAuthStatus / CpAuthStatus / LogoutResult)。
// プレーン固有の型 (AP のテナントコードを持つセッション等) は各プレーンの auth/ で定義する。

/**
 * 認証のプレーン (AP: アプリケーションプレーン、CP: コントロールプレーン)。
 */
export type AuthPlane = 'app' | 'cp';

/**
 * 認証ステータス API が返すユーザー情報 (FastAPI: AuthUser)。
 */
export interface AuthStatusUser {
    /** ユーザー一意識別子 (認証基盤の `sub`)。 */
    sub: string;
    /** 表示用ユーザー名。 */
    preferred_username: string | null;
    /** メールアドレス。 */
    email: string | null;
    /** ロール (AP: tenant_admin / member、CP: saas_admin / saas_viewer)。画面の出し分け用であり、保護はサーバー側で行う。 */
    roles: string[];
}

/**
 * AP の認証ステータス API (`GET /api/auth/app/status`) のレスポンス (OpenAPI: AppAuthStatus)。
 * 認証済みの場合のみ 200 で返り、未認証・セッション切れ・別プレーンのセッションは 401 (Problem Details) になる。
 * レルム名・クライアント ID・tenant_id は返らない。
 */
export interface AppAuthStatusResponse {
    /** 常に true (未認証は 401)。 */
    authenticated: true;
    plane: 'app';
    /** ログイン中のテナントコード。ルートガードで URL のテナントコードと照合する。 */
    tenant_code: string;
    user: AuthStatusUser;
}

/**
 * CP の認証ステータス API (`GET /api/auth/cp/status`) のレスポンス (OpenAPI: CpAuthStatus)。
 */
export interface CpAuthStatusResponse {
    /** 常に true (未認証は 401)。 */
    authenticated: true;
    plane: 'cp';
    user: AuthStatusUser;
}

/**
 * 認証ステータス API のレスポンス (プレーン共通の処理で使う)。
 */
export type AuthStatusResponse = AppAuthStatusResponse | CpAuthStatusResponse;

/**
 * ログアウト API (`POST /api/auth/app/logout` / `POST /api/auth/cp/logout`) のレスポンス (OpenAPI: LogoutResult)。
 * 変更系のため `X-Requested-With: rf-stack` が必須 (無ければ 403 `csrf_validation_failed`。requestFetch が付与する)。
 */
export interface LogoutResponse {
    /**
     * ブラウザをトップレベル遷移させる URL (認証基盤の RP-Initiated Logout)。
     * 完了後は AP: `/{tenant_code}/login`、CP: `/cp/login` に戻る。セッションが無かった場合はそのログイン画面の URL そのもの。
     */
    logout_url: string;
}

/**
 * プレーンのセッションの状態。
 * - loading: 状態 API の応答待ち
 * - unauthenticated: 未認証 (状態 API が 401)
 * - authenticated: 認証済み (session はプレーン固有の形)
 * - error: 401 以外の失敗 (503・ネットワークエラー等)。未認証とは区別し、握り潰さない
 */
export type SessionState<S> =
    | { status: 'loading' }
    | { status: 'unauthenticated' }
    | { status: 'authenticated'; session: S }
    | { status: 'error'; error: unknown };

/**
 * ログイン画面・ランディングへ `?error=` で渡されるエラーコード (FastAPI: modules/auth/redirects.py の LoginErrorCode)。
 * 文言の出し分けは画面側で行う。一覧に無い値が来ることもある (画面は既定の文言で扱う)。
 */
export const LOGIN_ERROR_CODE = {
    TENANT_UNAVAILABLE: 'tenant_unavailable',
    INVALID_AUTH_STATE: 'invalid_auth_state',
    AUTHORIZATION_FAILED: 'authorization_failed',
    TOKEN_EXCHANGE_FAILED: 'token_exchange_failed',
    INVALID_TOKEN: 'invalid_token',
    LOGIN_REJECTED: 'login_rejected',
    IDENTITY_PROVIDER_UNREACHABLE: 'identity_provider_unreachable',
    SERVICE_UNAVAILABLE: 'service_unavailable',
    INTERNAL_ERROR: 'internal_error',
} as const;
