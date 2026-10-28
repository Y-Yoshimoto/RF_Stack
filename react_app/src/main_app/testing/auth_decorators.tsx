// Storybook のストーリー用: AP の認証状態 (認証済み) を注入するデコレーター (アプリ本体からは import しない)
import type { Decorator } from '@storybook/react-vite';
import { AppAuthContext, type AppAuthValue } from '@/main_app/auth/context';

/**
 * ストーリーの parameters.app_auth で指定する値 (すべて省略可)。
 */
export type AppAuthStoryParameters = {
    tenant_code?: string;
    user_name?: string;
    roles?: string[];
    /** true ならログアウトが失敗する (reject する)。 */
    logout_fails?: boolean;
};

const noop = () => undefined;

/**
 * AP の認証状態を注入するデコレーター (useAppSession / useAppAuth を使う画面用。parameters.app_auth で値を変える)
*/
// eslint-disable-next-line @typescript-eslint/naming-convention -- Storybook のデコレーターは第 1 引数をコンポーネント (<Story />) として描画する慣習のため
export const withAppAuth: Decorator = (Story, context) => {
    const { tenant_code = 'alpha', user_name = 'alpha-admin', roles = ['tenant_admin', 'member'], logout_fails = false } = (context.parameters.app_auth ?? {}) as AppAuthStoryParameters;
    const value: AppAuthValue = {
        state: { status: 'authenticated', session: { tenant_code, user: { sub: 'story-sub', preferred_username: user_name, email: `${user_name}@example.com`, roles } } },
        blocked: null,
        refresh: noop,
        login: noop,
        logout: () => (logout_fails ? Promise.reject(new Error('story: logout failed')) : Promise.resolve()),
        reportApiError: noop,
    };
    return (
        <AppAuthContext value={value}>
            <Story />
        </AppAuthContext>
    );
};
