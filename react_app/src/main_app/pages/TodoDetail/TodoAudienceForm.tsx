/**
 * @desc ToDo の閲覧範囲・公開先組織の編集フォーム (permissions.can_change_visibility が false なら表示のみ)
 * 公開先の組織がすべて削除されて private 扱いになっている場合 (needs_organization_reselect) は、組織の再指定を促す。
 */
import { useState } from 'react';
import { Alert, Box, Button, CircularProgress } from '@mui/material';
import type { TodoDetail } from '@/main_app/api/contract';
import { AudienceFields, type AudienceValue } from '@/main_app/pages/TodoCommon/AudienceFields';
import { diffTodoChanges, type TodoChanges } from '@/main_app/todos/todo_changes';
import type { TodoOrganizationOption } from '@/main_app/todos/useTodoChoices';
import type { AppErrorInfo } from '@/main_app/api/errors';

export type TodoAudienceFormProps = {
    todo: TodoDetail;
    /** 入力値 (下書き。親が持つ)。 */
    value: AudienceValue;
    onChange: (value: AudienceValue) => void;
    /** 他の人の変更と重なった項目がある (入力は残している)。 */
    has_conflict?: boolean;
    needs_reselect: boolean;
    organizations: readonly TodoOrganizationOption[];
    organizations_status: 'loading' | 'success' | 'error';
    organizations_error: AppErrorInfo | null;
    onReloadOrganizations: () => void;
    pending: boolean;
    onSave: (changes: TodoChanges) => Promise<boolean>;
};

const ORGANIZATIONS_REQUIRED = '公開先の組織を 1 つ以上選んでください。';

export const TodoAudienceForm = ({ todo, value, onChange, has_conflict = false, needs_reselect, organizations, organizations_status, organizations_error, onReloadOrganizations, pending, onSave }: TodoAudienceFormProps) => {
    const [error_text, setErrorText] = useState<string | undefined>(undefined);
    const editable = todo.permissions.can_change_visibility;
    const changes: TodoChanges = { audience: value };
    const is_changed = Object.keys(diffTodoChanges(todo, changes)).length > 0;

    const change = (next: AudienceValue) => {
        onChange(next);
        setErrorText(undefined);
    };

    const save = async () => {
        if (value.visibility === 'organization' && value.organization_ids.length === 0) {
            setErrorText(ORGANIZATIONS_REQUIRED);
            return;
        }
        await onSave(diffTodoChanges(todo, changes));
    };

    return (
        <Box data-testid="todo-audience-form" data-editable={editable} data-conflict={has_conflict}>
            {needs_reselect && (
                <Alert severity="warning" sx={{ mb: 2 }} data-testid="todo-reselect-notice">
                    {editable
                        ? '公開先に指定していた組織がすべて削除されたため、現在は非公開 (作成者と担当者のみ) と同じ扱いです。公開先の組織を選び直すか、閲覧範囲を変更してください。'
                        : '公開先に指定していた組織がすべて削除されたため、現在は非公開 (作成者と担当者のみ) と同じ扱いです。作成者またはテナント管理者に、公開先の再指定を依頼してください。'}
                </Alert>
            )}
            {!editable && <Alert severity="info" sx={{ mb: 2 }} data-testid="todo-audience-readonly">閲覧範囲を変更できるのは、作成者とテナント管理者だけです。</Alert>}
            <AudienceFields
                value={value}
                onChange={change}
                organizations={organizations}
                organizations_status={organizations_status}
                organizations_error={organizations_error}
                onReloadOrganizations={onReloadOrganizations}
                organizations_error_text={error_text}
                disabled={!editable || pending}
                test_id="todo-edit-audience"
            />
            {editable && (
                <Button
                    variant="contained"
                    onClick={() => void save()}
                    disabled={pending || !is_changed}
                    startIcon={pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                    sx={{ mt: 2 }}
                    data-testid="todo-audience-submit"
                >
                    {pending ? '保存中…' : '閲覧範囲を保存'}
                </Button>
            )}
        </Box>
    );
};

export default TodoAudienceForm;
