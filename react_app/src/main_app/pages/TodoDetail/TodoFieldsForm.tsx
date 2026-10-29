/**
 * @desc ToDo の項目 (タイトル・説明・期限・優先度) の編集フォーム
 * permissions.can_edit_fields が false なら入力を無効にして保存ボタンも出さない (担当者は項目を編集できない)。
 * 実際に変わった項目だけを diffTodoChanges で求め、変更が無ければ保存できない。
 */
import { useRef, useState, type FormEvent } from 'react';
import { Alert, Box, Button, CircularProgress } from '@mui/material';
import type { TodoDetail } from '@/main_app/api/contract';
import { fieldValuesOf, TODO_FIELD_ORDER, validateTodoFields, type TodoFieldErrors, type TodoFieldKey, type TodoFieldValues } from '@/main_app/pages/TodoCommon/todo_form';
import { TodoFieldInputs } from '@/main_app/pages/TodoCommon/TodoFieldInputs';
import { diffTodoChanges, type TodoChanges } from '@/main_app/todos/todo_changes';

export type TodoFieldsFormProps = {
    todo: TodoDetail;
    pending: boolean;
    /** 変更を保存する (変更のある項目だけを渡す)。 */
    onSave: (changes: TodoChanges) => Promise<boolean>;
};

/**
 * 入力値から変更内容を作る関数
 * @param {TodoFieldValues} values 入力値
 * @returns {TodoChanges} 変更内容 (タイトルは前後の空白を除く)
*/
const changesOf = (values: TodoFieldValues): TodoChanges => ({
    title: values.title.trim(),
    description: values.description,
    due_date: values.due_date === '' ? null : values.due_date,
    priority: values.priority,
});

export const TodoFieldsForm = ({ todo, pending, onSave }: TodoFieldsFormProps) => {
    const [values, setValues] = useState<TodoFieldValues>(fieldValuesOf(todo));
    const [errors, setErrors] = useState<TodoFieldErrors>({});
    const field_refs = useRef<Partial<Record<TodoFieldKey, HTMLInputElement | HTMLTextAreaElement | null>>>({});
    const editable = todo.permissions.can_edit_fields;
    const is_changed = Object.keys(diffTodoChanges(todo, changesOf(values))).length > 0;

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        const found = validateTodoFields(values);
        setErrors(found);
        const first_invalid = TODO_FIELD_ORDER.find((key) => found[key] !== undefined);
        if (first_invalid) {
            field_refs.current[first_invalid]?.focus();
            return;
        }
        await onSave(diffTodoChanges(todo, changesOf(values)));
    };

    return (
        <Box component="form" noValidate onSubmit={(event: FormEvent) => void submit(event)} aria-labelledby="todo-fields-section-heading" data-testid="todo-fields-form" data-editable={editable}>
            {!editable && <Alert severity="info" sx={{ mb: 2 }} data-testid="todo-fields-readonly">タイトル・説明・期限・優先度を編集できるのは、作成者とテナント管理者だけです。</Alert>}
            <TodoFieldInputs values={values} errors={errors} onChange={setValues} fields_disabled={!editable} pending={pending} registerField={(key, element) => { field_refs.current[key] = element; }} test_id="todo-edit" />
            {editable && (
                <Button
                    type="submit"
                    variant="contained"
                    disabled={pending || !is_changed}
                    startIcon={pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                    sx={{ mt: 3 }}
                    data-testid="todo-fields-submit"
                >
                    {pending ? '保存中…' : '変更を保存'}
                </Button>
            )}
        </Box>
    );
};

export default TodoFieldsForm;
