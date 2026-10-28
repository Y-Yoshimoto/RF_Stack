/**
 * @desc 開発用ログインバイパスの入口ページ (`/dev-login`。開発モードのみ)
 *
 * Playwright テストや手動での動作確認時に、KeyCloak のログイン画面を経由せず
 * 認証済み状態にするための導線。クエリで指定されたプロファイルを FastAPI の
 * `/api/auth/dev-login` に引き渡す。ログイン後の遷移先は FastAPI が決める
 * (`next` 省略時は AP: `/{tenant_code}/`、CP: `/cp/`。modules/auth/redirects.py)。
 *
 * このページは import.meta.env.MODE が development のときだけルートに登録される
 * (production ビルドではバンドルから除去される。routes/AppRoutes.tsx)。ただしこれは導線を消すだけであり、
 * 実際の防御は FastAPI 側でルート自体を登録しないことによる。
 */
import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Typography } from '@mui/material';
import { assignLocation } from '@/shared/auth/session';

/** このページのパス (予約語) */
export const DEV_LOGIN_PATH = '/dev-login';
/** FastAPI の開発用ログイン API */
export const DEV_LOGIN_API = '/api/auth/dev-login';
/** 既定で使用するプロファイル名。FastAPI 側の DEFAULT_DEV_PROFILE (modules/auth/dev_profiles.py) と対応する。 */
export const DEFAULT_PROFILE = 'alpha-admin';

/**
 * 開発用ログイン API の URL を組み立てる関数
 * `next` はパスのみ受け付ける (`//host` 等は渡さない。FastAPI 側でも検証される)。
 * @param {URLSearchParams} search_params このページのクエリ (`as` / `next`)
 * @returns {string} `/api/auth/dev-login?as=...[&next=...]`
*/
export const buildDevLoginUrl = (search_params: URLSearchParams): string => {
    const query = new URLSearchParams({ as: search_params.get('as') || DEFAULT_PROFILE });
    const next_path = search_params.get('next');
    if (next_path && next_path.startsWith('/') && !next_path.startsWith('//')) query.set('next', next_path);
    return `${DEV_LOGIN_API}?${query.toString()}`;
};

export const DevLoginPage = () => {
    const [search_params] = useSearchParams();

    useEffect(() => {
        // Cookie の付与とリダイレクト追従のため、fetch ではなくトップレベル遷移にする。
        assignLocation(buildDevLoginUrl(search_params));
    }, [search_params]);

    return (
        <Typography variant="h6" align="center" data-testid='dev-login-message'>
            開発用ログインで認証しています...
        </Typography>
    );
};

export default DevLoginPage;
