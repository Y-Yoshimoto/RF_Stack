/**
 * @desc 開発用ログインバイパスの入口ページ
 *
 * Playwright テストや手動での動作確認時に、KeyCloak のログイン画面を経由せず
 * 認証済み状態にするための導線。クエリで指定されたプロファイルを FastAPI の
 * `/api/auth/dev-login` に引き渡す。
 *
 * このページは `VITE_ENABLE_DEV_LOGIN` が真のときだけルートに登録される
 * (production ビルドではバンドルから除去される)。ただしこれは導線を消すだけであり、
 * 実際の防御は FastAPI 側でルート自体を登録しないことによる。
 */
import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Typography } from '@mui/material';

/** 既定で使用するプロファイル名。FastAPI 側の DEV_PROFILES (modules/auth/dev_profiles.py) と対応する。 */
const DEFAULT_PROFILE = 'alpha-admin';

export const DevLoginPage = () => {
    const [search_params] = useSearchParams();

    useEffect(() => {
        const profile = search_params.get('as') || DEFAULT_PROFILE;
        const next_path = search_params.get('next');

        const query = new URLSearchParams({ as: profile });
        if (next_path) query.set('next', next_path);

        // Cookie の付与とリダイレクト追従のため、fetch ではなくトップレベル遷移にする。
        window.location.href = `/api/auth/dev-login?${query.toString()}`;
    }, [search_params]);

    return (
        <Typography variant="h6" align="center" data-testid='dev-login-message'>
            開発用ログインで認証しています...
        </Typography>
    );
};

export default DevLoginPage;
