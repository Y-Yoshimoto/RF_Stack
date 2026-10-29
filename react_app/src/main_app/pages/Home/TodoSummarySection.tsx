/**
 * @desc ホームの ToDo の要約 (AP-UX-01)
 * - 4 枚の要約カード (担当の未完了 / 期限切れ / 7 日以内 / 自分が作成した未完了)。各カードは絞り込み済みの一覧へのリンク
 * - 期限の近い担当 ToDo の上位 5 件 (小さいカード) と「すべて見る」
 * 要約・一覧のどちらかが失敗しても、その部分だけにエラーと再試行を出し、ホーム全体は止めない。
 * 期限切れは色だけでなく、警告アイコンと文字でも示す。
 */
import type { ReactElement } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Box, Button, Card, CardActionArea, CardContent, Skeleton, Stack, Typography } from '@mui/material';
import AssignmentIndOutlinedIcon from '@mui/icons-material/AssignmentIndOutlined';
import EditNoteIcon from '@mui/icons-material/EditNote';
import EventIcon from '@mui/icons-material/Event';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import type { TodoSummary } from '@/main_app/api/contract';
import type { TodoListFilter } from '@/main_app/api/todos';
import { useAppSession } from '@/main_app/auth/useAppAuth';
import { TodoCard } from '@/main_app/pages/TodoCommon/TodoCard';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { appTodosPath } from '@/main_app/paths';
import { toTodoListSearch } from '@/main_app/todos/list_search';
import { TODO_SUMMARY_UPCOMING_FILTER, todoSummaryCountsOf, todoSummaryFiltersOf, type TodoSummaryCard } from '@/main_app/todos/todo_summary';
import { useTodoList } from '@/main_app/todos/useTodoList';
import { useTodoSummary } from '@/main_app/todos/useTodoSummary';

/** 要約カードの並びと表示 */
const SUMMARY_CARDS: readonly { key: TodoSummaryCard; label: string; icon: ReactElement; alert?: boolean }[] = [
    { key: 'assigned_unfinished', label: '担当の未完了', icon: <AssignmentIndOutlinedIcon aria-hidden /> },
    { key: 'assigned_overdue', label: '期限切れ', icon: <WarningAmberIcon aria-hidden />, alert: true },
    { key: 'assigned_due_soon', label: '7 日以内に期限', icon: <EventIcon aria-hidden /> },
    { key: 'created_unfinished', label: '自分が作成した未完了', icon: <EditNoteIcon aria-hidden /> },
];

const GRID_SX = { display: 'grid', gap: 2, gridTemplateColumns: { xs: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' } } as const;

/**
 * 絞り込み済みの一覧のパスを作る関数
 * @param {string} tenant_code テナントコード
 * @param {TodoListFilter} filter 絞り込み
 * @returns {string} 一覧のパス (クエリ付き)
*/
const listPathOf = (tenant_code: string, filter: TodoListFilter): string => {
    const search = toTodoListSearch(filter).toString();
    return search === '' ? appTodosPath(tenant_code) : `${appTodosPath(tenant_code)}?${search}`;
};

const SummaryCards = ({ summary, tenant_code }: { summary: TodoSummary; tenant_code: string }) => {
    const counts = todoSummaryCountsOf(summary);
    const filters = todoSummaryFiltersOf(summary);
    return (
        <Box component="ul" role="list" aria-label="ToDo の件数" sx={{ ...GRID_SX, listStyle: 'none', m: 0, p: 0 }} data-testid="todo-summary-cards">
            {SUMMARY_CARDS.map(({ key, label, icon, alert }) => {
                const highlight = alert === true && counts[key] > 0;
                const text_color = highlight ? 'error.main' : 'text.secondary';
                return (
                    <li key={key}>
                        <Card variant="outlined" sx={{ height: '100%', ...(highlight ? { borderColor: 'error.main', borderWidth: 2 } : {}) }} data-testid={`todo-summary-card-${key}`} data-count={counts[key]}>
                            <CardActionArea component={RouterLink} to={listPathOf(tenant_code, filters[key])} sx={{ height: '100%' }} data-testid={`todo-summary-link-${key}`}>
                                <CardContent>
                                    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', color: text_color }}>
                                        {icon}
                                        <Typography variant="body2" component="span" sx={{ color: text_color, fontWeight: highlight ? 'bold' : undefined }}>{label}</Typography>
                                    </Stack>
                                    <Typography variant="h4" component="p" sx={{ mt: 1 }}>
                                        <span data-testid={`todo-summary-count-${key}`}>{counts[key]}</span>
                                        <Typography variant="body2" component="span" color="text.secondary"> 件</Typography>
                                    </Typography>
                                </CardContent>
                            </CardActionArea>
                        </Card>
                    </li>
                );
            })}
        </Box>
    );
};

const SummarySkeleton = () => (
    <Box sx={GRID_SX} role="status" aria-label="ToDo の件数を読み込み中" data-testid="todo-summary-loading">
        {SUMMARY_CARDS.map(({ key }) => <Skeleton key={key} variant="rounded" height={104} />)}
    </Box>
);

const UpcomingList = ({ tenant_code }: { tenant_code: string }) => {
    const list = useTodoList(TODO_SUMMARY_UPCOMING_FILTER);
    return (
        <Box component="section" aria-labelledby="todo-summary-upcoming-heading" data-testid="todo-summary-upcoming">
            <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Typography id="todo-summary-upcoming-heading" variant="subtitle1" component="h3">期限の近い担当 ToDo</Typography>
                <Button component={RouterLink} to={listPathOf(tenant_code, TODO_SUMMARY_UPCOMING_FILTER)} size="small" data-testid="todo-summary-upcoming-all">すべて見る</Button>
            </Stack>
            {list.status === 'loading' && (
                <Stack spacing={1} role="status" aria-label="期限の近い ToDo を読み込み中" data-testid="todo-summary-upcoming-loading">
                    <Skeleton variant="rounded" height={72} />
                    <Skeleton variant="rounded" height={72} />
                </Stack>
            )}
            {list.status === 'error' && list.error && <TodoErrorAlert error={list.error} test_id="todo-summary-upcoming-error" onReload={list.reload} always_retry />}
            {list.status === 'success' && (list.items.length === 0 ? (
                <Typography variant="body2" color="text.secondary" data-testid="todo-summary-upcoming-empty">期限の近い担当の ToDo はありません。</Typography>
            ) : (
                <Stack component="ul" role="list" aria-label="期限の近い担当 ToDo" spacing={1} sx={{ listStyle: 'none', m: 0, p: 0 }} data-testid="todo-summary-upcoming-list">
                    {list.items.map((todo) => <li key={todo.id}><TodoCard todo={todo} tenant_code={tenant_code} compact /></li>)}
                </Stack>
            ))}
        </Box>
    );
};

export const TodoSummarySection = () => {
    const { tenant_code } = useAppSession();
    const summary = useTodoSummary();
    return (
        <Box component="section" aria-labelledby="todo-summary-heading" data-testid="todo-summary">
            <Stack spacing={2}>
                <Typography id="todo-summary-heading" variant="h6" component="h2">ToDo の要約</Typography>
                {summary.status === 'loading' && <SummarySkeleton />}
                {summary.status === 'error' && summary.error && <TodoErrorAlert error={summary.error} test_id="todo-summary-error" onReload={summary.reload} always_retry />}
                {summary.status === 'success' && summary.summary && <SummaryCards summary={summary.summary} tenant_code={tenant_code} />}
                <UpcomingList tenant_code={tenant_code} />
            </Stack>
        </Box>
    );
};

export default TodoSummarySection;
