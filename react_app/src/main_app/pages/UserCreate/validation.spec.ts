// ユーザー作成フォームの入力検証のテスト
import { describe, expect, it } from 'vitest';
import { NAME_MAX_LENGTH, validateUserCreate, type UserCreateValues } from './validation';

const VALID: UserCreateValues = { email: 'taro@alpha.example', last_name: '山田', first_name: '太郎', roles: ['member'] };

describe('validateUserCreate', () => {
    it('正しい入力ではエラーが無い', () => {
        expect(validateUserCreate(VALID)).toEqual({});
    });

    it('必須項目が空 (空白のみを含む) ならエラー', () => {
        const errors = validateUserCreate({ email: ' ', last_name: '', first_name: '  ', roles: [] });
        expect(Object.keys(errors).sort()).toEqual(['email', 'first_name', 'last_name', 'roles']);
    });

    it('メールアドレスの形式が不正ならエラー', () => {
        expect(validateUserCreate({ ...VALID, email: 'taro-at-example' }).email).toContain('形式');
    });

    it('姓・名が 100 文字を超えるとエラー', () => {
        const errors = validateUserCreate({ ...VALID, last_name: 'あ'.repeat(NAME_MAX_LENGTH + 1) });
        expect(errors.last_name).toContain('100');
        expect(errors.first_name).toBeUndefined();
    });
});
