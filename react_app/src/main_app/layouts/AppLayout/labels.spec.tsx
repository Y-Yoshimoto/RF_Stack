// AP のナビゲーション項目のテスト (ユーザー管理・組織管理・プロフィールが有効、ToDo も有効)
import { describe, expect, it } from 'vitest';
import { appNavItemsOf } from './labels';

describe('appNavItemsOf', () => {
    it('ユーザー管理・組織管理・プロフィールの遷移先をテナントのパスで返す', () => {
        const items = Object.fromEntries(appNavItemsOf('alpha').map((item) => [item.id, item.to]));
        expect(items).toMatchObject({ home: '/alpha/', users: '/alpha/users', organizations: '/alpha/organizations', profile: '/alpha/profile' });
    });

    it('ToDo の遷移先をテナントのパスで返す', () => {
        expect(appNavItemsOf('alpha').find((item) => item.id === 'todo')?.to).toBe('/alpha/todos');
    });
});
