/**
 * @desc チェックリストの末尾の追加欄 (Enter で追加し、続けて入力できるようフォーカスを保つ。項目が上限に達したら無効にする)
 * 追加の実行中は入力欄を readOnly にする (disabled にするとフォーカスが外れるため)。
 */
import { useRef, useState, type FormEvent } from 'react';
import { Box, Button, TextField } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { TODO_LIMITS } from '@/main_app/api/contract';
import { isValidChecklistTitle } from '@/main_app/todos/checklist_changes';

export type TodoChecklistAddFormProps = {
    /** 項目が上限に達している。 */
    is_full: boolean;
    /** 追加の実行中。 */
    pending: boolean;
    /** 追加する (成功したら true)。 */
    onAdd: (title: string) => Promise<boolean>;
};

export const TodoChecklistAddForm = ({ is_full, pending, onAdd }: TodoChecklistAddFormProps) => {
    const [title, setTitle] = useState('');
    const input_ref = useRef<HTMLInputElement | null>(null);
    const length = title.trim().length;
    const too_long = length > TODO_LIMITS.CHECKLIST_ITEM_TITLE_MAX;
    const can_submit = !is_full && !pending && isValidChecklistTitle(title);

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        if (!can_submit) return;
        const ok = await onAdd(title);
        if (!ok) return;
        setTitle('');
        input_ref.current?.focus();
    };

    const helper = is_full
        ? `項目は最大 ${TODO_LIMITS.CHECKLIST_ITEMS_MAX} 件までです。追加するには、不要な項目を削除してください。`
        : too_long ? `項目名は ${TODO_LIMITS.CHECKLIST_ITEM_TITLE_MAX} 文字以内で入力してください。` : `Enter で追加 (${length} / ${TODO_LIMITS.CHECKLIST_ITEM_TITLE_MAX} 文字)`;

    return (
        <Box component="form" noValidate onSubmit={(event: FormEvent) => void submit(event)} sx={{ display: 'flex', gap: 1, alignItems: 'flex-start', mt: 2 }} data-testid="todo-checklist-add-form">
            <TextField
                size="small"
                fullWidth
                label="項目を追加"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                disabled={is_full}
                error={too_long}
                helperText={helper}
                inputRef={input_ref}
                slotProps={{ htmlInput: { 'data-testid': 'todo-checklist-add-input', autoComplete: 'off', readOnly: pending } }}
            />
            <Button type="submit" variant="outlined" startIcon={<AddIcon />} disabled={!can_submit} sx={{ flexShrink: 0, mt: '1px', height: 40 }} data-testid="todo-checklist-add-submit">追加</Button>
        </Box>
    );
};

export default TodoChecklistAddForm;
