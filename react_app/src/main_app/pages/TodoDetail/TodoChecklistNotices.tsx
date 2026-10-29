/**
 * @desc チェックリストの読み込み中・読み込みの失敗・操作の失敗の通知
 * 412 などで最新を取り直せたときは、エラーではなく「最新を表示しました」と知らせる (failure_refreshed)。失敗は role="alert" で読み上げる。
 */
import { Alert, Box } from '@mui/material';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import type { TodoChecklistState } from '@/main_app/todos/useTodoChecklist';
import { PageLoading } from '@/shared/components/PageLoading';

export type TodoChecklistNoticesProps = {
    checklist: TodoChecklistState;
};

export const TodoChecklistNotices = ({ checklist }: TodoChecklistNoticesProps) => {
    const { failure } = checklist;
    return (
        <>
            {checklist.status === 'loading' && <PageLoading />}
            {checklist.status === 'error' && checklist.error && <TodoErrorAlert error={checklist.error} test_id="todo-checklist-load-error" onReload={checklist.reload} always_retry />}
            {failure && checklist.failure_refreshed && (
                <Alert severity="warning" role="alert" sx={{ mb: 2 }} onClose={checklist.clearFailure} data-testid="todo-checklist-refreshed">
                    他のユーザーが更新したため、チェックリストの最新の内容を表示しました。確認してもう一度操作してください。
                </Alert>
            )}
            {failure && !checklist.failure_refreshed && (
                <Box sx={{ mb: 2 }}>
                    <TodoErrorAlert error={failure} test_id="todo-checklist-error" onReload={() => { checklist.clearFailure(); checklist.reload(); }} />
                </Box>
            )}
        </>
    );
};

export default TodoChecklistNotices;
