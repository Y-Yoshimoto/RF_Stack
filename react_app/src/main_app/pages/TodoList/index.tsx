/**
 * @desc ToDo 一覧 (`/{tenant_code}/todos`。tenant_admin / member のどちらも可)
 * 表示範囲 (すべて / 自分が作成 / 自分が担当 / 共有された) のタブ、リスト／ボードの切り替え、折りたたみ式の絞り込み (ステータス・優先度・担当者・公開先組織・期限・タイトル検索・並び替え)、
 * 適用中の条件のチップ、無限スクロールと総件数を持つ。表示範囲・絞り込み・表示方法はすべて URL のクエリ (`?scope=mine&status=open&view=board`) に持たせる。
 * - リスト表示 (TodoListContent): md 以上は表、md 未満はカード
 * - ボード表示 (TodoBoard/): ステータスを列にしたカンバン。ステータスの絞り込みは使わない (URL には残し、リストに戻すと復元する)
 *
 * 一覧・ボードからのステータス変更: 一覧 API の要素は permissions を持たないため、詳細を開いての判定はせず、サーバーの権限表と同じ条件
 * (tenant_admin・作成者・担当者) を操作者の ID とロールで先に判定し、該当する行・カードだけ操作を出す (list_rules.ts)。ボードでは自分の ID の取得前は全カードを掴めない。
 * 判定が古い場合は API が 403 / 412 を返し、再読み込みを促す。
 * 使うフック: useTodoList / useTodoActions (TodoListContent)、useTodoBoard (TodoBoard)、useMe (自分の ID)、useTodoAssigneeChoices / useTodoOrganizationChoices (絞り込みの選択肢)。
 */
import { useMemo, useState } from 'react';
import { Link as RouterLink, useLocation, useSearchParams } from 'react-router-dom';
import { Alert, Button, Stack, Tab, Tabs, ToggleButton, ToggleButtonGroup } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ViewKanbanOutlinedIcon from '@mui/icons-material/ViewKanbanOutlined';
import ViewListIcon from '@mui/icons-material/ViewList';
import { type TodoRead, type TodoScope } from '@/main_app/api/contract';
import type { TodoListFilter } from '@/main_app/api/todos';
import { useAppPermissions, useAppSession } from '@/main_app/auth/useAppAuth';
import { PageHeader } from '@/main_app/components/PageHeader';
import { useMe } from '@/main_app/me/useMe';
import { TODO_SCOPE_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';
import { appTodoCreatePath } from '@/main_app/paths';
import { parseTodoListSearch, parseTodoListView, toTodoListSearch, withTodoListView, type TodoListView } from '@/main_app/todos/list_search';
import { useTodoAssigneeChoices, useTodoOrganizationChoices } from '@/main_app/todos/useTodoChoices';
import { withoutStatusOf } from './filter_chips';
import { canChangeStatusInList, hasListConditions } from './list_rules';
import { TodoBoard } from './TodoBoard/TodoBoard';
import { TodoEmptyState } from './TodoEmptyState';
import { TodoFilterBar } from './TodoFilterBar';
import { TodoListContent } from './TodoListContent';

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
    const view = parseTodoListView(search_params);
    const scope: TodoScope = filter.scope ?? 'all';
    // ボードはステータスが列になるため、ステータスの絞り込みを使わない (URL には残す)
    const view_filter = useMemo(() => (view === 'board' ? withoutStatusOf(filter) : filter), [filter, view]);
    const me = useMe();
    const assignee_choices = useTodoAssigneeChoices();
    const organization_choices = useTodoOrganizationChoices();
    const [notice, setNotice] = useState<string | null>(noticeOf(location.state));
    const has_conditions = hasListConditions(view_filter);

    const changeFilter = (next: TodoListFilter) => setSearchParams(toTodoListSearch(next, search_params), { replace: true });
    const clearFilter = () => changeFilter({ scope: filter.scope, sort: filter.sort });
    const changeView = (next: TodoListView) => setSearchParams(withTodoListView(next, search_params), { replace: true });

    const canChangeInList = (todo: TodoRead): boolean => canChangeStatusInList(todo, me.self_user_id, is_tenant_admin);
    // ボードは自分の ID を取得するまで、権限を確かめられないため全カードを掴めない
    const canChangeInBoard = (todo: TodoRead): boolean => me.status === 'success' && canChangeInList(todo);
    const empty_state = <TodoEmptyState scope={scope} has_conditions={has_conditions} onClear={clearFilter} create_to={appTodoCreatePath(tenant_code)} />;

    return (
        <Stack spacing={3} data-testid="app-todo-list-page" data-scope={scope} data-view={view}>
            <PageHeader
                test_id="todo-list"
                title="ToDo"
                description="閲覧できる ToDo の一覧です。"
                actions={<Button component={RouterLink} to={appTodoCreatePath(tenant_code)} variant="contained" startIcon={<AddIcon />} data-testid="todo-list-create">ToDo を作成</Button>}
            />

            <Stack direction="row" spacing={2} useFlexGap sx={{ alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
                <Tabs
                    value={scope}
                    onChange={(_event, next: TodoScope) => changeFilter({ ...filter, scope: next })}
                    aria-label="表示範囲"
                    variant="scrollable"
                    scrollButtons="auto"
                    sx={{ minWidth: 0, flex: '1 1 auto' }}
                    data-testid="todo-scope-tabs"
                >
                    {SCOPE_TAB_ORDER.map((value) => <Tab key={value} value={value} label={TODO_SCOPE_LABELS[value]} id={`todo-scope-tab-${value}`} aria-controls={PANEL_ID} data-testid={`todo-scope-${value}`} />)}
                </Tabs>
                <ToggleButtonGroup
                    size="small"
                    exclusive
                    value={view}
                    onChange={(_event, next: TodoListView | null) => next !== null && changeView(next)}
                    aria-label="表示方法"
                    data-testid="todo-view-toggle"
                >
                    <ToggleButton value="list" sx={{ gap: 0.5 }} data-testid="todo-view-list"><ViewListIcon fontSize="small" aria-hidden />リスト</ToggleButton>
                    <ToggleButton value="board" sx={{ gap: 0.5 }} data-testid="todo-view-board"><ViewKanbanOutlinedIcon fontSize="small" aria-hidden />ボード</ToggleButton>
                </ToggleButtonGroup>
            </Stack>

            <Stack spacing={3} role="tabpanel" id={PANEL_ID} aria-labelledby={`todo-scope-tab-${scope}`}>
                <TodoFilterBar
                    filter={filter}
                    view={view}
                    onChange={changeFilter}
                    assignees={assignee_choices.options}
                    organizations={organization_choices.options}
                    onClear={clearFilter}
                />

                {notice && <Alert severity="success" role="status" onClose={() => setNotice(null)} data-testid="todo-list-notice">{notice}</Alert>}

                {view === 'board' ? (
                    <TodoBoard filter={view_filter} tenant_code={tenant_code} canChangeStatus={canChangeInBoard} empty_state={empty_state} onNotice={setNotice} />
                ) : (
                    <TodoListContent filter={view_filter} tenant_code={tenant_code} canChangeStatus={canChangeInList} empty_state={empty_state} onNotice={setNotice} />
                )}
            </Stack>
        </Stack>
    );
};

export default AppTodoListPage;
