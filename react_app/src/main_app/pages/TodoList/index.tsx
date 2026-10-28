/**
 * @desc ToDo 一覧 (`/{tenant_code}/todos`。tenant_admin / member のどちらも可)
 * 表示範囲 (すべて / 自分が作成 / 自分が担当 / 共有された) のタブ、ステータス・優先度・担当者・公開先組織・期限の絞り込み、タイトル検索、並び替え (キー 1 つ)、
 * 「さらに読み込む」を持つ。絞り込みはすべて URL のクエリ (`?scope=mine&status=open`) に持たせる。
 *
 * 一覧からのステータス変更: 一覧 API の要素は permissions を持たないため、詳細を開いての判定はせず、サーバーの権限表と同じ条件
 * (tenant_admin・作成者・担当者) を操作者の ID とロールで先に判定し、該当する行だけセレクトを出す (list_rules.ts)。
 * 判定が古い場合は API が 403 / 412 を返し、再読み込みを促す。
 * 使うフック: useTodoList (一覧)、useTodoActions (ステータス変更)、useMe (自分の ID)、useTodoAssigneeChoices / useTodoOrganizationChoices (絞り込みの選択肢)。
 */
import { useMemo, useState } from 'react';
import { Link as RouterLink, useLocation, useSearchParams } from 'react-router-dom';
import { Alert, Box, Button, Stack, Tab, Tabs, Typography } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { type TodoRead, type TodoScope, type TodoStatus } from '@/main_app/api/contract';
import type { TodoListFilter } from '@/main_app/api/todos';
import { useAppPermissions, useAppSession } from '@/main_app/auth/useAppAuth';
import { ListFooter } from '@/main_app/components/ListFooter';
import { PageHeader } from '@/main_app/components/PageHeader';
import { useMe } from '@/main_app/me/useMe';
import { TODO_SCOPE_LABELS, TODO_STATUS_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { appTodoCreatePath } from '@/main_app/paths';
import { parseTodoListSearch, toTodoListSearch } from '@/main_app/todos/list_search';
import { todoReadOf, todoTargetOf } from '@/main_app/todos/todo_changes';
import { useTodoActions } from '@/main_app/todos/useTodoActions';
import { useTodoAssigneeChoices, useTodoOrganizationChoices } from '@/main_app/todos/useTodoChoices';
import { useTodoList } from '@/main_app/todos/useTodoList';
import { PageLoading } from '@/shared/components/PageLoading';
import { canChangeStatusInList, hasListConditions } from './list_rules';
import { TodoFilterBar } from './TodoFilterBar';
import { TodoTable } from './TodoTable';

const PANEL_ID = 'todo-scope-panel';

/** タブの並び (既定の「すべて」を先頭にする) */
const SCOPE_TAB_ORDER: readonly TodoScope[] = ['all', 'mine', 'assigned', 'shared'];

/**
 * 直前の画面 (削除など) から渡された通知を取り出す関数
 * @param {unknown} state location.state
 * @returns {string | null} 通知
*/
const noticeOf = (state: unknown): string | null => {
    if (typeof state !== 'object' || state === null || !('notice' in state)) return null;
    return typeof state.notice === 'string' ? state.notice : null;
};

export const AppTodoListPage = () => {
    const { tenant_code } = useAppSession();
    const { is_tenant_admin } = useAppPermissions();
    const location = useLocation();
    const [search_params, setSearchParams] = useSearchParams();
    const filter = useMemo(() => parseTodoListSearch(search_params), [search_params]);
    const scope: TodoScope = filter.scope ?? 'all';
    const list = useTodoList(filter);
    const me = useMe();
    const assignee_choices = useTodoAssigneeChoices();
    const organization_choices = useTodoOrganizationChoices();
    const [notice, setNotice] = useState<string | null>(noticeOf(location.state));
    const [changing_id, setChangingId] = useState<string | null>(null);

    const actions = useTodoActions({
        onUpdated: (update) => {
            if (update.action === 'change_status') list.replaceItem(todoReadOf(update.todo));
        },
    });
    const has_conditions = hasListConditions(filter);

    const changeFilter = (next: TodoListFilter) => setSearchParams(toTodoListSearch(next, search_params), { replace: true });

    const changeStatus = async (todo: TodoRead, status: TodoStatus) => {
        setNotice(null);
        setChangingId(todo.id);
        const result = await actions.changeStatus(todoTargetOf(todo), status);
        setChangingId(null);
        if (result.ok) setNotice(`「${todo.title}」のステータスを「${TODO_STATUS_LABELS[status]}」に変更しました。`);
    };

    const reloadAll = () => {
        actions.clearFailure();
        setNotice(null);
        list.reload();
    };

    return (
        <Stack spacing={3} data-testid="app-todo-list-page" data-scope={scope}>
            <PageHeader
                test_id="todo-list"
                title="ToDo"
                description="閲覧できる ToDo の一覧です。"
                actions={<Button component={RouterLink} to={appTodoCreatePath(tenant_code)} variant="contained" startIcon={<AddIcon />} data-testid="todo-list-create">ToDo を作成</Button>}
            />

            <Tabs
                value={scope}
                onChange={(_event, next: TodoScope) => changeFilter({ ...filter, scope: next })}
                aria-label="表示範囲"
                variant="scrollable"
                scrollButtons="auto"
                data-testid="todo-scope-tabs"
            >
                {SCOPE_TAB_ORDER.map((value) => <Tab key={value} value={value} label={TODO_SCOPE_LABELS[value]} id={`todo-scope-tab-${value}`} aria-controls={PANEL_ID} data-testid={`todo-scope-${value}`} />)}
            </Tabs>

            <Stack spacing={3} role="tabpanel" id={PANEL_ID} aria-labelledby={`todo-scope-tab-${scope}`}>
                <TodoFilterBar
                    filter={filter}
                    onChange={changeFilter}
                    assignees={assignee_choices.options}
                    organizations={organization_choices.options}
                    has_conditions={has_conditions}
                    onClear={() => changeFilter({ scope: filter.scope, sort: filter.sort })}
                />

                {notice && <Alert severity="success" role="status" onClose={() => setNotice(null)} data-testid="todo-list-notice">{notice}</Alert>}
                {actions.failure && <TodoErrorAlert error={actions.failure} test_id="todo-list-action-error" onReload={reloadAll} />}

                {list.status === 'loading' && <PageLoading />}
                {list.status === 'error' && list.error && <TodoErrorAlert error={list.error} test_id="todo-list-error" onReload={list.reload} always_retry />}
                {list.status === 'success' && (
                    list.items.length === 0 ? (
                        <Box data-testid="todo-list-empty" sx={{ py: 4, textAlign: 'center' }}>
                            <Typography variant="body1" color="text.secondary">
                                {has_conditions ? '条件に合う ToDo がありません。' : 'ToDo がありません。'}
                            </Typography>
                            {has_conditions && <Button onClick={() => changeFilter({ scope: filter.scope, sort: filter.sort })} sx={{ mt: 1 }} data-testid="todo-list-empty-clear">絞り込みをクリア</Button>}
                        </Box>
                    ) : (
                        <>
                            <TodoTable
                                tenant_code={tenant_code}
                                todos={list.items}
                                canChangeStatus={(todo) => canChangeStatusInList(todo, me.self_user_id, is_tenant_admin)}
                                onChangeStatus={(todo, status) => void changeStatus(todo, status)}
                                pending={actions.pending !== null && changing_id !== null}
                            />
                            <ListFooter
                                test_id="todo-list"
                                count={list.items.length}
                                has_more={list.has_more}
                                is_loading_more={list.is_loading_more}
                                load_more_error={list.load_more_error}
                                onLoadMore={list.loadMore}
                                onReload={list.reload}
                            />
                        </>
                    )
                )}
            </Stack>
        </Stack>
    );
};

export default AppTodoListPage;
