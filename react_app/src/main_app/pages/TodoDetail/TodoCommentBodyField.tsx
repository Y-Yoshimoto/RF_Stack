/**
 * @desc コメント本文の入力欄 (複数行・残り文字数・Ctrl/Cmd + Enter で確定・Esc で取り消し)
 * 投稿の入力と、編集の入力で共有する。日本語入力の変換中の Enter は無視する。
 * 実行中は readOnly にする (disabled にするとフォーカスが外れるため)。
 */
import type { KeyboardEvent, Ref } from 'react';
import { TextField } from '@mui/material';
import { TODO_LIMITS } from '@/main_app/api/contract';

export type TodoCommentBodyFieldProps = {
    value: string;
    onChange: (value: string) => void;
    /** Ctrl/Cmd + Enter。 */
    onSubmit: () => void;
    /** Esc (省略時は何もしない)。 */
    onCancel?: () => void;
    label: string;
    /** 残り文字数に添える操作の案内。 */
    hint: string;
    read_only?: boolean;
    min_rows?: number;
    input_ref?: Ref<HTMLTextAreaElement>;
    test_id: string;
};

/**
 * 残り文字数の案内を作る関数
 * @param {number} length 入力の文字数
 * @returns {string} 案内
*/
export const commentCounterTextOf = (length: number): string => {
    const rest = TODO_LIMITS.COMMENT_BODY_MAX - length;
    return rest < 0 ? `${(-rest).toLocaleString('ja-JP')} 文字超えています (最大 ${TODO_LIMITS.COMMENT_BODY_MAX.toLocaleString('ja-JP')} 文字)` : `残り ${rest.toLocaleString('ja-JP')} 文字`;
};

export const TodoCommentBodyField = ({ value, onChange, onSubmit, onCancel, label, hint, read_only = false, min_rows = 3, input_ref, test_id }: TodoCommentBodyFieldProps) => {
    const over = value.length > TODO_LIMITS.COMMENT_BODY_MAX;
    const onKeyDown = (event: KeyboardEvent) => {
        if (event.nativeEvent.isComposing) return;
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            onSubmit();
        } else if (event.key === 'Escape' && onCancel) {
            event.stopPropagation();
            onCancel();
        }
    };
    return (
        <TextField
            label={label}
            fullWidth
            multiline
            minRows={min_rows}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={onKeyDown}
            error={over}
            helperText={`${commentCounterTextOf(value.length)} ・ ${hint}`}
            inputRef={input_ref}
            slotProps={{ htmlInput: { 'data-testid': test_id, readOnly: read_only } }}
        />
    );
};

export default TodoCommentBodyField;
