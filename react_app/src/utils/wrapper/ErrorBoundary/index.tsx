

/**
 * @fileoverview
 * このファイルは、`react-error-boundary` ライブラリを利用したエラーバウンダリーコンポーネントのラッパーを提供する
 * アプリケーション内で発生したJavaScriptエラーをキャッチし、指定されたフォールバックUIを表示する
 * 開発途中で、デフォルトのエラー表示使用できるようにすることと、共通のエラー出力のためラッピングして使用する
 * また、React Router v7の`ErrorBoundary`用のコンポーネントも提供する
 * エクスポート:
 * - `W_ErrorBoundary`: 子コンポーネントのエラーをキャッチし、フォールバックUIを表示するラッパーコンポーネント
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
    isSendError?: boolean; // エラー情報をonError内で外部サービスに送信化の有無
    onError?: (error: Error, info: ErrorInfo, isSendError: boolean) => void; // エラー発生時のコールバック関数
    onReset?: () => void; // フォールバックUIのリセット時のコールバック関数
    errorFallback?: React.ComponentType<FallbackProps>; // エラー発生時に表示するカスタムフォールバックコンポーネント
    error?: Error;
};

// デフォルトのエラーフォールバックコンポーネント
export const ErrorFallback_default = ({ error, resetErrorBoundary }: FallbackProps): React.ReactNode => {
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
export const onError_default = (error: Error, info: ErrorInfo, isSendError = false) => {
    console.debug('ErrorBoundary onError called');
    console.error('error.message', error?.message);
    console.error('error.stack', error?.stack);
    if (info?.componentStack) {
        console.error('info.componentStack:', info.componentStack);
    }
    if (isSendError) {
        // Todo: エラーをエラーレポートサービスに送信する
        console.debug('Todo: Send error to error reporting service');
    }
};
// デフォルトの onReset ハンドラ
// ページをリロードする
export const onReset_default = (action = () => { window.location.reload() }) => {
    console.debug('ErrorBoundary onReset location reload');
    try {
        action();
    } catch (e) {
        console.warn('OnReset error', e);
    }
};

export const W_ErrorBoundary = ({
    children,
    isSendError = false,
    onError = onError_default,
    onReset = onReset_default,
    errorFallback = ErrorFallback_default
}: ErrorBoundaryProps) => {
    return (
        <ErrorBoundary
            FallbackComponent={errorFallback}
            onError={(error, info) => onError(error, info, isSendError)}
            onReset={onReset}
        >
            {children}
        </ErrorBoundary>
    );
};
export const W_ErrorBoundary_Router = ({ error }: { error: Error }) => {
    onError_default(error, { componentStack: '' }, false);
    return (
        <ErrorFallback_default error={error} resetErrorBoundary={onReset_default} />
    );
}

export default W_ErrorBoundary;