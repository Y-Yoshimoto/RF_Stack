/**
 * @description:
 * CP のテナントの変更操作 (作成・停止・再開・削除要求・払い出しの再実行) のカスタムフック
 *
 * - saas_viewer など変更権限の無いユーザーでは API を呼ばずに失敗 (kind: forbidden) にする (useCpPermissions)
 * - 停止・再開・削除要求は保持している ETag を If-Match に付ける。412 は requires_reload のエラーになる
 * - 一時パスワードは issued_credentials にだけ保持し、dismissCredentials・次の操作の開始・一定時間の経過・アンマウントで消す。
 *   操作の戻り値・onUpdated・エラーには含めない。ログにも出さない
 * - 操作は reject しない。結果 (ok / failure) を返し、最後の失敗を failure に保持する
*/
import { useCallback, useEffect, useRef, useState } from 'react';
import { useCpApiClient } from '@/control_plane_app/api/client';
import type { InitialAdminCredentials, InitialAdminInput, TenantCreate, TenantProvisioned } from '@/control_plane_app/api/contract';
import { classifyCpError, CpGuardError, type CpErrorInfo } from '@/control_plane_app/api/errors';
import {
    createTenant,
    requestTenantDeletion,
    resumeTenant,
    retryTenantProvisioning,
    suspendTenant,
    type TenantTarget,
    type TenantVersioned,
    type WithEtag,
} from '@/control_plane_app/api/tenants';
import { useCpPermissions } from '@/control_plane_app/auth/useCpAuth';

/** 一時パスワードを保持する既定の時間 (ミリ秒)。画面は表示を閉じたら dismissCredentials を呼ぶこと */
export const DEFAULT_CREDENTIALS_TTL_MS = 10 * 60 * 1000;

/**
 * 変更操作の種類。
 */
export type TenantActionName = 'create' | 'suspend' | 'resume' | 'request_deletion' | 'retry';

/**
 * 変更操作の失敗。
 */
export type TenantActionFailure = CpErrorInfo & {
    action: TenantActionName;
    tenant_id: string | null;
};

/**
 * 変更操作の結果。成功時は更新後のテナントと新しい ETag (一時パスワードは含まない)。
 */
export type TenantActionResult =
    | ({ ok: true; action: TenantActionName } & TenantVersioned)
    | { ok: false; failure: TenantActionFailure };

/**
 * 払い出し (作成・再実行) で発行された初期管理者の認証情報。一度だけ表示する。
 */
export type IssuedCredentials = InitialAdminCredentials & {
    tenant_id: string;
    tenant_code: string;
};

export type UseTenantActionsOptions = {
    /** 成功時に呼ばれる (useTenant の applyUpdate や一覧の reload につなぐ)。一時パスワードは渡さない。 */
    onUpdated?: (update: TenantVersioned & { action: TenantActionName }) => void;
    /** 一時パスワードを保持する時間 (ミリ秒)。 */
    credentials_ttl_ms?: number;
};

/**
 * 変更操作の状態と操作。
 */
export type TenantActionsState = {
    /** 変更操作を使える (saas_admin)。false のとき画面は変更操作の UI を表示しない。 */
    can_write: boolean;
    /** 実行中の操作 (無ければ null)。 */
    pending: TenantActionName | null;
    /** 最後の失敗 (次の操作の開始・clearFailure で消える)。 */
    failure: TenantActionFailure | null;
    /** 発行された一時パスワード (無ければ null)。 */
    issued_credentials: IssuedCredentials | null;
    /** 一時パスワードを破棄する (表示を閉じたときに呼ぶ)。 */
    dismissCredentials: () => void;
    clearFailure: () => void;
    /** テナントを作成する (201 で一時パスワードが issued_credentials に入る)。 */
    create: (input: TenantCreate) => Promise<TenantActionResult>;
    /** 停止する (target.etag を If-Match に付ける)。 */
    suspend: (target: TenantTarget) => Promise<TenantActionResult>;
    /** 再開する (target.etag を If-Match に付ける)。 */
    resume: (target: TenantTarget) => Promise<TenantActionResult>;
    /** 削除を要求する (target.etag を If-Match に付ける)。 */
    requestDeletion: (target: TenantTarget) => Promise<TenantActionResult>;
    /** 払い出しを再実行する (target.etag は任意。新しい一時パスワードが issued_credentials に入る)。 */
    retry: (target: TenantTarget, initial_admin: InitialAdminInput) => Promise<TenantActionResult>;
};

/** 実行する処理 (API 呼び出し) と、その結果の扱い */
type ActionPlan = {
    action: TenantActionName;
    tenant_id: string | null;
    /** If-Match が必須の操作で、ETag が無い場合は API を呼ばない。 */
    required_etag?: string | null;
    run: () => Promise<TenantVersioned & { credentials?: IssuedCredentials }>;
};

