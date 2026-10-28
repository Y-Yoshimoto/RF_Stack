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
} as const;
