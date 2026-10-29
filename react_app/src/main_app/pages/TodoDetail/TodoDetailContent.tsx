/**
 * @desc ToDo 詳細の本体 (詳細の取得後に表示する。ステータス・項目の編集・チェックリスト・担当者・閲覧範囲・コメント/アクティビティのタブ・削除)
 * 変更操作 (useTodoActions) と結果の通知はここで持つ。操作の可否は詳細の permissions で項目単位に出し分ける。
 * - 3 つのフォームの未保存の入力は useTodoDetailDrafts で持つ。別のフォームの保存や再表示でも、入力中の項目は残る (AP-UX-08)
 * - 412 / 428 / 403 todo_operation_forbidden (requires_reload) で失敗したら、最新の内容を自動で再表示し (onRefresh)、入力は残したまま、
 *   他の人の変更と重なった項目を知らせる (AP-UX-07)。再表示に失敗したら、従来どおり再読み込みを促す (再読み込みすると未保存の入力は破棄される)
 * - コメント数・チェックリストの進捗は、コメント・チェックリストの変更を受けて表示を更新する (詳細の値は自動では変わらない)
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Button, Chip, Stack } from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import type { TodoChecklistProgress, TodoDetail, TodoStatus } from '@/main_app/api/contract';
import { useAppSession } from '@/main_app/auth/useAppAuth';
import { ConfirmDialog } from '@/main_app/components/ConfirmDialog';
import { TodoDueText, TodoPriorityChip } from '@/main_app/pages/TodoCommon/TodoBadges';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { TodoSection } from '@/main_app/pages/TodoCommon/TodoSection';
import { TODO_STATUS_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';
import { appTodosPath } from '@/main_app/paths';
import type { TodoChanges, TodoTarget } from '@/main_app/todos/todo_changes';
import { useTodoActions, type TodoActionResult } from '@/main_app/todos/useTodoActions';
import { useTodoActivities } from '@/main_app/todos/useTodoActivities';
import { useTodoAssigneeChoices, useTodoOrganizationChoices } from '@/main_app/todos/useTodoChoices';
import type { TodoActionUpdate } from '@/main_app/todos/useTodo';
import type { TodoCommentChange } from '@/main_app/todos/useTodoComments';
import { withChecklistProgress, withCommentDelta, shownChecklistProgress, shownCommentCount, type ChecklistProgressOverride, type CommentCountOverride } from './detail_counts';
import { refreshedNoticeTextOf } from './detail_drafts';
import { TodoChecklist } from './TodoChecklist';
import { TodoDetailTabs } from './TodoDetailTabs';
import { TodoAssigneesForm } from './TodoAssigneesForm';
import { TodoAudienceForm } from './TodoAudienceForm';
import { TodoFieldsForm } from './TodoFieldsForm';
import { TodoStatusControl } from './TodoStatusControl';
import { useTodoDetailDrafts } from './useTodoDetailDrafts';

export type TodoDetailContentProps = {
    todo: TodoDetail;
    /** useTodo の target (ETag を含む)。 */
    target: TodoTarget;
    needs_organization_reselect: boolean;
    /** 変更の結果を詳細に反映する (useTodo の applyUpdate)。 */
    onUpdated: (update: TodoActionUpdate) => void;
    /** 詳細を取り直す。 */
    onReload: () => void;
    /** 表示を保ったまま詳細を取り直す (useTodo の refresh。成功すれば true)。 */
    onRefresh: () => Promise<boolean>;
};

