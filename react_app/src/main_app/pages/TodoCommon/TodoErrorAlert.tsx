/**
 * @desc ToDo の API エラーの通知 (role="alert" で読み上げられる)
 * ToDo 固有のエラー (権限不足・見つからない・担当者や公開先の不正) は専用の文言にし、それ以外は AP 共通の文言 (appErrorTextOf) を使う。
 * requires_reload (412 / 428 / 403 todo_operation_forbidden) では「再読み込み」を出し、表示が古いことを案内する。
 */
import { Alert, AlertTitle, Box, Button, Typography } from '@mui/material';
import { APP_PROBLEM_CODE, type TodoOperation } from '@/main_app/api/contract';
import type { AppErrorInfo } from '@/main_app/api/errors';
import { appErrorTextOf, fieldErrorMessagesOf, type AppErrorText } from '@/main_app/components/error_text';

const OPERATION_LABELS: Readonly<Record<TodoOperation, string>> = {
    edit_fields: 'タイトル・説明・期限・優先度の編集',
    change_status: 'ステータスの変更',
    change_visibility: '閲覧範囲の変更',
    change_assignees: '担当者の変更',
    delete: '削除',
};

/**
 * ToDo のエラーを利用者向けの文言にする関数
 * @param {AppErrorInfo} info 分類済みのエラー
 * @returns {AppErrorText} 文言
*/
export const todoErrorTextOf = (info: AppErrorInfo): AppErrorText => {
    switch (info.code) {
        case APP_PROBLEM_CODE.TODO_OPERATION_FORBIDDEN: {
            const operation = info.problem?.operation;
            const label = typeof operation === 'string' && Object.hasOwn(OPERATION_LABELS, operation) ? OPERATION_LABELS[operation as TodoOperation] : null;
            return {
                title: label ? `${label}はできません` : 'この操作を行う権限がありません',
                message: info.requires_reload ? '権限が変わった可能性があります。再読み込みして、最新の権限を確認してください。' : 'この操作は作成者・担当者・テナント管理者の権限に応じて制限されています。',
                details: [],
            };
        }
        case APP_PROBLEM_CODE.TODO_NOT_FOUND:
            return { title: 'ToDo が見つかりません', message: '削除されたか、閲覧できない ToDo です。一覧から選び直してください。', details: [] };
        case APP_PROBLEM_CODE.INVALID_TODO_ASSIGNEES:
            return { title: '担当者に指定できないユーザーが含まれています', message: '無効化されたユーザーは新たに割り当てられません。選び直してください。', details: fieldErrorMessagesOf(info) };
        case APP_PROBLEM_CODE.INVALID_TODO_ORGANIZATIONS:
            return { title: '公開先に指定できない組織が含まれています', message: '組織が削除された可能性があります。再読み込みして、選び直してください。', details: [] };
        default:
            return appErrorTextOf(info);
    }
};

export type TodoErrorAlertProps = {
    error: AppErrorInfo;
    /** data-testid。 */
    test_id: string;
    /** 再読み込み (または再試行) の操作。 */
    onReload?: () => void;
    /** requires_reload でなくても再試行を出す (取得の失敗など)。 */
    always_retry?: boolean;
};

export const TodoErrorAlert = ({ error, test_id, onReload, always_retry = false }: TodoErrorAlertProps) => {
    const text = todoErrorTextOf(error);
    const show_reload = onReload !== undefined && (error.requires_reload || always_retry);
    const request_id = error.problem?.request_id;
    return (
        <Alert
            severity="error"
            role="alert"
            data-testid={test_id}
            data-error-kind={error.kind}
            data-error-code={error.code ?? ''}
            action={show_reload ? <Button color="inherit" size="small" onClick={onReload} data-testid={`${test_id}-reload`}>{error.requires_reload ? '再読み込み' : '再試行'}</Button> : undefined}
        >
            <AlertTitle>{text.title}</AlertTitle>
            {text.message}
            {text.details.length > 0 && (
                <Box component="ul" sx={{ mt: 0.5, mb: 0, pl: 2.5 }} data-testid={`${test_id}-details`}>
                    {text.details.map((line) => <li key={line}>{line}</li>)}
                </Box>
            )}
            {request_id && <Typography variant="caption" component="p" sx={{ mt: 0.5 }}>リクエスト ID: {request_id}</Typography>}
        </Alert>
    );
};

export default TodoErrorAlert;
