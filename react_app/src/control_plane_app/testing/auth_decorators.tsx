// Storybook のストーリー用: CP の認証状態 (認証済み) を注入するデコレーター (アプリ本体からは import しない)
import type { Decorator } from '@storybook/react-vite';
import { ControlPlaneAuthContext, type CpAuthValue } from '@/control_plane_app/auth/context';

/**
 * ストーリーの parameters.cp_auth で指定する値 (すべて省略可)。
 */
export type CpAuthStoryParameters = {
    user_name?: string;
    /** saas_admin / saas_viewer。 */
    roles?: string[];
    /** true ならログアウトが失敗する (reject する)。 */
    logout_fails?: boolean;
};

const noop = () => undefined;

/**
 * CP の認証状態を注入するデコレーター (useCpSession / useCpPermissions / useCpAuth を使う画面用。parameters.cp_auth で値を変える)
*/
// eslint-disable-next-line @typescript-eslint/naming-convention -- Storybook のデコレーターは第 1 引数をコンポーネント (<Story />) として描画する慣習のため
export const withCpAuth: Decorator = (Story, context) => {
    const { user_name = 'cp-admin', roles = ['saas_admin'], logout_fails = false } = (context.parameters.cp_auth ?? {}) as CpAuthStoryParameters;
    const value: CpAuthValue = {
        state: { status: 'authenticated', session: { user: { sub: 'story-sub', preferred_username: user_name, email: `${user_name}@example.com`, roles } } },
        refresh: noop,
        login: noop,
        logout: () => (logout_fails ? Promise.reject(new Error('story: logout failed')) : Promise.resolve()),
        reportApiError: noop,
    };
    return (
        <ControlPlaneAuthContext value={value}>
            <Story />
        </ControlPlaneAuthContext>
    );
};
