/**
 * @desc ToDo の詳細・編集 (`/{tenant_code}/todos/:todoId`。tenant_admin / member のどちらも可)
 * 項目の編集 (permissions に応じて項目単位で可否を出し分け)、ステータスの変更、閲覧範囲・公開先組織の変更、担当者の置き換え、削除 (確認ダイアログ)、
 * チェックリスト (並べ替え・進捗)、コメントとアクティビティのタブ。閲覧できない ToDo は存在を明かさない 404 としてエラー表示する。
 * 並び: 見出し → 作成者・更新者 → ステータス → 項目 → チェックリスト → 担当者 → 閲覧範囲 → コメント / アクティビティ。
 * 使うフック: useTodo (詳細・ETag・permissions・refresh)、useTodoActions / useTodoActivities / 選択肢のフック / useTodoChecklist / useTodoComments (子の部品)。
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
import { TodoMetaLine } from './TodoMetaLine';

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

            {todo && <TodoMetaLine todo={todo} />}

            {detail.status === 'loading' && <PageLoading />}
            {detail.status === 'error' && detail.error && <TodoErrorAlert error={detail.error} test_id="todo-detail-error" onReload={detail.reload} always_retry />}
            {detail.status === 'success' && todo !== null && target !== null && (
                <TodoDetailContent key={todo.id} todo={todo} target={target} needs_organization_reselect={detail.needs_organization_reselect} onUpdated={detail.applyUpdate} onReload={detail.reload} onRefresh={detail.refresh} />
            )}
        </Stack>
    );
};

export default AppTodoDetailPage;