export const TodoDetailContent = ({ todo, target, needs_organization_reselect, onUpdated, onReload, onRefresh }: TodoDetailContentProps) => {
    const { tenant_code } = useAppSession();
    const navigate = useNavigate();
    const [notice, setNotice] = useState<string | null>(null);
    const [confirming_delete, setConfirmingDelete] = useState(false);
    const [refreshed, setRefreshed] = useState(false);
    const [refreshing, setRefreshing] = useState(false);
    const [comment_override, setCommentOverride] = useState<CommentCountOverride | null>(null);
    const [checklist_override, setChecklistOverride] = useState<ChecklistProgressOverride | null>(null);
    const drafts = useTodoDetailDrafts(todo);
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

    /**
     * 変更の結果を見て、再表示が必要な失敗なら最新の内容を自動で再表示する関数 (AP-UX-07)
     * 再表示できたら失敗の通知を消して案内を出し、できなければ失敗の通知 (再読み込み) をそのまま残す。
     * @param {TodoActionResult} result 変更操作の結果
     * @returns {Promise<boolean>} 変更に成功していれば true
    */
    const settle = async (result: TodoActionResult): Promise<boolean> => {
        if (result.ok) return true;
        if (result.failure.status === null || !result.failure.requires_reload) return false;
        setRefreshing(true);
        const refreshed_ok = await onRefresh();
        setRefreshing(false);
        if (refreshed_ok) {
            actions.clearFailure();
            setRefreshed(true);
            reloadActivities();
        }
        return false;
    };

    const begin = () => {
        setNotice(null);
        setRefreshed(false);
    };

    const saveChanges = async (changes: TodoChanges, message: string, resetDraft: () => void): Promise<boolean> => {
        begin();
        const ok = await settle(await actions.update(target, changes));
        if (ok) {
            setNotice(message);
            resetDraft();
        }
        return ok;
    };

    const changeStatus = async (status: TodoStatus) => {
        begin();
        if (await settle(await actions.changeStatus(target, status))) setNotice(`ステータスを「${TODO_STATUS_LABELS[status]}」に変更しました。`);
    };

    const saveAssignees = async (user_ids: string[]): Promise<boolean> => {
        begin();
        const ok = await settle(await actions.setAssignees(target, user_ids));
        if (ok) {
            setNotice('担当者を保存しました。');
            drafts.assignees.reset();
        }
        return ok;
    };

    const remove = async () => {
        const result = await actions.remove(target);
        // 失敗したらダイアログを開いたままにして、中にエラーを出す
        if (result.ok) void navigate(appTodosPath(tenant_code), { state: { notice: `「${todo.title}」を削除しました。` } });
    };

    const reloadAll = () => {
        actions.clearFailure();
        setNotice(null);
        setRefreshed(false);
        onReload();
        reloadActivities();
    };

    const onCommentChanged = (change: TodoCommentChange) => {
        const delta = change.action === 'create' ? 1 : change.action === 'delete' ? -1 : 0;
        if (delta !== 0) setCommentOverride(withCommentDelta(todo.comment_count, comment_override, delta));
    };

    const onChecklistChanged = (progress: TodoChecklistProgress) => setChecklistOverride(withChecklistProgress(todo.checklist, progress));

    const progress = shownChecklistProgress(todo.checklist, checklist_override);

    return (
        <>
            {notice && <Alert severity="success" role="status" onClose={() => setNotice(null)} data-testid="todo-detail-notice">{notice}</Alert>}
            {refreshing && <Alert severity="info" role="status" data-testid="todo-detail-refreshing">他のユーザーが更新したため、最新の内容を取得しています…</Alert>}
            {refreshed && <Alert severity="warning" role="alert" onClose={() => setRefreshed(false)} data-testid="todo-detail-refreshed">{refreshedNoticeTextOf(drafts.conflict_labels)}</Alert>}
            {actions.failure && !confirming_delete && !refreshing && <TodoErrorAlert error={actions.failure} test_id="todo-detail-action-error" onReload={reloadAll} />}

            <Stack direction="row" spacing={2} useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap' }} data-testid="todo-detail-summary">
                <TodoPriorityChip priority={todo.priority} test_id="todo-detail-priority" />
                <TodoDueText due_date={todo.due_date} status={todo.status} test_id="todo-detail-due" />
                {progress.total_count > 0 && <Chip size="small" variant="outlined" label={`チェックリスト ${progress.done_count} / ${progress.total_count}`} data-testid="todo-detail-checklist-progress" />}
                {permissions.can_delete && (
                    <Button color="error" variant="outlined" startIcon={<DeleteIcon />} onClick={() => { actions.clearFailure(); setConfirmingDelete(true); }} disabled={pending} data-testid="todo-detail-delete">削除</Button>
                )}
            </Stack>

            <TodoSection title="ステータス" test_id="todo-status-section">
                <TodoStatusControl status={todo.status} editable={permissions.can_change_status} pending={pending} onChange={(status) => void changeStatus(status)} />
            </TodoSection>

            <TodoSection title="項目" test_id="todo-fields-section">
                <TodoFieldsForm
                    todo={todo}
                    values={drafts.fields_values}
                    onChange={drafts.fields.setDraft}
                    has_conflict={drafts.fields.conflicts.length > 0}
                    pending={actions.pending === 'update'}
                    onSave={(changes) => saveChanges(changes, '変更を保存しました。', drafts.fields.reset)}
                />
            </TodoSection>

            <TodoSection title="チェックリスト" test_id="todo-checklist-section">
                <TodoChecklist todo_id={todo.id} onChanged={onChecklistChanged} />
            </TodoSection>

            <TodoSection title="担当者" test_id="todo-assignees-section">
                <TodoAssigneesForm
                    todo={todo}
                    user_ids={drafts.assignee_ids}
                    onChange={(assignee_ids) => drafts.assignees.setDraft({ assignee_ids })}
                    has_conflict={drafts.assignees.conflicts.length > 0}
                    options={assignee_choices.options}
                    options_loading={assignee_choices.status === 'loading'}
                    options_error={assignee_choices.error}
                    onReloadOptions={assignee_choices.reload}
                    pending={actions.pending === 'set_assignees'}
                    onSave={saveAssignees}
                />
            </TodoSection>

            <TodoSection title="閲覧範囲" test_id="todo-audience-section">
                <TodoAudienceForm
                    todo={todo}
                    value={drafts.audience_value}
                    onChange={drafts.audience.setDraft}
                    has_conflict={drafts.audience.conflicts.length > 0}
                    needs_reselect={needs_organization_reselect}
                    organizations={organization_choices.options}
                    organizations_status={organization_choices.status}
                    organizations_error={organization_choices.error}
                    onReloadOrganizations={organization_choices.reload}
                    pending={actions.pending === 'update'}
                    onSave={(changes) => saveChanges(changes, '閲覧範囲を保存しました。', drafts.audience.reset)}
                />
            </TodoSection>

            <TodoDetailTabs
                todo_id={todo.id}
                can_comment={permissions.can_comment}
                comment_count={shownCommentCount(todo.comment_count, comment_override)}
                onCommentChanged={onCommentChanged}
                activities={activities}
                organizationName={organizationName}
            />

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
