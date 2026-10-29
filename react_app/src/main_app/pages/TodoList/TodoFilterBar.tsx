/**
 * @desc ToDo 一覧の絞り込み・検索・並び替え (状態は URL のクエリに持たせるため、変更は onChange で親に渡す)
 * 常に出すのは、検索欄と「絞り込み」ボタン (適用数のバッジ付き) だけ。ステータス・優先度・担当者・公開先・期限・並び替えは Collapse に畳む (TodoFilterPanel。AP-UX-05)。
 * 適用中の条件は TodoActiveFilterChips で常に出し、個別に外せる。ボード表示ではステータスの絞り込みを隠す (列がステータス。AP-BRD-02)。
 * 検索はタイトルの部分一致で、Enter または「検索」で確定する。それ以外は変更するとすぐに反映する。
 */
import { useId, useState, type FormEvent } from 'react';
import { Badge, Box, Button, Collapse, Paper, TextField } from '@mui/material';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FilterListIcon from '@mui/icons-material/FilterList';
import SearchIcon from '@mui/icons-material/Search';
import { TODO_LIMITS } from '@/main_app/api/contract';
import type { TodoListFilter } from '@/main_app/api/todos';
import type { TodoListView } from '@/main_app/todos/list_search';
import type { TodoAssigneeOption, TodoOrganizationOption } from '@/main_app/todos/useTodoChoices';
import { activeFilterChipsOf, filterCountOf } from './filter_chips';
import { TodoActiveFilterChips } from './TodoActiveFilterChips';
import { TodoFilterPanel } from './TodoFilterPanel';

export type TodoFilterBarProps = {
    filter: TodoListFilter;
    /** 表示方法 (board ではステータスの絞り込みを隠す)。 */
    view: TodoListView;
    onChange: (filter: TodoListFilter) => void;
    assignees: readonly TodoAssigneeOption[];
    organizations: readonly TodoOrganizationOption[];
    /** すべての条件 (検索語を含む) を外す。 */
    onClear: () => void;
};

export const TodoFilterBar = ({ filter, view, onChange, assignees, organizations, onClear }: TodoFilterBarProps) => {
    const panel_id = useId();
    const [expanded, setExpanded] = useState(false);
    const chips = activeFilterChipsOf(filter, view, {
        assigneeNameOf: (id) => assignees.find((option) => option.user_id === id)?.display_name,
        organizationNameOf: (id) => organizations.find((option) => option.organization_id === id)?.name,
    });
    const applied_count = filterCountOf(chips);
    // 検索語は確定するまで入力中の値を持つ。URL の値が変わったら (クリアなど) 入力欄も合わせる
    const [draft, setDraft] = useState(filter.q ?? '');
    const [synced_q, setSyncedQ] = useState(filter.q ?? '');
    if ((filter.q ?? '') !== synced_q) {
        setSyncedQ(filter.q ?? '');
        setDraft(filter.q ?? '');
    }
    const submitSearch = (event: FormEvent) => {
        event.preventDefault();
        onChange({ ...filter, q: draft });
    };
    return (
        <Paper variant="outlined" component="section" aria-label="絞り込みと並び替え" sx={{ p: 2 }} data-testid="todo-filter">
            <Box>
                <Box component="form" role="search" aria-label="ToDo の検索" onSubmit={submitSearch} sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }} data-testid="todo-search-form">
                    <TextField
                        type="search"
                        size="small"
                        label="タイトルを検索"
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                        sx={{ flex: '1 1 240px' }}
                        slotProps={{ htmlInput: { maxLength: TODO_LIMITS.QUERY_MAX, 'data-testid': 'todo-search-input' } }}
                    />
                    <Button type="submit" variant="outlined" startIcon={<SearchIcon />} data-testid="todo-search-submit">検索</Button>
                    <Badge badgeContent={applied_count} color="primary" data-testid="todo-filter-badge" slotProps={{ badge: { 'aria-hidden': true } }}>
                        <Button
                            variant={expanded ? 'contained' : 'outlined'}
                            startIcon={<FilterListIcon />}
                            endIcon={expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                            aria-expanded={expanded}
                            aria-controls={panel_id}
                            aria-label={applied_count > 0 ? `絞り込み (${applied_count} 件の条件を適用中)` : '絞り込み'}
                            onClick={() => setExpanded((value) => !value)}
                            data-testid="todo-filter-toggle"
                        >
                            絞り込み
                        </Button>
                    </Badge>
                </Box>

                {chips.length > 0 && <Box sx={{ mt: 2 }}><TodoActiveFilterChips chips={chips} onChange={onChange} onClear={onClear} /></Box>}

                <Collapse in={expanded} id={panel_id} data-testid="todo-filter-panel">
                    <TodoFilterPanel filter={filter} view={view} onChange={onChange} assignees={assignees} organizations={organizations} />
                </Collapse>
            </Box>
        </Paper>
    );
};

export default TodoFilterBar;
