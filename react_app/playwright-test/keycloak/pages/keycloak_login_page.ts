/**
 * Keycloak のログイン画面のページオブジェクト。
 *
 * Keycloak の画面は keycloak_c の実画面で、バージョン (テーマ) によって DOM が変わりうる。
 * ロケーターはこのファイルだけに置き、テスト側は Keycloak の DOM に依存しない。
 * 現行 (Keycloak 26 の keycloak.v2 テーマ) の要素 ID を第一候補とし、ラベル・ロールをフォールバックにする。
 * Keycloak を更新して壊れた場合は、このファイルだけを直す。
 */
import { expect, type Locator, type Page } from '@playwright/test';

/** Keycloak の URL パス (KC_HTTP_RELATIVE_PATH。.env.default の `keycloak`) */
const KEYCLOAK_PATH_PREFIX = '/keycloak/';

export class KeycloakLoginPage {
    readonly page: Page;
    readonly username_input: Locator;
    readonly password_input: Locator;
    readonly submit_button: Locator;
    /** 認証失敗 (ユーザー名またはパスワードの誤り) のメッセージ */
    readonly error_message: Locator;

    constructor(page: Page) {
        this.page = page;
        this.username_input = page.locator('#username').or(page.getByLabel(/username|ユーザー名/i));
        this.password_input = page.locator('#password').or(page.getByLabel(/^password|^パスワード/i));
        this.submit_button = page.locator('#kc-login').or(page.getByRole('button', { name: /sign in|ログイン/i }));
        this.error_message = page.locator('#input-error-username, #input-error, .kc-feedback-text, [role="alert"]').first();
    }

    /**
     * Keycloak のログイン画面が表示されていることを確認する
     * @param realm 期待するレルム名 (例: tenant-alpha / control-plane)
     */
    async expectShown(realm: string): Promise<void> {
        await expect(this.page).toHaveURL((url) => url.pathname.startsWith(`${KEYCLOAK_PATH_PREFIX}realms/${realm}/`));
        await expect(this.submit_button).toBeVisible();
    }

    /**
     * ユーザー名とパスワードを入力して送信する
     * @param username ユーザー名
     * @param password パスワード
     */
    async submitCredentials(username: string, password: string): Promise<void> {
        await this.username_input.fill(username);
        await this.password_input.fill(password);
        await this.submit_button.click();
    }

    /**
     * 認証に失敗し、Keycloak の画面に留まっていることを確認する
     */
    async expectLoginFailed(): Promise<void> {
        await expect(this.error_message).toBeVisible();
        await expect(this.page).toHaveURL((url) => url.pathname.startsWith(KEYCLOAK_PATH_PREFIX));
        await expect(this.submit_button).toBeVisible();
    }
}
