// CP の API エラー (CpErrorInfo) を、利用者向けの文言にする関数
import { CP_PROBLEM_CODE } from '@/control_plane_app/api/contract';
import type { CpErrorInfo } from '@/control_plane_app/api/errors';
import { formatDateTime, tenantStatusLabelOf } from './tenant_labels';

/**
 * 画面に出すエラーの文言。
 */
export type CpErrorText = {
    /** 見出し (1 行)。 */
    title: string;
    /** 補足。原因・次にとる行動。 */
    message: string;
    /** 箇条書きの詳細 (現在の状態・猶予期間の終了日時・項目ごとの入力エラーなど)。 */
    details: string[];
};

/** 状態遷移の操作名 (invalid_tenant_transition の operation) の表示名 */
const OPERATION_LABEL: Record<string, string> = {
    suspend: '停止',
    resume: '再開',
    request_deletion: '削除要求',
    delete: '削除要求',
    retry: '払い出しの再実行',
    retry_provisioning: '払い出しの再実行',
};

/**
 * 拡張メンバー (文字列) を取り出す関数
 * @param {CpErrorInfo} info エラー
 * @param {string} key メンバー名
 * @returns {string | null} 値 (文字列でなければ null)
*/
export const problemStringOf = (info: CpErrorInfo, key: string): string | null => {
    const value = info.problem?.[key];
    return typeof value === 'string' && value !== '' ? value : null;
};

/**
 * 409 (conflict) の文言を作る関数
 * @param {CpErrorInfo} info エラー
 * @returns {CpErrorText} 文言
*/
const conflictTextOf = (info: CpErrorInfo): CpErrorText => {
    const details: string[] = [];
    const current_status = problemStringOf(info, 'current_status');
    if (current_status) details.push(`現在の状態: ${tenantStatusLabelOf(current_status)}`);
    switch (info.code) {
        case CP_PROBLEM_CODE.TENANT_CODE_ALREADY_EXISTS:
            return { title: 'テナントコードが既に使われています', message: '別のテナントコードを指定してください。削除済みのテナントのコードも再利用できません。', details };
        case CP_PROBLEM_CODE.INVALID_TENANT_TRANSITION: {
            const operation = problemStringOf(info, 'operation');
            const operation_label = operation ? (OPERATION_LABEL[operation] ?? operation) : null;
            return { title: operation_label ? `現在の状態では「${operation_label}」を実行できません` : '現在の状態では実行できない操作です', message: '表示が古い可能性があります。最新の状態を読み込んでから、やり直してください。', details };
        }
        case CP_PROBLEM_CODE.DELETION_GRACE_PERIOD_NOT_ELAPSED: {
            const deletable_at = problemStringOf(info, 'deletable_at');
            if (deletable_at) details.push(`削除できるようになる日時: ${formatDateTime(deletable_at)}`);
            return { title: '削除の猶予期間が経過していません', message: '猶予期間の経過後に、定期ジョブが物理削除します。', details };
        }
        case CP_PROBLEM_CODE.TENANT_OPERATION_IN_PROGRESS:
            return { title: 'このテナントに対する別の操作を実行中です', message: 'しばらくしてから、最新の状態を確認してやり直してください。', details };
        default:
            return { title: '操作が競合しました', message: info.problem?.detail ?? '最新の状態を読み込んでから、やり直してください。', details };
    }
};

/**
 * 入力検証エラー (422) の項目ごとの詳細を文言にする関数
 * @param {CpErrorInfo} info エラー
 * @returns {string[]} 項目ごとのメッセージ
*/
export const fieldErrorMessagesOf = (info: CpErrorInfo): string[] => (info.problem?.errors ?? []).map((item) => `${item.field}: ${item.message}`);

/**
 * CP の API エラーを利用者向けの文言にする関数
 * @param {CpErrorInfo} info 分類済みのエラー
 * @returns {CpErrorText} 文言
*/
export const cpErrorTextOf = (info: CpErrorInfo): CpErrorText => {
    switch (info.kind) {
        case 'unauthenticated':
            return { title: 'ログインの有効期限が切れました', message: '再度ログインしてください。', details: [] };
        case 'forbidden':
            return { title: 'この操作を行う権限がありません', message: '変更操作には SaaS 管理者の権限が必要です。', details: [] };
        case 'not_found':
            return { title: '対象が見つかりません', message: '削除されたか、指定が誤っている可能性があります。', details: [] };
        case 'version_conflict':
        case 'precondition_required':
            return { title: '他の操作で更新されています', message: '表示している内容が古くなっています。再読み込みして最新の状態を確認してから、やり直してください。', details: [] };
        case 'conflict':
            return conflictTextOf(info);
        case 'invalid_input':
            return { title: '入力内容を確認してください', message: info.problem?.detail ?? '入力された値が受け付けられませんでした。', details: fieldErrorMessagesOf(info) };
        case 'external_failure': {
            const step = problemStringOf(info, 'step');
            return { title: '外部システムの操作に失敗しました', message: '認証基盤との連携で失敗しました。時間をおいて、やり直してください。', details: step ? [`失敗したステップ: ${step}`] : [] };
        }
        case 'unavailable':
            return { title: 'サービスが一時的に利用できません', message: 'しばらくしてから、やり直してください。', details: [] };
        case 'busy':
            return { title: '別の操作を実行中です', message: '完了してから、やり直してください。', details: [] };
        default:
            return { title: '予期しないエラーが発生しました', message: 'しばらくしてから、やり直してください。解消しない場合は管理者に連絡してください。', details: [] };
    }
};
