/**
 * @desc ToDo 一覧の絞り込み・検索・並び替え (状態は URL のクエリに持たせるため、変更は onChange で親に渡す)
 * 検索はタイトルの部分一致で、Enter または「検索」で確定する。それ以外は変更するとすぐに反映する。
 */
import { useState, type FormEvent } from 'react';
import { Box, Button, MenuItem, Paper, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import { TODO_LIMITS, TODO_PRIORITIES, TODO_SORT_KEYS, TODO_STATUSES, type TodoPriority, type TodoSortKey, type TodoStatus } from '@/main_app/api/contract';
import type { TodoListFilter } from '@/main_app/api/todos';
import { TODO_STATUS_ICONS } from '@/main_app/pages/TodoCommon/TodoBadges';
import { TODO_PRIORITY_LABELS, TODO_SORT_LABELS, TODO_STATUS_LABELS } from '@/main_app/pages/TodoCommon/todo_labels';
import type { TodoAssigneeOption, TodoOrganizationOption } from '@/main_app/todos/useTodoChoices';

export type TodoFilterBarProps = {
    filter: TodoListFilter;
    onChange: (filter: TodoListFilter) => void;
    assignees: readonly TodoAssigneeOption[];
    organizations: readonly TodoOrganizationOption[];
    /** 絞り込み (表示範囲と並び順を除く) が指定されている。 */
    has_conditions: boolean;
    onClear: () => void;
};

const SELECT_SLOT_PROPS = { select: { displayEmpty: true }, inputLabel: { shrink: true } } as const;

type ChoiceFilterProps = {
    label: string;
    value: string;
    choices: readonly { id: string; label: string }[];
    /** URL に載った ID が選択肢に無い場合の表示。 */
    unknown_label: string;
    onChange: (id: string) => void;
    test_id: string;
};

/** 「指定なし」を持つ絞り込みのセレクト (URL に載った ID が選択肢に無くても値を保つ) */
const ChoiceFilter = ({ label, value, choices, unknown_label, onChange, test_id }: ChoiceFilterProps) => (
    <TextField select size="small" label={label} value={value} onChange={(event) => onChange(event.target.value)} slotProps={SELECT_SLOT_PROPS} sx={{ minWidth: 180 }} data-testid={test_id}>
        <MenuItem value="">指定なし</MenuItem>
        {value !== '' && !choices.some((choice) => choice.id === value) && <MenuItem value={value}>{unknown_label}</MenuItem>}
        {choices.map((choice) => <MenuItem key={choice.id} value={choice.id} data-testid={`${test_id}-${choice.id}`}>{choice.label}</MenuItem>)}
    </TextField>
);

export const TodoFilterBar = ({ filter, onChange, assignees, organizations, has_conditions, onClear }: TodoFilterBarProps) => {
    // 検索語は確定するまで入力中の値を持つ。URL の値が変わったら (クリアなど) 入力欄も合わせる
    const [draft, setDraft] = useState(filter.q ?? '');
    const [synced_q, setSyncedQ] = useState(filter.q ?? '');
    if ((filter.q ?? '') !== synced_q) {
        setSyncedQ(filter.q ?? '');
        setDraft(filter.q ?? '');
    }
    const set = (patch: Partial<TodoListFilter>) => onChange({ ...filter, ...patch });
    const submitSearch = (event: FormEvent) => {
        event.preventDefault();
        set({ q: draft });
    };
    return (
        <Paper variant="outlined" component="section" aria-label="絞り込みと並び替え" sx={{ p: 2 }} data-testid="todo-filter">
            <Stack spacing={2}>
                <Box component="form" role="search" aria-label="ToDo の検索" onSubmit={submitSearch} sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }} data-testid="todo-search-form">
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
                </Box>

                <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
                    <Box component="fieldset" sx={{ border: 0, p: 0, m: 0 }} data-testid="todo-filter-status">
                        <Typography variant="caption" component="legend" color="text.secondary">ステータス</Typography>
                        <ToggleButtonGroup
                            size="small"
                            aria-label="ステータスで絞り込み"
                            value={[...(filter.status ?? [])]}
                            onChange={(_event, next: TodoStatus[]) => set({ status: next })}
                        >
                            {TODO_STATUSES.map((status) => (
                                <ToggleButton key={status} value={status} sx={{ gap: 0.5 }} data-testid={`todo-filter-status-${status}`}>
                                    {TODO_STATUS_ICONS[status]}{TODO_STATUS_LABELS[status]}
                                </ToggleButton>
                            ))}
                        </ToggleButtonGroup>
                    </Box>
                    <Box component="fieldset" sx={{ border: 0, p: 0, m: 0 }} data-testid="todo-filter-priority">
                        <Typography variant="caption" component="legend" color="text.secondary">優先度</Typography>
                        <ToggleButtonGroup
                            size="small"
                            aria-label="優先度で絞り込み"
                            value={[...(filter.priority ?? [])]}
                            onChange={(_event, next: TodoPriority[]) => set({ priority: next })}
                        >
                            {TODO_PRIORITIES.map((priority) => (
                                <ToggleButton key={priority} value={priority} data-testid={`todo-filter-priority-${priority}`}>{`優先度 ${TODO_PRIORITY_LABELS[priority]}`}</ToggleButton>
                            ))}
                        </ToggleButtonGroup>
                    </Box>
                </Stack>

                <Stack direction="row" spacing={2} useFlexGap sx={{ flexWrap: 'wrap' }}>
                    <ChoiceFilter
                        label="担当者"
                        value={filter.assignee_id ?? ''}
                        choices={assignees.map((option) => ({ id: option.user_id, label: option.is_active ? option.display_name : `${option.display_name} (無効)` }))}
                        unknown_label="(不明なユーザー)"
                        onChange={(assignee_id) => set({ assignee_id })}
                        test_id="todo-filter-assignee"
                    />
                    <ChoiceFilter
                        label="公開先の組織"
                        value={filter.organization_id ?? ''}
                        choices={organizations.map((option) => ({ id: option.organization_id, label: option.name }))}
                        unknown_label="(不明な組織)"
                        onChange={(organization_id) => set({ organization_id })}
                        test_id="todo-filter-organization"
                    />
                    <TextField
                        type="date"
                        size="small"
                        label="期限 (この日以降)"
                        value={filter.due_after ?? ''}
                        onChange={(event) => set({ due_after: event.target.value })}
                        slotProps={{ inputLabel: { shrink: true }, htmlInput: { 'data-testid': 'todo-filter-due-after' } }}
                    />
                    <TextField
                        type="date"
                        size="small"
                        label="期限 (この日以前)"
                        value={filter.due_before ?? ''}
                        onChange={(event) => set({ due_before: event.target.value })}
                        slotProps={{ inputLabel: { shrink: true }, htmlInput: { 'data-testid': 'todo-filter-due-before' } }}
                    />
                    <TextField
                        select
                        size="small"
                        label="並び替え"
                        value={filter.sort ?? '-created_at'}
                        onChange={(event) => set({ sort: event.target.value as TodoSortKey })}
                        sx={{ minWidth: 240 }}
                        data-testid="todo-sort"
                    >
                        {TODO_SORT_KEYS.map((key) => <MenuItem key={key} value={key} data-testid={`todo-sort-${key}`}>{TODO_SORT_LABELS[key]}</MenuItem>)}
                    </TextField>
                    {has_conditions && <Button onClick={onClear} data-testid="todo-filter-clear">絞り込みをクリア</Button>}
                </Stack>
            </Stack>
        </Paper>
    );
};

export default TodoFilterBar;
