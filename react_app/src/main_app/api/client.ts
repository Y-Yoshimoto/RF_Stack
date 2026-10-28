// アプリケーションプレーン (AP) の API クライアント
// 02 §6.2: 401 を受けたらログイン画面へ、403 (テナント停止中・利用不可) はエラー画面へ。
// 遷移は AP の認証状態 (AppAuthProvider) に反映し、ルートガードが画面を出し分ける。
import { useMemo } from 'react';
import { createApiClient, type ApiClient } from '@/shared/api/client';
import { useAppAuth } from '@/main_app/auth/useAppAuth';

/**
 * AP の API クライアントを返すカスタムフック (AppAuthProvider の内側で使う)
 * @returns {ApiClient} API クライアント
*/
export const useAppApiClient = (): ApiClient => {
    const { reportApiError } = useAppAuth();
    return useMemo(() => createApiClient(reportApiError), [reportApiError]);
};
