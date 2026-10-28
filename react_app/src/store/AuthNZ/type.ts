/**
 * 認証のプレーン (AP: アプリケーションプレーン、CP: コントロールプレーン)。
 */
export type AuthPlane = 'app' | 'cp';

/**
 * 認証ステータス API が返すユーザー情報 (FastAPI の main_app/route/auth/apiapp.py `_status_payload`)。
 * `sub` / `preferred_username` / `email` はセッションに無ければ null になる。
 */
export interface AuthStatusUser {
    /** ユーザー一意識別子 (KeyCloak の `sub`)。 */
    sub: string | null;
    /** 表示用ユーザー名。 */
    preferred_username: string | null;
    /** メールアドレス。 */
    email: string | null;
    /** ロール (AP: tenant_admin / member、CP: saas_admin / saas_viewer)。画面の出し分け用であり、保護はサーバー側で行う。 */
    roles: string[];
}

/**
 * 認証済みユーザーの基本情報 (ストアで保持する形)。
 */
export interface AuthUserInfo extends AuthStatusUser {
    /** ログイン中のテナントコード (AP のみ。状態 API の tenant_code)。 */
    tenant_code?: string | null;
}

/**
 * 認証ステータス API (`GET /api/auth/app/status` / `GET /api/auth/cp/status`) のレスポンス。
 * 認証済みの場合のみ 200 で返り、未認証・セッション切れ・別プレーンのセッションは 401 (Problem Details) になる。
 * レルム名・クライアント ID・tenant_id は返らない。
 */
export interface AuthStatusResponse {
    /** 認証済みかどうか (200 の応答では常に true)。 */
    authenticated: boolean;
    /** セッションのプレーン。 */
    plane: AuthPlane;
    /** ログイン中のテナントコード (AP のみ。CP の応答には含まれない)。 */
    tenant_code?: string | null;
    /** ユーザー情報。 */
    user: AuthStatusUser;
}

/**
 * ログアウト API (`POST /api/auth/app/logout` / `POST /api/auth/cp/logout`) のレスポンス。
 * 変更系のため `X-Requested-With: rf-stack` が必須 (無ければ 403 `csrf_validation_failed`)。
 */
export interface LogoutResponse {
    /** ブラウザをトップレベル遷移させる URL (KeyCloak の RP-Initiated Logout、またはフロントエンドの URL)。 */
    logout_url: string;
}

/**
 * 認証情報を扱うオブジェクト。
 */
export interface AuthNInfo {
    /** 認証状態。 */
    is_auth_n: boolean | undefined;
    /** 認証状態の更新関数。 */
    setIsAuthN: React.Dispatch<React.SetStateAction<boolean | undefined>>;
    /** ユーザー情報。 */
    user_info: AuthUserInfo | undefined;
    /** ユーザー情報の更新関数。 */
    setUserInfo: React.Dispatch<React.SetStateAction<AuthUserInfo | undefined>>;
}

/**
 * 認可情報を扱うオブジェクト。
 */
export interface AuthZInfo {
    /** 認可状態。 */
    is_auth_z: boolean | undefined;
    /** 認可状態の更新関数。 */
    setIsAuthZ: React.Dispatch<React.SetStateAction<boolean | undefined>>;
    /** ロール情報。 */
    roles: string | undefined;
    /** ロール情報の更新関数。 */
    setRoles: React.Dispatch<React.SetStateAction<string | undefined>>;
    /** パーミッション情報。 */
    permissions: string[] | undefined;
    /** パーミッション情報の更新関数。 */
    setPermissions: React.Dispatch<React.SetStateAction<string[] | undefined>>;
}

/**
 * 認証認可ステータスの集約情報。
 */
export interface Status {
    /** 認証状態。 */
    is_auth_n: boolean | undefined;
    /** 認可状態。 */
    is_auth_z: boolean | undefined;
}

/**
 * 認証認可関連のコマンド群。
 */
export interface CommandInfo {
    /**
     * ログイン状態を反映する。
     * @param response 認証 API のレスポンス。
     */
    login: (response: AuthStatusResponse) => void;
    /** ログアウト状態へ遷移する。 */
    logout: () => void;
}

/**
 * useAuthNZ フックの返却型。
 */
export interface UseAuthNZReturn {
    /** 認証情報。 */
    auth_n_info: AuthNInfo;
    /** 認可情報。 */
    auth_z_info: AuthZInfo;
    /** 認証認可ステータス。 */
    auth_status: Status;
    /** ユーザー情報。 */
    user_info: AuthUserInfo | undefined;
    /** 操作用コマンド。 */
    command: CommandInfo;
}
