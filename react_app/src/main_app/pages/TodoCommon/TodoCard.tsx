/**
 * @desc ToDo のカード (狭い画面の一覧・カンバン・ホームの「期限の近い ToDo」で共用)
 * - 通常: タイトル・ステータス・優先度・期限・進捗・コメント数・担当者・作成者・更新日時
 * - compact: ステータス (列やホームで自明) と作成者・更新日時を省く
 * - ステータス欄は status_control (セレクトなど) で差し替えられる。先頭 (leading) と右上 (actions) にドラッグ用のハンドルやメニューを置ける
 * - preview: ドラッグ中の複製として使う (リンクにせず、data-testid も付けない)
 */
import type { ReactNode } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Box, Card, CardContent, Link, Stack, Typography } from '@mui/material';
import type { TodoRead } from '@/main_app/api/contract';
import { formatDateTime } from '@/main_app/components/format';
import { appTodoPath } from '@/main_app/paths';
import { TodoDueText, TodoPriorityChip, TodoStatusChip } from './TodoBadges';
import { TodoItemMeta } from './TodoProgress';
import { assigneeTextOf, userRefTextOf } from './todo_people';

export type TodoCardProps = {
    todo: TodoRead;
    tenant_code: string;
    /** 省スペース表示 (ステータス・作成者・更新日時を省く)。 */
    compact?: boolean;
    /** ステータス欄の差し替え (権限があればセレクト)。省略時は compact でなければチップ。 */
    status_control?: ReactNode;
    /** タイトルの前に置くもの (ドラッグのハンドルなど)。 */
    leading?: ReactNode;
    /** 右上に置くもの (メニューなど)。 */
    actions?: ReactNode;
    /** ドラッグ中の複製 (操作できない見た目だけの表示)。 */
    preview?: boolean;
};

export const TodoCard = ({ todo, tenant_code, compact = false, status_control, leading, actions, preview = false }: TodoCardProps) => {
    const id = todo.id;
    // ドラッグ中の複製は本物のカードと data-testid が重ならないよう別の接頭辞にする
    const key = preview ? `preview-${id}` : id;
    const status = status_control ?? (compact ? null : <TodoStatusChip status={todo.status} test_id={`todo-status-chip-${key}`} />);
    return (
        <Card variant="outlined" sx={{ bgcolor: 'background.paper', ...(preview ? { boxShadow: 6 } : {}) }} data-testid={`todo-card-${key}`} data-status={todo.status}>
            <CardContent sx={{ p: 1.5, '&:last-child': { pb: 1.5 } }}>
                <Stack spacing={0.75}>
                    <Stack direction="row" spacing={0.5} sx={{ alignItems: 'flex-start' }}>
                        {leading}
                        {preview
                            ? <Typography variant="subtitle2" component="p" sx={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{todo.title}</Typography>
                            : (
                                <Typography variant="subtitle2" component="p" sx={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>
                                    <Link component={RouterLink} to={appTodoPath(tenant_code, id)} underline="hover" data-testid={`todo-link-${id}`}>{todo.title}</Link>
                                </Typography>
                            )}
                        {actions}
                    </Stack>
                    <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                        {status && <Box sx={{ display: 'inline-flex' }} data-testid={`todo-status-${key}`}>{status}</Box>}
                        <TodoPriorityChip priority={todo.priority} test_id={`todo-priority-${key}`} />
                        <TodoDueText due_date={todo.due_date} status={todo.status} test_id={`todo-due-${key}`} />
                    </Stack>
                    <TodoItemMeta checklist={todo.checklist} comment_count={todo.comment_count} todo_id={key} />
                    <Typography variant="caption" component="p" color="text.secondary" sx={{ overflowWrap: 'anywhere' }} data-testid={`todo-assignees-${key}`}>
                        {`担当: ${assigneeTextOf(todo)}`}
                    </Typography>
                    {!compact && (
                        <Typography variant="caption" component="p" color="text.secondary" sx={{ overflowWrap: 'anywhere' }} data-testid={`todo-creator-${key}`}>
                            {`作成者: ${userRefTextOf(todo.creator)} / 更新: ${formatDateTime(todo.updated_at)}`}
                        </Typography>
                    )}
                </Stack>
            </CardContent>
        </Card>
    );
};

export default TodoCard;
