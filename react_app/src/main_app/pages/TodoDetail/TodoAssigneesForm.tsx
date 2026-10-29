/**
 * @desc ToDo の担当者の置き換えフォーム (最大 20 人。permissions.can_change_assignees が false なら表示のみ)
 * 無効化されたユーザーは「無効」と表示し、外すことはできる (AP-ASN-04)。
 */
import { Alert, Box, Button, CircularProgress } from '@mui/material';
import type { TodoDetail } from '@/main_app/api/contract';
import type { AppErrorInfo } from '@/main_app/api/errors';
import { AssigneePicker } from '@/main_app/pages/TodoCommon/AssigneePicker';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { sameIdSet } from '@/main_app/todos/todo_changes';
import type { TodoAssigneeOption } from '@/main_app/todos/useTodoChoices';

export type TodoAssigneesFormProps = {
    todo: TodoDetail;
    /** 選択中の担当者 (下書き。親が持つ)。 */
    user_ids: string[];
    onChange: (user_ids: string[]) => void;
    /** 他の人の変更と重なっている (入力は残している)。 */
    has_conflict?: boolean;
    options: readonly TodoAssigneeOption[];
    options_loading: boolean;
    options_error: AppErrorInfo | null;
    onReloadOptions: () => void;
    pending: boolean;
    onSave: (user_ids: string[]) => Promise<boolean>;
};

export const TodoAssigneesForm = ({ todo, user_ids, onChange, has_conflict = false, options, options_loading, options_error, onReloadOptions, pending, onSave }: TodoAssigneesFormProps) => {
    const current_ids = todo.assignees.map((assignee) => assignee.user_id);
    const editable = todo.permissions.can_change_assignees;
    const is_changed = !sameIdSet(current_ids, user_ids);
    return (
        <Box data-testid="todo-assignees-form" data-editable={editable} data-conflict={has_conflict}>
            {!editable && <Alert severity="info" sx={{ mb: 2 }} data-testid="todo-assignees-readonly">担当者を変更できるのは、作成者・担当者・テナント管理者だけです。</Alert>}
            {options_error && <TodoErrorAlert error={options_error} test_id="todo-assignees-load-error" onReload={onReloadOptions} always_retry />}
            <AssigneePicker options={options} value={user_ids} onChange={onChange} loading={options_loading} disabled={!editable || pending} test_id="todo-edit-assignees" />
            {editable && (
                <Button
                    variant="contained"
                    onClick={() => void onSave(user_ids)}
                    disabled={pending || !is_changed}
                    startIcon={pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                    sx={{ mt: 2 }}
                    data-testid="todo-assignees-submit"
                >
                    {pending ? '保存中…' : '担当者を保存'}
                </Button>
            )}
        </Box>
    );
};

export default TodoAssigneesForm;
