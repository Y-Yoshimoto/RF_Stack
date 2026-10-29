/**
 * @desc チェックリスト項目の名前のその場編集 (Enter で保存・Esc で取り消し。日本語入力の変換中の Enter は無視する)
 */
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { IconButton, Stack, TextField } from '@mui/material';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import { TODO_LIMITS } from '@/main_app/api/contract';
import { isValidChecklistTitle } from '@/main_app/todos/checklist_changes';

export type TodoChecklistItemEditorProps = {
    item_id: string;
    /** 編集前の項目名。 */
    title: string;
    /** 保存の実行中。 */
    pending: boolean;
    /** 保存する (項目名が変わっていなければ呼ばない)。成功したら true。 */
    onSave: (title: string) => Promise<boolean>;
    /** 編集をやめる (取り消し・保存の成功)。 */
    onClose: () => void;
};

export const TodoChecklistItemEditor = ({ item_id, title, pending, onSave, onClose }: TodoChecklistItemEditorProps) => {
    const [value, setValue] = useState(title);
    const input_ref = useRef<HTMLInputElement | null>(null);
    const too_long = value.trim().length > TODO_LIMITS.CHECKLIST_ITEM_TITLE_MAX;
    const can_save = isValidChecklistTitle(value) && !pending;

    useEffect(() => {
        input_ref.current?.focus();
        input_ref.current?.select();
    }, []);

    const save = async () => {
        if (!can_save) return;
        if (value.trim() === title) {
            onClose();
            return;
        }
        if (await onSave(value)) onClose();
    };

    const onKeyDown = (event: KeyboardEvent) => {
        if (event.nativeEvent.isComposing) return;
        if (event.key === 'Enter') {
            event.preventDefault();
            void save();
        } else if (event.key === 'Escape') {
            event.stopPropagation();
            onClose();
        }
    };

    return (
        <Stack direction="row" spacing={0.5} sx={{ alignItems: 'flex-start', flex: 1, minWidth: 0 }}>
            <TextField
                size="small"
                fullWidth
                value={value}
                onChange={(event) => setValue(event.target.value)}
                onKeyDown={onKeyDown}
                error={too_long || value.trim() === ''}
                helperText={too_long ? `項目名は ${TODO_LIMITS.CHECKLIST_ITEM_TITLE_MAX} 文字以内で入力してください。` : 'Enter で保存、Esc で取り消し'}
                inputRef={input_ref}
                slotProps={{ htmlInput: { 'aria-label': `「${title}」の新しい名前`, 'data-testid': `todo-checklist-item-${item_id}-rename-input`, autoComplete: 'off', readOnly: pending } }}
            />
            <IconButton size="small" color="primary" aria-label="名前の変更を保存" disabled={!can_save} onClick={() => void save()} data-testid={`todo-checklist-item-${item_id}-rename-save`}><CheckIcon fontSize="small" /></IconButton>
            <IconButton size="small" aria-label="名前の変更を取り消す" onClick={onClose} data-testid={`todo-checklist-item-${item_id}-rename-cancel`}><CloseIcon fontSize="small" /></IconButton>
        </Stack>
    );
};

export default TodoChecklistItemEditor;
