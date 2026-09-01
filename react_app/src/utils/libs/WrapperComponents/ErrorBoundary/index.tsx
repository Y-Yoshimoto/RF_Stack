

/**
 * @fileoverview
 * このファイルは、`react-error-boundary` ライブラリを利用したエラーバウンダリーコンポーネントのラッパーを提供する
 * アプリケーション内で発生したJavaScriptエラーをキャッチし、指定されたフォールバックUIを表示する
 * 開発途中で、デフォルトのエラー表示使用できるようにすることと、共通のエラー出力のためラッピングして使用する
 * また、React Router v7の`ErrorBoundary`用のコンポーネントも提供する
 * エクスポート:
 * - `WErrorBoundary`: 子コンポーネントのエラーをキャッチし、フォールバックUIを表示するラッパーコンポーネント
 * 
 * 参考:
 * - [react-error-boundary ドキュメント](https://github.com/bvaughn/react-error-boundary)
 */
import type { ErrorInfo } from "react";
import { ErrorBoundary, FallbackProps } from "react-error-boundary";
/**
 * ErrorBoundary コンポーネント
 *
 * @remarks
 * ErrorBoundary コンポーネントに渡すことができるプロパティ型
 *
 * @property children - ErrorBoundary がラップする子の React ノード。
 * @property fallback - エラー発生時に表示するカスタムフォールバックコンポーネント（省略可能）。
 * @property error: 例外を受け取る
 */
export type ErrorBoundaryProps = {
    children: React.ReactNode; // ErrorBoundaryがラップする子コンポーネント
    is_send_error?: boolean; // エラー情報をonError内で外部サービスに送信化の有無
    onError?: (error: Error, info: ErrorInfo, is_send_error: boolean) => void; // エラー発生時のコールバック関数
    onReset?: () => void; // フォールバックUIのリセット時のコールバック関数
    error_fallback?: React.ComponentType<FallbackProps>; // エラー発生時に表示するカスタムフォールバックコンポーネント
    error?: Error;
};

// デフォルトのエラーフォールバックコンポーネント
export const ErrorFallbackDefault = ({ error, resetErrorBoundary }: FallbackProps): React.ReactNode => {
    console.debug("ErrorBoundary caught an error");
    return (
        <div role="alert">
            <p>Something error:</p>
            <pre>error.message: {error?.message}</pre>
            <pre>error.stack: {error?.stack}</pre>
            <button type="button" onClick={() => resetErrorBoundary()}>
                再読み込み
            </button>
        </div>
    );
};

// エラーログを出力するデフォルトの onError ハンドラ
export const onErrorDefault = (error: Error, info: ErrorInfo, is_send_error = false) => {
    console.debug('ErrorBoundary onError called');
    console.error('error.message', error?.message);
    console.error('error.stack', error?.stack);
    if (info?.componentStack) {
        console.error('info.componentStack:', info.componentStack);
    }
    if (is_send_error) {
        // Todo: エラーをエラーレポートサービスに送信する
        console.debug('Todo: Send error to error reporting service');
    }
};
// デフォルトの onReset ハンドラ
// ページをリロードする
export const onResetDefault = (action = () => { window.location.reload() }) => {
    console.debug('ErrorBoundary onReset location reload');
    try {
        action();
    } catch (e) {
        console.warn('OnReset error', e);
    }
};

export const WErrorBoundary = ({
    children,
    is_send_error = false,
    onError = onErrorDefault,
    onReset = onResetDefault,
    error_fallback = ErrorFallbackDefault
}: ErrorBoundaryProps) => {
    return (
        <ErrorBoundary
            FallbackComponent={error_fallback}
            onError={(error, info) => onError(error, info, is_send_error)}
            onReset={onReset}
        >
            {children}
        </ErrorBoundary>
    );
};
export const WErrorBoundaryRouter = ({ error }: { error: Error }) => {
    onErrorDefault(error, { componentStack: '' }, false);
    return (
        <ErrorFallbackDefault error={error} resetErrorBoundary={onResetDefault} />
    );
}

export default WErrorBoundary;