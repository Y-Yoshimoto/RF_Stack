/**
 * @desc ToDo 詳細の本体 (詳細の取得後に表示する。ステータス・項目の編集・閲覧範囲・担当者・アクティビティ・削除)
 * 変更操作 (useTodoActions) と結果の通知はここで持つ。操作の可否は詳細の permissions で項目単位に出し分ける。
 * 412 / 428 / 403 todo_operation_forbidden (requires_reload) では再読み込みを促す。再読み込みすると未保存の入力は破棄される。
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Button, Stack } from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import type { TodoDetail, TodoStatus } from '@/main_app/api/contract';
import { useAppSession } from '@/main_app/auth/useAppAuth';
import { ConfirmDialog } from '@/main_app/components/ConfirmDialog';
import { TodoDueText, TodoPriorityChip } from '@/main_app/pages/TodoCommon/TodoBadges';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { TodoSection } from '@/main_app/pages/TodoCommon/TodoSection';
import { TODO_STATUS_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';
import { appTodosPath } from '@/main_app/paths';
import type { TodoChanges, TodoTarget } from '@/main_app/todos/todo_changes';
import { useTodoActions } from '@/main_app/todos/useTodoActions';
import { useTodoActivities } from '@/main_app/todos/useTodoActivities';
import { useTodoAssigneeChoices, useTodoOrganizationChoices } from '@/main_app/todos/useTodoChoices';
import type { TodoActionUpdate } from '@/main_app/todos/useTodo';
import { TodoActivityList } from './TodoActivityList';
import { TodoAssigneesForm } from './TodoAssigneesForm';
import { TodoAudienceForm } from './TodoAudienceForm';
import { TodoFieldsForm } from './TodoFieldsForm';
import { TodoStatusControl } from './TodoStatusControl';

export type TodoDetailContentProps = {
    todo: TodoDetail;
    /** useTodo の target (ETag を含む)。 */
    target: TodoTarget;
    needs_organization_reselect: boolean;
    /** 変更の結果を詳細に反映する (useTodo の applyUpdate)。 */
    onUpdated: (update: TodoActionUpdate) => void;
    /** 詳細を取り直す。 */
    onReload: () => void;
};

export const TodoDetailContent = ({ todo, target, needs_organization_reselect, onUpdated, onReload }: TodoDetailContentProps) => {
    const { tenant_code } = useAppSession();
    const navigate = useNavigate();
    const [notice, setNotice] = useState<string | null>(null);
    const [confirming_delete, setConfirmingDelete] = useState(false);
    const activities = useTodoActivities(todo.id);
    const assignee_choices = useTodoAssigneeChoices(todo.assignees);
    const organization_choices = useTodoOrganizationChoices(todo.organizations);
    const reloadActivities = activities.reload;
    const actions = useTodoActions({
        onUpdated: (update) => {
            onUpdated(update);
            if (update.action !== 'delete') reloadActivities();
        },
    });
    const { permissions } = todo;
    const pending = actions.pending !== null;

    const organizationName = (id: string): string => organization_choices.options.find((option) => option.organization_id === id)?.name ?? '不明な組織';

    const saveChanges = async (changes: TodoChanges, message: string): Promise<boolean> => {
        setNotice(null);
        const result = await actions.update(target, changes);
        if (result.ok) setNotice(message);
        return result.ok;
    };

    const changeStatus = async (status: TodoStatus) => {
        setNotice(null);
        const result = await actions.changeStatus(target, status);
        if (result.ok) setNotice(`ステータスを「${TODO_STATUS_LABELS[status]}」に変更しました。`);
    };

    const saveAssignees = async (user_ids: string[]): Promise<boolean> => {
        setNotice(null);
        const result = await actions.setAssignees(target, user_ids);
        if (result.ok) setNotice('担当者を保存しました。');
        return result.ok;
    };

    const remove = async () => {
        const result = await actions.remove(target);
        // 失敗したらダイアログを開いたままにして、中にエラーを出す
        if (result.ok) void navigate(appTodosPath(tenant_code), { state: { notice: `「${todo.title}」を削除しました。` } });
    };

    const reloadAll = () => {
        actions.clearFailure();
        setNotice(null);
        onReload();
        reloadActivities();
    };

    return (
        <>
            {notice && <Alert severity="success" role="status" onClose={() => setNotice(null)} data-testid="todo-detail-notice">{notice}</Alert>}
            {actions.failure && !confirming_delete && <TodoErrorAlert error={actions.failure} test_id="todo-detail-action-error" onReload={reloadAll} />}

            <Stack direction="row" spacing={2} useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap' }} data-testid="todo-detail-summary">
                <TodoPriorityChip priority={todo.priority} test_id="todo-detail-priority" />
                <TodoDueText due_date={todo.due_date} status={todo.status} test_id="todo-detail-due" />
                {permissions.can_delete && (
                    <Button color="error" variant="outlined" startIcon={<DeleteIcon />} onClick={() => { actions.clearFailure(); setConfirmingDelete(true); }} disabled={pending} data-testid="todo-detail-delete">削除</Button>
                )}
            </Stack>

            <TodoSection title="ステータス" test_id="todo-status-section">
                <TodoStatusControl status={todo.status} editable={permissions.can_change_status} pending={pending} onChange={(status) => void changeStatus(status)} />
            </TodoSection>

            <TodoSection title="項目" test_id="todo-fields-section">
                <TodoFieldsForm key={`fields-${todo.version}`} todo={todo} pending={actions.pending === 'update'} onSave={(changes) => saveChanges(changes, '変更を保存しました。')} />
            </TodoSection>

            <TodoSection title="閲覧範囲" test_id="todo-audience-section">
                <TodoAudienceForm
                    key={`audience-${todo.version}`}
                    todo={todo}
                    needs_reselect={needs_organization_reselect}
                    organizations={organization_choices.options}
                    organizations_status={organization_choices.status}
                    organizations_error={organization_choices.error}
                    onReloadOrganizations={organization_choices.reload}
                    pending={actions.pending === 'update'}
                    onSave={(changes) => saveChanges(changes, '閲覧範囲を保存しました。')}
                />
            </TodoSection>

            <TodoSection title="担当者" test_id="todo-assignees-section">
                <TodoAssigneesForm
                    key={`assignees-${todo.version}`}
                    todo={todo}
                    options={assignee_choices.options}
                    options_loading={assignee_choices.status === 'loading'}
                    options_error={assignee_choices.error}
                    onReloadOptions={assignee_choices.reload}
                    pending={actions.pending === 'set_assignees'}
                    onSave={saveAssignees}
                />
            </TodoSection>

            <TodoSection title="アクティビティ" test_id="todo-activities-section">
                <TodoActivityList activities={activities} organizationName={organizationName} />
            </TodoSection>

            <ConfirmDialog
                open={confirming_delete}
                title="ToDo を削除しますか"
                description={`「${todo.title}」を削除します。削除すると、誰も参照できなくなります。`}
                confirm_label="削除する"
                confirm_color="error"
                pending={actions.pending === 'delete'}
                onConfirm={() => void remove()}
                onCancel={() => setConfirmingDelete(false)}
                test_id="todo-delete-dialog"
            >
                {actions.failure && confirming_delete && <TodoErrorAlert error={actions.failure} test_id="todo-delete-error" onReload={() => { setConfirmingDelete(false); reloadAll(); }} />}
            </ConfirmDialog>
        </>
    );
};

export default TodoDetailContent;
