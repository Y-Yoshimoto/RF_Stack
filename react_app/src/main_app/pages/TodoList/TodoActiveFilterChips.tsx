/**
 * @desc ToDo 一覧の上に出す、適用中の絞り込み条件 (AP-UX-05)
 * 条件ごとのチップで、個別に外せる (チップを押す・Delete キーで外す)。条件が無ければ何も出さない。
 */
import { Button, Chip, Stack } from '@mui/material';
import type { TodoListFilter } from '@/main_app/api/todos';
import type { TodoFilterChip } from './filter_chips';

export type TodoActiveFilterChipsProps = {
    chips: readonly TodoFilterChip[];
    /** 1 つの条件を外した絞り込みを適用する。 */
    onChange: (filter: TodoListFilter) => void;
    /** すべての条件を外す。 */
    onClear: () => void;
};

export const TodoActiveFilterChips = ({ chips, onChange, onClear }: TodoActiveFilterChipsProps) => {
    if (chips.length === 0) return null;
    return (
        <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap' }} data-testid="todo-active-filters">
            <Stack component="ul" aria-label="適用中の条件" direction="row" spacing={1} useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap', listStyle: 'none', m: 0, p: 0 }}>
                {chips.map((chip) => (
                    <li key={chip.id}>
                        <Chip
                            size="small"
                            variant="outlined"
                            label={chip.label}
                            onClick={() => onChange(chip.without)}
                            onDelete={() => onChange(chip.without)}
                            aria-label={`${chip.label} (条件を外す)`}
                            data-testid={`todo-chip-${chip.id}`}
                        />
                    </li>
                ))}
            </Stack>
            <Button size="small" onClick={onClear} data-testid="todo-filter-clear">絞り込みをクリア</Button>
        </Stack>
    );
};

export default TodoActiveFilterChips;
