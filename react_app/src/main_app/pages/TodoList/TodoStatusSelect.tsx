/**
 * @desc 一覧の行でステータスをすばやく変えるセレクト (作成者・担当者・tenant_admin 向け)
 */
import { MenuItem, Select, Stack } from '@mui/material';
import { TODO_STATUSES, type TodoStatus } from '@/main_app/api/contract';
import { TODO_STATUS_ICONS } from '@/main_app/pages/TodoCommon/TodoBadges';
import { TODO_STATUS_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';

export type TodoStatusSelectProps = {
    todo_id: string;
    title: string;
    status: TodoStatus;
    disabled: boolean;
    onChange: (status: TodoStatus) => void;
};

export const TodoStatusSelect = ({ todo_id, title, status, disabled, onChange }: TodoStatusSelectProps) => (
    <Select
        size="small"
        value={status}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as TodoStatus)}
        renderValue={(value) => <Stack direction="row" spacing={0.5} component="span" sx={{ alignItems: 'center' }}>{TODO_STATUS_ICONS[value]}<span>{TODO_STATUS_LABELS[value]}</span></Stack>}
        inputProps={{ 'aria-label': `「${title}」のステータスを変更`, 'data-testid': `todo-status-input-${todo_id}` }}
        data-testid={`todo-status-select-${todo_id}`}
        sx={{ minWidth: 130 }}
    >
        {TODO_STATUSES.map((value) => <MenuItem key={value} value={value} data-testid={`todo-status-option-${todo_id}-${value}`}>{TODO_STATUS_LABELS[value]}</MenuItem>)}
    </Select>
);

export default TodoStatusSelect;
