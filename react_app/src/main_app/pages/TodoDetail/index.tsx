/**
 * @desc ToDo の詳細・編集 (`/{tenant_code}/todos/:todoId`。tenant_admin / member のどちらも可)
 * 項目の編集 (permissions に応じて項目単位で可否を出し分け)、ステータスの変更、閲覧範囲・公開先組織の変更、担当者の置き換え、削除 (確認ダイアログ)、
 * アクティビティの時系列表示。閲覧できない ToDo は存在を明かさない 404 としてエラー表示する。
 * 使うフック: useTodo (詳細・ETag・permissions)、useTodoActions / useTodoActivities / 選択肢のフック (TodoDetailContent)。
 */
import { useParams } from 'react-router-dom';
import { Stack } from '@mui/material';
import { useAppSession } from '@/main_app/auth/useAppAuth';
import { PageHeader } from '@/main_app/components/PageHeader';
import { TodoStatusChip } from '@/main_app/pages/TodoCommon/TodoBadges';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { appTodosPath } from '@/main_app/paths';
import { useTodo } from '@/main_app/todos/useTodo';
import { PageLoading } from '@/shared/components/PageLoading';
import { TodoDetailContent } from './TodoDetailContent';

export const AppTodoDetailPage = () => {
    const { todoId = '' } = useParams();
    const { tenant_code } = useAppSession();
    const detail = useTodo(todoId);
    const { todo, target } = detail;

    return (
        <Stack spacing={3} data-testid="app-todo-detail-page">
            <PageHeader
                test_id="todo-detail"
                title={todo?.title ?? 'ToDo の詳細'}
                description={todo ? <TodoStatusChip status={todo.status} test_id="todo-detail-status-chip" /> : undefined}
                back={{ to: appTodosPath(tenant_code), label: 'ToDo 一覧へ戻る' }}
            />

            {detail.status === 'loading' && <PageLoading />}
            {detail.status === 'error' && detail.error && <TodoErrorAlert error={detail.error} test_id="todo-detail-error" onReload={detail.reload} always_retry />}
            {detail.status === 'success' && todo !== null && target !== null && (
                <TodoDetailContent todo={todo} target={target} needs_organization_reselect={detail.needs_organization_reselect} onUpdated={detail.applyUpdate} onReload={detail.reload} />
            )}
        </Stack>
    );
};

export default AppTodoDetailPage;
