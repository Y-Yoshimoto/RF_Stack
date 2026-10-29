/**
 * @desc ToDo の作成 (`/{tenant_code}/todos/new`。tenant_admin / member のどちらも可)
 * タイトル・説明・期限・優先度・ステータス・閲覧範囲 (既定は private。organization では組織を選択)・担当者 (最大 20 人) を入力して作成する。
 * 作成に成功したら詳細へ遷移する。使うフック: useTodoActions (作成)、useTodoAssigneeChoices / useTodoOrganizationChoices (選択肢)。
 */
import { useRef, useState, type FormEvent } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { Box, Button, CircularProgress, Stack } from '@mui/material';
import { TODO_DEFAULTS } from '@/main_app/api/contract';
import { useAppSession } from '@/main_app/auth/useAppAuth';
import { PageHeader } from '@/main_app/components/PageHeader';
import { AssigneePicker } from '@/main_app/pages/TodoCommon/AssigneePicker';
import { AudienceFields, type AudienceValue } from '@/main_app/pages/TodoCommon/AudienceFields';
import { INITIAL_TODO_FIELDS, TODO_FIELD_ORDER, validateTodoFields, type TodoFieldErrors, type TodoFieldKey, type TodoFieldValues } from '@/main_app/pages/TodoCommon/todo_form';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { TodoFieldInputs } from '@/main_app/pages/TodoCommon/TodoFieldInputs';
import { TodoSection } from '@/main_app/pages/TodoCommon/TodoSection';
import { appTodoPath, appTodosPath } from '@/main_app/paths';
import { useTodoActions } from '@/main_app/todos/useTodoActions';
import { useTodoAssigneeChoices, useTodoOrganizationChoices } from '@/main_app/todos/useTodoChoices';

const INITIAL_AUDIENCE: AudienceValue = { visibility: TODO_DEFAULTS.VISIBILITY, organization_ids: [] };
const ORGANIZATIONS_REQUIRED = '公開先の組織を 1 つ以上選んでください。';

export const AppTodoCreatePage = () => {
    const { tenant_code } = useAppSession();
    const navigate = useNavigate();
    const actions = useTodoActions();
    const assignee_choices = useTodoAssigneeChoices();
    const organization_choices = useTodoOrganizationChoices();
    const [values, setValues] = useState<TodoFieldValues>(INITIAL_TODO_FIELDS);
    const [audience, setAudience] = useState<AudienceValue>(INITIAL_AUDIENCE);
    const [assignee_ids, setAssigneeIds] = useState<string[]>([]);
    const [errors, setErrors] = useState<TodoFieldErrors>({});
    const [organizations_error, setOrganizationsError] = useState<string | undefined>(undefined);
    const field_refs = useRef<Partial<Record<TodoFieldKey, HTMLInputElement | HTMLTextAreaElement | null>>>({});
    const is_pending = actions.pending === 'create';

    const changeAudience = (next: AudienceValue) => {
        setAudience(next);
        setOrganizationsError(undefined);
    };

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        const found = validateTodoFields(values);
        const lacks_organizations = audience.visibility === 'organization' && audience.organization_ids.length === 0;
        setErrors(found);
        setOrganizationsError(lacks_organizations ? ORGANIZATIONS_REQUIRED : undefined);
        const first_invalid = TODO_FIELD_ORDER.find((key) => found[key] !== undefined);
        if (first_invalid) {
            field_refs.current[first_invalid]?.focus();
            return;
        }
        if (lacks_organizations) return;
        const result = await actions.create({
            title: values.title.trim(),
            description: values.description === '' ? null : values.description,
            due_date: values.due_date === '' ? null : values.due_date,
            priority: values.priority,
            status: values.status,
            visibility: audience.visibility,
            ...(audience.visibility === 'organization' ? { organization_ids: audience.organization_ids } : {}),
            assignee_ids,
        });
        if (result.ok && result.action === 'create') void navigate(appTodoPath(tenant_code, result.todo.id));
    };

    return (
        <Stack spacing={3} data-testid="app-todo-create-page">
            <PageHeader test_id="todo-create" title="ToDo の作成" description="閲覧範囲の既定は非公開 (作成者と担当者のみ) です。" back={{ to: appTodosPath(tenant_code), label: 'ToDo 一覧へ戻る' }} />
            <Box component="form" noValidate onSubmit={(event: FormEvent) => void submit(event)} aria-label="ToDo の作成" data-testid="todo-create-form" sx={{ maxWidth: 720 }}>
                <Stack spacing={3}>
                    {actions.failure && <TodoErrorAlert error={actions.failure} test_id="todo-create-error" />}
                    <TodoSection title="基本情報" test_id="todo-create-fields-section">
                        <TodoFieldInputs values={values} errors={errors} onChange={setValues} show_status pending={is_pending} registerField={(key, element) => { field_refs.current[key] = element; }} test_id="todo-create-field" />
                    </TodoSection>
                    <TodoSection title="閲覧範囲" test_id="todo-create-audience-section">
                        <AudienceFields
                            value={audience}
                            onChange={changeAudience}
                            organizations={organization_choices.options}
                            organizations_status={organization_choices.status}
                            organizations_error={organization_choices.error}
                            onReloadOrganizations={organization_choices.reload}
                            organizations_error_text={organizations_error}
                            disabled={is_pending}
                            test_id="todo-create-audience"
                        />
                    </TodoSection>
                    <TodoSection title="担当者" test_id="todo-create-assignees-section">
                        {assignee_choices.error && <TodoErrorAlert error={assignee_choices.error} test_id="todo-create-assignees-load-error" onReload={assignee_choices.reload} always_retry />}
                        <AssigneePicker
                            options={assignee_choices.options.filter((option) => option.is_active)}
                            value={assignee_ids}
                            onChange={setAssigneeIds}
                            loading={assignee_choices.status === 'loading'}
                            disabled={is_pending}
                            test_id="todo-create-assignees"
                        />
                    </TodoSection>
                    <Stack direction="row" spacing={2}>
                        <Button
                            type="submit"
                            variant="contained"
                            disabled={is_pending}
                            startIcon={is_pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                            data-testid="todo-create-submit"
                        >
                            {is_pending ? '作成中…' : '作成する'}
                        </Button>
                        <Button component={RouterLink} to={appTodosPath(tenant_code)} disabled={is_pending} data-testid="todo-create-cancel">キャンセル</Button>
                    </Stack>
                </Stack>
            </Box>
        </Stack>
    );
};

export default AppTodoCreatePage;
