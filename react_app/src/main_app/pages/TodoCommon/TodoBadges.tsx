/**
 * @desc ToDo のステータス・優先度・期限の表示 (色だけに頼らず、アイコンと文字で区別する)
 */
import AutorenewIcon from '@mui/icons-material/Autorenew';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import EventIcon from '@mui/icons-material/Event';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';
import RemoveIcon from '@mui/icons-material/Remove';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { Chip, Stack, Typography } from '@mui/material';
import type { ReactElement } from 'react';
import type { TodoPriority, TodoStatus } from '@/main_app/api/contract';
import { TODO_PRIORITY_LABELS, TODO_STATUS_LABELS } from './todo_labels';

/** ステータスのアイコン */
export const TODO_STATUS_ICONS: Readonly<Record<TodoStatus, ReactElement>> = {
    open: <RadioButtonUncheckedIcon fontSize="small" aria-hidden />,
    in_progress: <AutorenewIcon fontSize="small" aria-hidden />,
    done: <CheckCircleIcon fontSize="small" aria-hidden />,
};

const STATUS_COLORS: Readonly<Record<TodoStatus, 'default' | 'info' | 'success'>> = { open: 'default', in_progress: 'info', done: 'success' };
const PRIORITY_COLORS: Readonly<Record<TodoPriority, 'default' | 'warning' | 'error'>> = { low: 'default', medium: 'warning', high: 'error' };
const PRIORITY_ICONS: Readonly<Record<TodoPriority, ReactElement>> = {
    low: <ArrowDownwardIcon fontSize="small" aria-hidden />,
    medium: <RemoveIcon fontSize="small" aria-hidden />,
    high: <ArrowUpwardIcon fontSize="small" aria-hidden />,
};

export type TodoStatusChipProps = { status: TodoStatus; test_id: string };

export const TodoStatusChip = ({ status, test_id }: TodoStatusChipProps) => (
    <Chip size="small" variant="outlined" color={STATUS_COLORS[status]} icon={TODO_STATUS_ICONS[status]} label={TODO_STATUS_LABELS[status]} data-testid={test_id} data-status={status} />
);

export type TodoPriorityChipProps = { priority: TodoPriority; test_id: string };

export const TodoPriorityChip = ({ priority, test_id }: TodoPriorityChipProps) => (
    <Chip size="small" variant="outlined" color={PRIORITY_COLORS[priority]} icon={PRIORITY_ICONS[priority]} label={`優先度 ${TODO_PRIORITY_LABELS[priority]}`} data-testid={test_id} data-priority={priority} />
);

/**
 * 今日の日付 (ブラウザのタイムゾーン) を `YYYY-MM-DD` で返す関数
 * @param {Date} now 現在時刻
 * @returns {string} 今日の日付
*/
export const todayOf = (now: Date = new Date()): string => `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;

/**
 * 期限切れかを判定する関数 (完了していない ToDo の期限が今日より前)
 * @param {string | null} due_date 期限
 * @param {TodoStatus} status ステータス
 * @param {string} today 今日の日付
 * @returns {boolean} 期限切れなら true
*/
export const isOverdue = (due_date: string | null, status: TodoStatus, today: string = todayOf()): boolean => due_date !== null && status !== 'done' && due_date < today;

export type TodoDueTextProps = { due_date: string | null; status: TodoStatus; test_id: string };

export const TodoDueText = ({ due_date, status, test_id }: TodoDueTextProps) => {
    if (due_date === null) return <Typography variant="body2" color="text.secondary" component="span" data-testid={test_id}>期限なし</Typography>;
    const overdue = isOverdue(due_date, status);
    return (
        <Stack direction="row" spacing={0.5} component="span" data-testid={test_id} data-overdue={overdue} sx={{ alignItems: 'center', display: 'inline-flex' }}>
            {overdue ? <WarningAmberIcon fontSize="small" color="error" aria-hidden /> : <EventIcon fontSize="small" color="action" aria-hidden />}
            <Typography variant="body2" component="span" color={overdue ? 'error' : 'text.primary'}>{due_date}{overdue ? ' (期限切れ)' : ''}</Typography>
        </Stack>
    );
};
