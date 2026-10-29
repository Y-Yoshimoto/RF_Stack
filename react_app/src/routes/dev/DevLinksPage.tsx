/**
 * @desc 開発用: 主要な画面へのリンク一覧 (`/link`。開発モードのみ)
 * 開発用ログインのプロファイル (FastAPI: modules/auth/dev_profiles.py) と、各プレーンの入口を並べる。
 */
import { Link } from 'react-router-dom';
import { CP_HOME_PATH, CP_LOGIN_PATH } from '@/control_plane_app/paths';
import { appHomePath, appLoginPath, LANDING_PATH } from '@/main_app/paths';
import { DEV_LOGIN_PATH } from './DevLoginPage';

/** 開発用のテナント (シード。02 §7.1) */
const DEV_TENANT_CODE = 'alpha';
/** 開発用ログインのプロファイル (02 §7.2) */
const DEV_PROFILES = ['alpha-admin', 'alpha-member', 'beta-member', 'cp-admin', 'cp-viewer'] as const;

/** リンクの一覧 */
export const DEV_LINKS: ReadonlyArray<{ label: string; path: string }> = [
    { label: 'landing', path: LANDING_PATH },
    ...DEV_PROFILES.map((profile) => ({ label: `dev-login as ${profile}`, path: `${DEV_LOGIN_PATH}?${new URLSearchParams({ as: profile }).toString()}` })),
    { label: `AP login (${DEV_TENANT_CODE})`, path: appLoginPath(DEV_TENANT_CODE) },
    { label: `AP home (${DEV_TENANT_CODE})`, path: appHomePath(DEV_TENANT_CODE) },
    { label: 'CP login', path: CP_LOGIN_PATH },
    { label: 'CP home', path: CP_HOME_PATH },
];

export const DevLinksPage = () => {
    return (
        <>
            <h4>Path Links</h4>
            <ul>
                {DEV_LINKS.map(({ label, path }) => <li key={path}><Link to={path}>{label}</Link></li>)}
            </ul>
        </>
    );
};

export default DevLinksPage;
