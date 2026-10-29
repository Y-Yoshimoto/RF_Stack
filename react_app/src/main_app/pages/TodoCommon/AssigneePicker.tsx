/**
 * @desc 担当者の選択 (複数選択。最大 20 人: AP-ASN-01)
 * 上限に達すると、未選択のユーザーは選べなくなる。無効化されたユーザーは「無効」と表示し、既に割り当て済みのものだけが残る (外せる: AP-ASN-04)。
 */
import { Autocomplete, Chip, CircularProgress, FormHelperText, TextField } from '@mui/material';
import { TODO_LIMITS } from '@/main_app/api/contract';
import type { TodoAssigneeOption } from '@/main_app/todos/useTodoChoices';

export type AssigneePickerProps = {
    options: readonly TodoAssigneeOption[];
    /** 選択中のユーザー ID。 */
    value: readonly string[];
    onChange: (user_ids: string[]) => void;
    /** 選択肢の読み込み中。 */
    loading?: boolean;
    disabled?: boolean;
    label?: string;
    /** data-testid の接頭辞。 */
    test_id: string;
};

/**
 * 選択肢の表示名を返す関数 (無効なユーザーは「無効」を付ける)
 * @param {TodoAssigneeOption} option 選択肢
 * @returns {string} 表示名
*/
export const assigneeLabelOf = (option: TodoAssigneeOption): string => (option.is_active ? option.display_name : `${option.display_name} (無効)`);

export const AssigneePicker = ({ options, value, onChange, loading = false, disabled = false, label = '担当者', test_id }: AssigneePickerProps) => {
    const selected = options.filter((option) => value.includes(option.user_id));
    const at_limit = value.length >= TODO_LIMITS.ASSIGNEES_MAX;
    const help_id = `${test_id}-help`;
    return (
        <div data-testid={test_id}>
            <Autocomplete
                multiple
                disableCloseOnSelect
                size="small"
                options={[...options]}
                value={selected}
                loading={loading}
                disabled={disabled}
                loadingText="読み込み中…"
                noOptionsText="該当するユーザーがいません"
                getOptionLabel={assigneeLabelOf}
                isOptionEqualToValue={(a, b) => a.user_id === b.user_id}
                getOptionDisabled={(option) => at_limit && !value.includes(option.user_id)}
                onChange={(_event, next) => onChange(next.map((option) => option.user_id))}
                renderValue={(items, getItemProps) => items.map((item, index) => {
                    const { key, ...props } = getItemProps({ index });
                    return <Chip key={key} size="small" variant={item.is_active ? 'filled' : 'outlined'} label={assigneeLabelOf(item)} {...props} data-testid={`${test_id}-chip-${item.user_id}`} />;
                })}
                renderInput={(params) => (
                    <TextField
                        {...params}
                        label={label}
                        slotProps={{
                            ...params.slotProps,
                            htmlInput: { ...params.slotProps.htmlInput, 'data-testid': `${test_id}-input`, 'aria-describedby': help_id },
                            input: { ...params.slotProps.input, endAdornment: <>{loading ? <CircularProgress size={16} aria-hidden /> : null}{params.slotProps.input.endAdornment}</> },
                        }}
                    />
                )}
            />
            <FormHelperText id={help_id} role="status" data-testid={`${test_id}-count`} data-at-limit={at_limit} error={at_limit} sx={{ mx: 1.75 }}>
                {at_limit
                    ? `担当者は最大 ${TODO_LIMITS.ASSIGNEES_MAX} 人です。上限に達しているため、これ以上は追加できません (${value.length} / ${TODO_LIMITS.ASSIGNEES_MAX})。`
                    : `選択中 ${value.length} / ${TODO_LIMITS.ASSIGNEES_MAX} 人`}
            </FormHelperText>
        </div>
    );
};

export default AssigneePicker;
