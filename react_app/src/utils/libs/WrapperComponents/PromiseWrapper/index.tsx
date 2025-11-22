// プロミスオブジェクトを扱うラッパーコンポーネント
// use API及びSuspense, ErrorBoundaryを使用してFetch処理などをラッピングする

// 読み込み表示用のSuspense
import { W_Suspense, SuspenseProps } from '../Suspense';
// 全体のエラーバウンダリー
import { W_ErrorBoundary, ErrorBoundaryProps } from '../ErrorBoundary';
// プロミスオブジェクトを扱うラッパーコンポーネント Props
type PromiseWrapperProps = SuspenseProps & ErrorBoundaryProps;

/**
 * PromiseWrapper 非同期処理のためのエラーバウンダリとサスペンスをラップしたコンポーネント
 *
 * @param {PromiseWrapperProps} props - コンポーネントのプロパティ
 * @param {React.ReactNode} props.children - ラップする子要素
 * @param {React.ReactNode} props.errorFallback - エラー発生時に表示するフォールバックUI
 * @param {React.ReactNode} props.loadingFallback - ローディング中に表示するフォールバックUI
 * @param {(error: Error) => void} [props.onError] - エラー発生時に呼び出されるコールバック
 * @param {() => void} [props.onReset] - エラーリセット時に呼び出されるコールバック
 *
 * @returns {JSX.Element} エラーバウンダリとサスペンスでラップされた子要素
 */
export const PromiseWrapper = ({ children, errorFallback, loadingFallback, onError, onReset }: PromiseWrapperProps) => {
    return (
        <W_ErrorBoundary
            onError={onError}
            onReset={onReset}
            errorFallback={errorFallback}
        >
            <W_Suspense loadingFallback={loadingFallback}>
                {children}
            </W_Suspense>
        </W_ErrorBoundary>
    );
};

export default PromiseWrapper;