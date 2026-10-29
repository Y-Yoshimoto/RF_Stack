// AP の API エラーの文言のテスト
import { describe, expect, it } from 'vitest';
import type { AppErrorInfo } from '@/main_app/api/errors';
import { appErrorTextOf } from './error_text';

const infoOf = (overrides: Partial<AppErrorInfo>): AppErrorInfo => ({ kind: 'unknown', status: null, code: null, problem: null, requires_reload: false, error: null, ...overrides });

describe('appErrorTextOf', () => {
    it('メールアドレスの重複 (409) を案内する', () => {
        expect(appErrorTextOf(infoOf({ kind: 'conflict', code: 'user_already_exists' })).title).toContain('メールアドレス');
    });

    it('自分自身への禁止操作 (409) は、操作の種類を文言に含める', () => {
        const problem = { type: '', title: '', status: 409, detail: '', instance: '', code: 'user_self_modification_forbidden', operation: 'deactivate' };
        expect(appErrorTextOf(infoOf({ kind: 'conflict', code: 'user_self_modification_forbidden', problem })).title).toContain('自分自身を無効化');
    });

    it('412 / 428 は再読み込みを促す', () => {
        expect(appErrorTextOf(infoOf({ kind: 'version_conflict' })).message).toContain('再読み込み');
        expect(appErrorTextOf(infoOf({ kind: 'precondition_required' })).message).toContain('再読み込み');
    });

    it('422 は項目ごとのエラーを details に含める', () => {
        const problem = { type: '', title: '', status: 422, detail: '入力エラー', instance: '', code: 'invalid_user_input', errors: [{ field: 'email', code: 'invalid', message: '形式が不正です' }] };
        expect(appErrorTextOf(infoOf({ kind: 'invalid_input', code: 'invalid_user_input', problem })).details).toEqual(['email: 形式が不正です']);
    });

    it('502 は変更が反映されていないことを伝える', () => {
        expect(appErrorTextOf(infoOf({ kind: 'external_failure' })).message).toContain('反映されていません');
    });

    it('404 はユーザーと組織で文言を分ける', () => {
        expect(appErrorTextOf(infoOf({ kind: 'not_found', code: 'user_not_found' })).title).toContain('ユーザー');
        expect(appErrorTextOf(infoOf({ kind: 'not_found', code: 'organization_not_found' })).title).toContain('組織');
    });
});
