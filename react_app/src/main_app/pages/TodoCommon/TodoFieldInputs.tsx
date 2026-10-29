/**
 * @desc ToDo の項目の入力欄 (タイトル・説明・期限・優先度、作成ではステータスも)
 * 作成と詳細の編集で共有する。項目ごとに disabled を渡せる (詳細では permissions に応じて無効にする)。
 * data-testid は `${test_id}-title` `-description` `-due-date` `-priority` `-status` の形。
 */
import { MenuItem, Stack, TextField } from '@mui/material';
import { TODO_DESCRIPTION_HELP } from './todo_text';
import { TODO_LIMITS, TODO_PRIORITIES, TODO_STATUSES, type TodoPriority, type TodoStatus } from '@/main_app/api/contract';
import type { TodoFieldErrors, TodoFieldKey, TodoFieldValues } from './todo_form';
import { TODO_PRIORITY_LABELS, TODO_STATUS_LABELS } from './todo_labels';

export type TodoFieldInputsProps = {
    values: TodoFieldValues;
    errors: TodoFieldErrors;
    onChange: (values: TodoFieldValues) => void;
    /** 項目 (タイトル・説明・期限・優先度) を編集できない。 */
    fields_disabled?: boolean;
    /** ステータスの入力欄を出す (作成のみ。詳細では専用の操作を使う)。 */
    show_status?: boolean;
    /** 入力欄を無効にする (保存中)。 */
    pending?: boolean;
    /** 検証エラーでフォーカスする入力欄の登録 (入力欄の要素を受け取る)。 */
    registerField?: (key: TodoFieldKey, element: HTMLInputElement | HTMLTextAreaElement | null) => void;
    test_id: string;
};

export const TodoFieldInputs = ({ values, errors, onChange, fields_disabled = false, show_status = false, pending = false, registerField, test_id }: TodoFieldInputsProps) => {
    const locked = fields_disabled || pending;
    const set = <K extends keyof TodoFieldValues,>(key: K, value: TodoFieldValues[K]) => onChange({ ...values, [key]: value });
    return (
        <Stack spacing={3}>
            <TextField
                label="タイトル"
                required
                fullWidth
                value={values.title}
                onChange={(event) => set('title', event.target.value)}
                disabled={locked}
                error={errors.title !== undefined}
                helperText={errors.title ?? `${values.title.trim().length} / ${TODO_LIMITS.TITLE_MAX} 文字`}
                inputRef={(element: HTMLInputElement | null) => registerField?.('title', element)}
                slotProps={{ htmlInput: { 'data-testid': `${test_id}-title`, autoComplete: 'off' } }}
            />
            <TextField
                label="説明"
                fullWidth
                multiline
                minRows={3}
                value={values.description}
                onChange={(event) => set('description', event.target.value)}
                disabled={locked}
                error={errors.description !== undefined}
                helperText={errors.description ?? TODO_DESCRIPTION_HELP}
                inputRef={(element: HTMLTextAreaElement | null) => registerField?.('description', element)}
                slotProps={{ htmlInput: { 'data-testid': `${test_id}-description` } }}
            />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                <TextField
                    label="期限"
                    type="date"
                    value={values.due_date}
                    onChange={(event) => set('due_date', event.target.value)}
                    disabled={locked}
                    error={errors.due_date !== undefined}
                    helperText={errors.due_date ?? '任意。空にすると期限なしになります。'}
                    inputRef={(element: HTMLInputElement | null) => registerField?.('due_date', element)}
                    slotProps={{ inputLabel: { shrink: true }, htmlInput: { 'data-testid': `${test_id}-due-date` } }}
                    sx={{ minWidth: 200 }}
                />
                <TextField
                    select
                    label="優先度"
                    value={values.priority}
                    onChange={(event) => set('priority', event.target.value as TodoPriority)}
                    disabled={locked}
                    sx={{ minWidth: 160 }}
                    data-testid={`${test_id}-priority`}
                >
                    {TODO_PRIORITIES.map((priority) => <MenuItem key={priority} value={priority} data-testid={`${test_id}-priority-${priority}`}>{TODO_PRIORITY_LABELS[priority]}</MenuItem>)}
                </TextField>
                {show_status && (
                    <TextField
                        select
                        label="ステータス"
                        value={values.status}
                        onChange={(event) => set('status', event.target.value as TodoStatus)}
                        disabled={pending}
                        sx={{ minWidth: 160 }}
                        data-testid={`${test_id}-status`}
                    >
                        {TODO_STATUSES.map((status) => <MenuItem key={status} value={status} data-testid={`${test_id}-status-${status}`}>{TODO_STATUS_LABELS[status]}</MenuItem>)}
                    </TextField>
                )}
            </Stack>
        </Stack>
    );
};

export default TodoFieldInputs;