/**
 * 払い出しの結果を、テナントと一時パスワードに分ける関数
 * @param {WithEtag<TenantProvisioned>} result 払い出しの結果
 * @returns {TenantVersioned & { credentials: IssuedCredentials }} テナント・ETag と一時パスワード
*/
const splitProvisioned = ({ body, etag }: WithEtag<TenantProvisioned>): TenantVersioned & { credentials: IssuedCredentials } => ({
    tenant: body.tenant,
    etag,
    credentials: { ...body.initial_admin, tenant_id: body.tenant.id, tenant_code: body.tenant.tenant_code },
});

/**
 * CP のテナントの変更操作のカスタムフック (ControlPlaneAuthProvider の内側で使う)
 * @param {UseTenantActionsOptions} options 成功時の通知・一時パスワードの保持時間
 * @returns {TenantActionsState} 状態と操作
*/
export const useTenantActions = ({ onUpdated, credentials_ttl_ms = DEFAULT_CREDENTIALS_TTL_MS }: UseTenantActionsOptions = {}): TenantActionsState => {
    const client = useCpApiClient();
    const { can_write } = useCpPermissions();
    const [pending, setPending] = useState<TenantActionName | null>(null);
    const [failure, setFailure] = useState<TenantActionFailure | null>(null);
    const [issued_credentials, setIssuedCredentials] = useState<IssuedCredentials | null>(null);
    // 二重実行を防ぐ (イベントハンドラーからのみ読み書きする)
    const is_running = useRef(false);

    // 一時パスワードは一定時間で破棄する
    useEffect(() => {
        if (issued_credentials === null) return;
        const timer = setTimeout(() => setIssuedCredentials(null), credentials_ttl_ms);
        return () => clearTimeout(timer);
    }, [issued_credentials, credentials_ttl_ms]);

    const execute = useCallback(async (plan: ActionPlan): Promise<TenantActionResult> => {
        const fail = (error: unknown): TenantActionResult => {
            const info: TenantActionFailure = { ...classifyCpError(error), action: plan.action, tenant_id: plan.tenant_id };
            setFailure(info);
            return { ok: false, failure: info };
        };
        if (is_running.current) return fail(new CpGuardError('action_in_progress'));
        setFailure(null);
        setIssuedCredentials(null);
        if (!can_write) return fail(new CpGuardError('write_not_allowed'));
        if (plan.required_etag !== undefined && !plan.required_etag) return fail(new CpGuardError('missing_etag'));
        is_running.current = true;
        setPending(plan.action);
        try {
            const { credentials, tenant, etag } = await plan.run();
            if (credentials) setIssuedCredentials(credentials);
            onUpdated?.({ action: plan.action, tenant, etag });
            return { ok: true, action: plan.action, tenant, etag };
        } catch (error) {
            return fail(error);
        } finally {
            is_running.current = false;
            setPending(null);
        }
    }, [client, can_write, onUpdated]);

    const create = useCallback((input: TenantCreate) => execute({
        action: 'create',
        tenant_id: null,
        run: async () => splitProvisioned(await createTenant(client, input)),
    }), [execute, client]);

    const suspend = useCallback((target: TenantTarget) => execute({
        action: 'suspend',
        tenant_id: target.tenant_id,
        required_etag: target.etag,
        run: () => suspendTenant(client, target.tenant_id, target.etag ?? ''),
    }), [execute, client]);

    const resume = useCallback((target: TenantTarget) => execute({
        action: 'resume',
        tenant_id: target.tenant_id,
        required_etag: target.etag,
        run: () => resumeTenant(client, target.tenant_id, target.etag ?? ''),
    }), [execute, client]);

    const requestDeletion = useCallback((target: TenantTarget) => execute({
        action: 'request_deletion',
        tenant_id: target.tenant_id,
        required_etag: target.etag,
        run: () => requestTenantDeletion(client, target.tenant_id, target.etag ?? ''),
    }), [execute, client]);

    const retry = useCallback((target: TenantTarget, initial_admin: InitialAdminInput) => execute({
        action: 'retry',
        tenant_id: target.tenant_id,
        run: async () => splitProvisioned(await retryTenantProvisioning(client, target.tenant_id, initial_admin, target.etag)),
    }), [execute, client]);

    const dismissCredentials = useCallback(() => setIssuedCredentials(null), []);
    const clearFailure = useCallback(() => setFailure(null), []);

    return { can_write, pending, failure, issued_credentials, dismissCredentials, clearFailure, create, suspend, resume, requestDeletion, retry };
};

export default useTenantActions;
