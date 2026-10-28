/**
 * @desc ルート全体のエラーバウンダリー (React Router の ErrorBoundary)
 * ルートガードは 401 以外の認証状態の取得失敗などを握り潰さずに送出する。ここで受けて表示する。
 */
import { useRouteError } from 'react-router-dom';
import { WErrorBoundaryRouter } from '@/utils/libs/WrapperComponents/ErrorBoundary';

/**
 * 例外を Error に揃える関数
 * @param {unknown} value 送出された値
 * @returns {Error} Error
*/
export const toError = (value: unknown): Error => {
    if (value instanceof Error) return value;
    return new Error(typeof value === 'string' ? value : 'Unexpected error');
};

export const RouteErrorBoundary = () => {
    const route_error = useRouteError();
    return <WErrorBoundaryRouter error={toError(route_error)} />;
};

export default RouteErrorBoundary;
