// CP の API エラーの文言のテスト (409 の現在の状態・削除可能日時、412 の再読み込み、502 のステップ)
import { describe, expect, it } from 'vitest';
import { classifyCpError } from '@/control_plane_app/api/errors';
import { ApiError } from '@/utils/libs/FetchComponents/problem';
import { cpErrorTextOf } from './error_text';

/**
 * Problem Details を持つ ApiError から分類済みのエラーを作る関数
 * @param {number} status ステータス
 * @param {string} code エラーコード
 * @param {Record<string, unknown>} extra 拡張メンバー
 * @returns {ReturnType<typeof classifyCpError>} 分類
*/
const infoOf = (status: number, code: string, extra: Record<string, unknown> = {}) => {
    const problem = { type: `about:blank#${code}`, title: code, status, detail: code, instance: '/', code, errors: [], ...extra };
    return classifyCpError(new ApiError(status, 'x', problem));
};

describe('cpErrorTextOf', () => {
    it('409 invalid_tenant_transition は、操作名と現在の状態を出す', () => {
        const text = cpErrorTextOf(infoOf(409, 'invalid_tenant_transition', { operation: 'suspend', current_status: 'PENDING_DELETION' }));
        expect(text.title).toContain('停止');
        expect(text.details).toEqual(['現在の状態: 削除待ち']);
    });

    it('409 deletion_grace_period_not_elapsed は、削除できる日時を出す', () => {
        const text = cpErrorTextOf(infoOf(409, 'deletion_grace_period_not_elapsed', { current_status: 'PENDING_DELETION', deletable_at: '2026-11-27T00:00:00Z' }));
        expect(text.details.join('\n')).toMatch(/削除できるようになる日時: 2026\/11\/27/);
    });

    it('412 は再読み込みを促す', () => {
        const info = infoOf(412, 'tenant_version_conflict');
        expect(info.requires_reload).toBe(true);
        expect(cpErrorTextOf(info).message).toContain('再読み込み');
    });

    it('502 は、失敗したステップを出す', () => {
        expect(cpErrorTextOf(infoOf(502, 'tenant_provisioning_failed', { tenant_id: 't1', step: 'create_realm' })).details).toEqual(['失敗したステップ: create_realm']);
    });

    it('422 は、項目ごとのエラーを出す', () => {
        const info = infoOf(422, 'validation_error', { errors: [{ field: 'initial_admin.email', code: 'value_error', message: '形式が不正です' }] });
        expect(cpErrorTextOf(info).details).toEqual(['initial_admin.email: 形式が不正です']);
    });
});
