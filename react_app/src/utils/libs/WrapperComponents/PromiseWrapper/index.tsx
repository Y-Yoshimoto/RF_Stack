// プロミスオブジェクトを扱うラッパーコンポーネント
// use API及びSuspense, ErrorBoundaryを使用してFetch処理などをラッピングする

// 読み込み表示用のSuspense
import { WSuspense, SuspenseProps } from '../Suspense';
// 全体のエラーバウンダリー
import { WErrorBoundary, ErrorBoundaryProps } from '../ErrorBoundary';
// プロミスオブジェクトを扱うラッパーコンポーネント Props
type PromiseWrapperProps = SuspenseProps & ErrorBoundaryProps;

/**
 * PromiseWrapper 非同期処理のためのエラーバウンダリとサスペンスをラップしたコンポーネント
 *
 * @param {PromiseWrapperProps} props - コンポーネントのプロパティ
 * @param {React.ReactNode} props.children - ラップする子要素
 * @param {React.ReactNode} props.error_fallback - エラー発生時に表示するフォールバックUI
 * @param {React.ReactNode} props.loading_fallback - ローディング中に表示するフォールバックUI
 * @param {(error: Error) => void} [props.onError] - エラー発生時に呼び出されるコールバック
 * @param {() => void} [props.onReset] - エラーリセット時に呼び出されるコールバック
 *
 * @returns {JSX.Element} エラーバウンダリとサスペンスでラップされた子要素
 */
export const PromiseWrapper = ({ children, error_fallback, loading_fallback, onError, onReset }: PromiseWrapperProps) => {
    return (
        <WErrorBoundary
            onError={onError}
            onReset={onReset}
            error_fallback={error_fallback}
        >
            <WSuspense loading_fallback={loading_fallback}>
                {children}
            </WSuspense>
        </WErrorBoundary>
    );
};

export default PromiseWrapper;