// テナント作成フォームの入力検査のテスト
import { describe, expect, it } from 'vitest';
import { classifyCpError } from '@/control_plane_app/api/errors';
import { ApiError } from '@/utils/libs/FetchComponents/problem';
import { EMPTY_TENANT_CREATE_FORM, serverErrorsToFormErrors, toTenantCreate, validateTenantCreateForm } from './validation';

const VALID = { tenant_code: 'acme-1', name: 'ACME', email: 'admin@example.com', last_name: '', first_name: '' };

describe('validateTenantCreateForm', () => {
    it('正しい入力ではエラーが無い', () => {
        expect(validateTenantCreateForm(VALID)).toEqual({});
    });

    it('未入力は、すべての必須項目がエラーになる', () => {
        expect(Object.keys(validateTenantCreateForm(EMPTY_TENANT_CREATE_FORM)).sort()).toEqual(['email', 'name', 'tenant_code']);
    });

    it('テナントコードは、形式違反と予約語を弾く', () => {
        expect(validateTenantCreateForm({ ...VALID, tenant_code: 'a_b' }).tenant_code).toMatch(/英小文字・数字・ハイフン/);
        expect(validateTenantCreateForm({ ...VALID, tenant_code: 'ab' }).tenant_code).toBeDefined();
        expect(validateTenantCreateForm({ ...VALID, tenant_code: 'admin' }).tenant_code).toMatch(/予約語/);
    });

    it('テナントコードは、前後の空白と大文字を整えてから検査する', () => {
        expect(validateTenantCreateForm({ ...VALID, tenant_code: '  ACME-1 ' })).toEqual({});
    });

    it('メールアドレスの形式を検査する', () => {
        expect(validateTenantCreateForm({ ...VALID, email: 'not-an-email' }).email).toBeDefined();
    });

    it('名前の長さを検査する', () => {
        expect(validateTenantCreateForm({ ...VALID, name: 'あ'.repeat(101) }).name).toBeDefined();
    });
});

describe('toTenantCreate', () => {
    it('テナントコードを整え、姓名が空なら送らない', () => {
        expect(toTenantCreate({ ...VALID, tenant_code: ' ACME-1 ' })).toEqual({ tenant_code: 'acme-1', name: 'ACME', initial_admin: { email: 'admin@example.com' } });
    });

    it('姓名があれば送る', () => {
        expect(toTenantCreate({ ...VALID, last_name: '山田', first_name: '太郎' }).initial_admin).toEqual({ email: 'admin@example.com', last_name: '山田', first_name: '太郎' });
    });
});

describe('serverErrorsToFormErrors', () => {
    it('409 のテナントコード重複は、テナントコード欄のエラーにする', () => {
        const info = classifyCpError(new ApiError(409, 'x', { type: 't', title: 't', status: 409, detail: 'd', instance: '/', code: 'tenant_code_already_exists' }));
        expect(serverErrorsToFormErrors(info).tenant_code).toMatch(/既に使われています/);
    });

    it('422 の項目エラーは、項目名の末尾で入力欄に対応付ける', () => {
        const info = classifyCpError(new ApiError(422, 'x', { type: 't', title: 't', status: 422, detail: 'd', instance: '/', code: 'validation_error', errors: [{ field: 'initial_admin.email', code: 'c', message: 'メールが不正' }] }));
        expect(serverErrorsToFormErrors(info)).toEqual({ email: 'メールが不正' });
    });
});
