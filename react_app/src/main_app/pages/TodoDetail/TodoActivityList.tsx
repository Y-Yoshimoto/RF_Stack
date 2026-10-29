/**
 * @desc ToDo のアクティビティ (変更履歴) の時系列表示 (新しい順。「さらに読み込む」)
 * 操作者・担当者の名前は応答の users (activities.users) で解決する。無効なユーザーは「(無効)」、引けないユーザーは「不明なユーザー」と表示する。
 */
import { Box, Button, CircularProgress, List, ListItem, Stack, Typography } from '@mui/material';
import type { TodoActivitiesState } from '@/main_app/todos/useTodoActivities';
import { formatDateTime } from '@/main_app/components/format';
import { todoActivityActorOf } from '@/main_app/todos/activity_users';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { PageLoading } from '@/shared/components/PageLoading';
import { activityLinesOf, userRefTextOf, type NameLookup } from './activity_text';

export type TodoActivityListProps = {
    activities: TodoActivitiesState;
    organizationName: NameLookup;
};

export const TodoActivityList = ({ activities, organizationName }: TodoActivityListProps) => (
    <Box data-testid="todo-activities">
        {activities.status === 'loading' && <PageLoading />}
        {activities.status === 'error' && activities.error && <TodoErrorAlert error={activities.error} test_id="todo-activities-error" onReload={activities.reload} always_retry />}
        {activities.status === 'success' && activities.items.length === 0 && <Typography variant="body2" color="text.secondary" data-testid="todo-activities-empty">アクティビティはありません。</Typography>}
        {activities.status === 'success' && activities.items.length > 0 && (
            <List component="ol" aria-label="アクティビティ" disablePadding data-testid="todo-activities-list">
                {activities.items.map((activity) => (
                    <ListItem key={activity.id} divider alignItems="flex-start" disableGutters data-testid={`todo-activity-${activity.id}`} data-action={activity.action}>
                        <Stack spacing={0.25}>
                            <Typography variant="body2" color="text.secondary">
                                <time dateTime={activity.created_at}>{formatDateTime(activity.created_at)}</time>
                                <span data-testid={`todo-activity-actor-${activity.id}`}>{` ・ ${userRefTextOf(todoActivityActorOf(activity, activities.users))}`}</span>
                            </Typography>
                            {activityLinesOf(activity, { users: activities.users, organization: organizationName }).map((line) => <Typography key={line} variant="body1" sx={{ overflowWrap: 'anywhere' }}>{line}</Typography>)}
                        </Stack>
                    </ListItem>
                ))}
            </List>
        )}
        {activities.load_more_error && <TodoErrorAlert error={activities.load_more_error} test_id="todo-activities-load-more-error" onReload={activities.load_more_error.requires_reload ? activities.reload : activities.loadMore} always_retry />}
        {activities.has_more && (
            <Button
                variant="outlined"
                onClick={activities.loadMore}
                disabled={activities.is_loading_more}
                startIcon={activities.is_loading_more ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                sx={{ mt: 2 }}
                data-testid="todo-activities-load-more"
            >
                {activities.is_loading_more ? '読み込み中…' : 'さらに読み込む'}
            </Button>
        )}
    </Box>
);

export default TodoActivityList;
