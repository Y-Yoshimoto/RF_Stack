/**
 * @desc ToDo のステータスの変更 (3 つのボタンから選ぶと、すぐに保存する。担当者も使える: AP-ASN-03)
 */
import { ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import { TODO_STATUSES, type TodoStatus } from '@/main_app/api/contract';
import { TODO_STATUS_ICONS } from '@/main_app/pages/TodoCommon/TodoBadges';
import { TODO_STATUS_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';

export type TodoStatusControlProps = {
    status: TodoStatus;
    /** ステータスを変えられる (permissions.can_change_status)。 */
    editable: boolean;
    pending: boolean;
    onChange: (status: TodoStatus) => void;
};

export const TodoStatusControl = ({ status, editable, pending, onChange }: TodoStatusControlProps) => (
    <>
        <ToggleButtonGroup
            exclusive
            size="small"
            aria-label="ステータス"
            value={status}
            disabled={!editable || pending}
            onChange={(_event, next: TodoStatus | null) => {
                if (next !== null && next !== status) onChange(next);
            }}
            data-testid="todo-status-control"
        >
            {TODO_STATUSES.map((value) => (
                <ToggleButton key={value} value={value} sx={{ gap: 0.5 }} data-testid={`todo-status-${value}`}>{TODO_STATUS_ICONS[value]}{TODO_STATUS_LABELS[value]}</ToggleButton>
            ))}
        </ToggleButtonGroup>
        {!editable && <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }} data-testid="todo-status-readonly">ステータスを変更できるのは、作成者・担当者・テナント管理者です。</Typography>}
    </>
);

export default TodoStatusControl;
