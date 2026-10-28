// コントロールプレーン (CP) の API クライアント
// 02 §6.2: 401 を受けたらログイン画面へ (CP の認証状態を再取得し、ルートガードが /cp/login へ遷移させる)。
// 403 (saas_viewer の変更操作など) は操作単位のエラーとして呼び出し元で扱う。
import { useMemo } from 'react';
import { createApiClient, type ApiClient } from '@/shared/api/client';
import { useCpAuth } from '@/control_plane_app/auth/useCpAuth';

/**
 * CP の API クライアントを返すカスタムフック (ControlPlaneAuthProvider の内側で使う)
 * @returns {ApiClient} API クライアント
*/
export const useCpApiClient = (): ApiClient => {
    const { reportApiError } = useCpAuth();
    return useMemo(() => createApiClient(reportApiError), [reportApiError]);
};
