// AP の API 層 (URL・本文の組み立て・自分自身への禁止操作の判定・エラー分類・権限) のテスト
import { describe, expect, it } from 'vitest';
import { appPermissionsOf } from '@/main_app/auth/permissions';
import { ApiError, type ProblemDetails } from '@/utils/libs/FetchComponents/problem';
import { ifMatchOf } from './contract';
import { AppGuardError, classifyAppError } from './errors';
import { buildOrganizationListUrl, toOrganizationListQuery } from './organizations';
import { buildUserListUrl, selfModificationOf, toUserListQuery, toUserUpdate } from './users';

const SELF = 'self-id';

/**
 * Problem Details 付きの ApiError を作る関数
 * @param {number} status ステータス
 * @param {string} code エラーコード
 * @param {Partial<ProblemDetails>} extra 追加の項目
 * @returns {ApiError} 例外
*/
const apiErrorOf = (status: number, code: string, extra: Partial<ProblemDetails> = {}) => new ApiError(status, 'x', { type: 'about:blank', title: code, status, detail: code, instance: '/', code, errors: [], ...extra });

describe('一覧の URL', () => {
    it('ユーザー: sort・is_active・limit・cursor をクエリにする (false も送る)', () => {
        expect(buildUserListUrl(toUserListQuery({}))).toBe('/api/v1/users');
        expect(buildUserListUrl({ ...toUserListQuery({ sort: '-created_at', is_active: false, limit: 20 }), cursor: 'c1' })).toBe('/api/v1/users?limit=20&cursor=c1&sort=-created_at&is_active=false');
    });

    it('組織: sort・limit をクエリにする', () => {
        expect(buildOrganizationListUrl(toOrganizationListQuery({}))).toBe('/api/v1/organizations');
        expect(buildOrganizationListUrl(toOrganizationListQuery({ sort: 'name', limit: 5 }))).toBe('/api/v1/organizations?limit=5&sort=name');
    });
});

describe('toUserUpdate', () => {
    it('指定した項目だけを入れる (姓名は両方、ロールは重複を除く)', () => {
        expect(toUserUpdate({})).toEqual({});
        expect(toUserUpdate({ name: { first_name: '太郎', last_name: '山田' } })).toEqual({ first_name: '太郎', last_name: '山田' });
        expect(toUserUpdate({ roles: ['member', 'member', 'tenant_admin'], is_active: false })).toEqual({ roles: ['member', 'tenant_admin'], is_active: false });
    });
});

describe('selfModificationOf', () => {
    it('自分自身の無効化・tenant_admin の解除を判定する', () => {
        expect(selfModificationOf(SELF, SELF, { is_active: false })).toBe('deactivate');
        expect(selfModificationOf(SELF, SELF, { roles: ['member'] })).toBe('remove_tenant_admin');
        expect(selfModificationOf(SELF, SELF, { roles: ['tenant_admin'], is_active: true, name: { first_name: 'a', last_name: 'b' } })).toBeNull();
    });

    it('他のユーザー・自分の ID が未取得なら判定しない', () => {
        expect(selfModificationOf('other', SELF, { is_active: false })).toBeNull();
        expect(selfModificationOf(SELF, null, { is_active: false })).toBeNull();
    });
});

describe('classifyAppError', () => {
    it.each([
        [412, 'user_version_conflict', 'version_conflict', true],
        [412, 'organization_version_conflict', 'version_conflict', true],
        [428, 'precondition_required', 'precondition_required', true],
        [400, 'invalid_if_match', 'precondition_required', true],
        [403, 'forbidden', 'forbidden', false],
        [409, 'user_self_modification_forbidden', 'conflict', false],
        [409, 'organization_name_already_exists', 'conflict', false],
        [404, 'user_not_found', 'not_found', false],
        [401, 'user_deactivated', 'unauthenticated', false],
        [401, 'session_expired', 'unauthenticated', false],
        [502, 'identity_provider_operation_failed', 'external_failure', false],
    ])('%i %s は %s (requires_reload: %s)', (status, code, kind, requires_reload) => {
        expect(classifyAppError(apiErrorOf(status, code))).toMatchObject({ status, code, kind, requires_reload });
    });

    it('422 invalid_cursor (項目エラー) は先頭から取り直す', () => {
        const error = apiErrorOf(422, 'validation_error', { errors: [{ field: 'cursor', code: 'invalid_cursor', message: 'x' }] });
        expect(classifyAppError(error)).toMatchObject({ kind: 'invalid_input', requires_reload: true });
    });

    it('409 の拡張メンバー operation を problem で参照できる', () => {
        expect(classifyAppError(apiErrorOf(409, 'user_self_modification_forbidden', { operation: 'deactivate' })).problem?.operation).toBe('deactivate');
    });

    it('API を呼ばずに弾いた理由を分類する (自分自身への操作は API と同じ code)', () => {
        expect(classifyAppError(new AppGuardError('write_not_allowed'))).toMatchObject({ kind: 'forbidden', status: null, code: null });
        expect(classifyAppError(new AppGuardError('missing_etag'))).toMatchObject({ kind: 'precondition_required', requires_reload: true });
        expect(classifyAppError(new AppGuardError('action_in_progress')).kind).toBe('busy');
        expect(classifyAppError(new AppGuardError('self_deactivate'))).toMatchObject({ kind: 'conflict', status: null, code: 'user_self_modification_forbidden' });
        expect(classifyAppError(new AppGuardError('self_remove_tenant_admin')).code).toBe('user_self_modification_forbidden');
        expect(classifyAppError(new AppGuardError('empty_changes')).kind).toBe('invalid_input');
    });

    it('ApiError 以外は unknown', () => {
        expect(classifyAppError(new TypeError('network'))).toMatchObject({ kind: 'unknown', status: null });
    });
});

describe('appPermissionsOf / ifMatchOf', () => {
    it('tenant_admin のみ変更系を使える', () => {
        expect(appPermissionsOf(['tenant_admin', 'member'])).toEqual({ is_tenant_admin: true, can_write: true });
        expect(appPermissionsOf(['member'])).toEqual({ is_tenant_admin: false, can_write: false });
        expect(appPermissionsOf([])).toEqual({ is_tenant_admin: false, can_write: false });
    });

    it('version から If-Match の値を作る', () => {
        expect(ifMatchOf(7)).toBe('"7"');
    });
});
