/**
 * @desc ToDo 詳細の下部のタブ (「コメント (n)」「アクティビティ」)
 * どちらのパネルも描画したままにして (非表示のパネルは hidden)、タブを切り替えても投稿中の入力や読み込み済みの一覧を失わない。
 */
import { useState, type SyntheticEvent } from 'react';
import { Box, Paper, Tab, Tabs } from '@mui/material';
import type { TodoActivitiesState } from '@/main_app/todos/useTodoActivities';
import type { TodoCommentChange } from '@/main_app/todos/useTodoComments';
import { TodoActivityList } from './TodoActivityList';
import { TodoComments } from './TodoComments';
import type { NameLookup } from './activity_text';

type TabName = 'comments' | 'activities';

export type TodoDetailTabsProps = {
    todo_id: string;
    /** ToDo の permissions.can_comment。 */
    can_comment: boolean;
    /** タブに出すコメント数。 */
    comment_count: number;
    onCommentChanged: (change: TodoCommentChange) => void;
    activities: TodoActivitiesState;
    organizationName: NameLookup;
};

export const TodoDetailTabs = ({ todo_id, can_comment, comment_count, onCommentChanged, activities, organizationName }: TodoDetailTabsProps) => {
    const [tab, setTab] = useState<TabName>('comments');
    return (
        <Paper variant="outlined" component="section" aria-label="コメントとアクティビティ" sx={{ p: 2 }} data-testid="todo-collab-section">
            <Tabs value={tab} onChange={(_event: SyntheticEvent, next: TabName) => setTab(next)} aria-label="コメントとアクティビティ" variant="scrollable" scrollButtons="auto" sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }} data-testid="todo-collab-tabs">
                <Tab value="comments" label={`コメント (${comment_count})`} id="todo-tab-comments" aria-controls="todo-tabpanel-comments" data-testid="todo-tab-comments" />
                <Tab value="activities" label="アクティビティ" id="todo-tab-activities" aria-controls="todo-tabpanel-activities" data-testid="todo-tab-activities" />
            </Tabs>
            <Box role="tabpanel" id="todo-tabpanel-comments" aria-labelledby="todo-tab-comments" hidden={tab !== 'comments'} data-testid="todo-comments-section">
                <TodoComments todo_id={todo_id} can_comment={can_comment} onChanged={onCommentChanged} />
            </Box>
            <Box role="tabpanel" id="todo-tabpanel-activities" aria-labelledby="todo-tab-activities" hidden={tab !== 'activities'} data-testid="todo-activities-section">
                <TodoActivityList activities={activities} organizationName={organizationName} />
            </Box>
        </Paper>
    );
};

export default TodoDetailTabs;
