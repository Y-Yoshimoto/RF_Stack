/**
 * 認証済みユーザーの基本情報。
 */
export interface AuthUserInfo {
    /** ユーザー一意識別子。 */
    sub?: string;
    /** 表示用ユーザー名。 */
    preferred_username?: string;
    /** メールアドレス。 */
    email?: string;
    /** 所属レルム。 */
    realm?: string;
}

/**
 * 認証ステータス API のレスポンス。
 */
export interface AuthStatusResponse {
    /** 認証済みかどうか。 */
    authenticated: boolean;
    /** 認証済み時のユーザー情報。 */
    user?: AuthUserInfo;
}

/**
 * 認証情報を扱うオブジェクト。
 */
export interface AuthNInfo {
    /** 認証状態。 */
    isAuthN: boolean | undefined;
    /** 認証状態の更新関数。 */
    setIsAuthN: React.Dispatch<React.SetStateAction<boolean | undefined>>;
    /** ユーザー情報。 */
    userInfo: AuthUserInfo | undefined;
    /** ユーザー情報の更新関数。 */
    setUserInfo: React.Dispatch<React.SetStateAction<AuthUserInfo | undefined>>;
}

/**
 * 認可情報を扱うオブジェクト。
 */
export interface AuthZInfo {
    /** 認可状態。 */
    isAuthZ: boolean | undefined;
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
    isAuthN: boolean | undefined;
    /** 認可状態。 */
    isAuthZ: boolean | undefined;
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
    authNInfo: AuthNInfo;
    /** 認可情報。 */
    authZInfo: AuthZInfo;
    /** 認証認可ステータス。 */
    authStatus: Status;
    /** ユーザー情報。 */
    userInfo: AuthUserInfo | undefined;
    /** 操作用コマンド。 */
    command: CommandInfo;
}
