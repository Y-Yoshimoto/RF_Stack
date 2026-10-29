/**
 * @desc コメント 1 件 (投稿者・日時・「編集済み」・本文。自分のコメントは編集・削除、tenant_admin は他人のコメントの削除だけ)
 * 操作の可否はコメントごとの permissions (can_edit / can_delete) で決める。無効化されたユーザーの投稿者は「(無効)」と表示する。
 */
import { useEffect, useRef, useState } from 'react';
import { Box, Button, Chip, Stack, Typography } from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import type { TodoCommentRead } from '@/main_app/api/contract';
import { formatDateTime } from '@/main_app/components/format';
import { isValidCommentBody } from '@/main_app/todos/comment_changes';
import { TodoCommentBodyField } from './TodoCommentBodyField';
import { todoUserTextOf } from './todo_user_text';

export type TodoCommentItemProps = {
    comment: TodoCommentRead;
    /** 編集の保存の実行中 (このコメント)。 */
    saving: boolean;
    /** 編集の保存 (成功したら true)。 */
    onUpdate: (comment: TodoCommentRead, body: string) => Promise<boolean>;
    /** 削除の確認を開く。 */
    onRequestDelete: (comment: TodoCommentRead) => void;
};

export const TodoCommentItem = ({ comment, saving, onUpdate, onRequestDelete }: TodoCommentItemProps) => {
    const [editing, setEditing] = useState(false);
    const [body, setBody] = useState(comment.body);
    const edit_button_ref = useRef<HTMLButtonElement | null>(null);
    const input_ref = useRef<HTMLTextAreaElement | null>(null);
    const restore_focus = useRef(false);
    const { permissions } = comment;
    const can_save = !saving && isValidCommentBody(body) && body !== comment.body;

    useEffect(() => {
        if (editing) {
            input_ref.current?.focus();
        } else if (restore_focus.current) {
            restore_focus.current = false;
            edit_button_ref.current?.focus();
        }
    }, [editing]);

    const startEdit = () => {
        setBody(comment.body);
        setEditing(true);
    };

    const closeEdit = () => {
        restore_focus.current = true;
        setEditing(false);
    };

    const save = async () => {
        if (!can_save) return;
        if (await onUpdate(comment, body)) closeEdit();
    };

    return (
        <Box component="li" sx={{ py: 1.5, borderBottom: 1, borderColor: 'divider' }} data-testid={`todo-comment-${comment.id}`} data-edited={comment.edited_at !== null}>
            <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
                <Typography variant="subtitle2" component="span" sx={{ minWidth: 0, maxWidth: '100%', overflowWrap: 'anywhere' }} data-testid={`todo-comment-${comment.id}-author`}>{todoUserTextOf(comment.author)}</Typography>
                <Typography variant="body2" color="text.secondary" component="span">
                    <time dateTime={comment.created_at} data-testid={`todo-comment-${comment.id}-time`}>{formatDateTime(comment.created_at)}</time>
                </Typography>
                {comment.edited_at !== null && <Chip size="small" variant="outlined" label="編集済み" title={`${formatDateTime(comment.edited_at)} に編集`} data-testid={`todo-comment-${comment.id}-edited`} />}
                <Box sx={{ flex: 1 }} />
                {!editing && permissions.can_edit && (
                    <Button ref={edit_button_ref} size="small" startIcon={<EditIcon />} onClick={startEdit} aria-label={`${todoUserTextOf(comment.author)}のコメントを編集`} data-testid={`todo-comment-${comment.id}-edit`}>編集</Button>
                )}
                {!editing && permissions.can_delete && (
                    <Button size="small" color="error" startIcon={<DeleteIcon />} onClick={() => onRequestDelete(comment)} aria-label={`${todoUserTextOf(comment.author)}のコメントを削除`} data-testid={`todo-comment-${comment.id}-delete`}>削除</Button>
                )}
            </Stack>
            {editing ? (
                <Box sx={{ mt: 1 }}>
                    <TodoCommentBodyField value={body} onChange={setBody} onSubmit={() => void save()} onCancel={closeEdit} label="コメントを編集" hint="Ctrl / ⌘ + Enter で保存、Esc で取り消し" read_only={saving} input_ref={input_ref} test_id={`todo-comment-${comment.id}-input`} />
                    <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
                        <Button variant="contained" size="small" disabled={!can_save} onClick={() => void save()} data-testid={`todo-comment-${comment.id}-save`}>{saving ? '保存中…' : '保存'}</Button>
                        <Button size="small" onClick={closeEdit} data-testid={`todo-comment-${comment.id}-cancel`}>キャンセル</Button>
                    </Stack>
                </Box>
            ) : (
                <Typography variant="body1" sx={{ mt: 0.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }} data-testid={`todo-comment-${comment.id}-body`}>{comment.body}</Typography>
            )}
        </Box>
    );
};

export default TodoCommentItem;
