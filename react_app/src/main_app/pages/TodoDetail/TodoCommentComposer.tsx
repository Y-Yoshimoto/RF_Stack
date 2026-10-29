/**
 * @desc コメントの投稿欄 (複数行・残り文字数・Ctrl/Cmd + Enter で投稿。投稿後は入力を空にしてフォーカスを保つ)
 * 投稿の権限が無い (permissions.can_comment が false) ときは、入力欄を出さず理由を示す。
 */
import { useRef, useState, type FormEvent } from 'react';
import { Alert, Box, Button, CircularProgress } from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import { isValidCommentBody } from '@/main_app/todos/comment_changes';
import { TodoCommentBodyField } from './TodoCommentBodyField';

export type TodoCommentComposerProps = {
    can_comment: boolean;
    /** 投稿の実行中。 */
    pending: boolean;
    /** 投稿する (成功したら true)。 */
    onCreate: (body: string) => Promise<boolean>;
};

export const TodoCommentComposer = ({ can_comment, pending, onCreate }: TodoCommentComposerProps) => {
    const [body, setBody] = useState('');
    const input_ref = useRef<HTMLTextAreaElement | null>(null);
    const can_submit = !pending && isValidCommentBody(body);

    const submit = async (event?: FormEvent) => {
        event?.preventDefault();
        if (!can_submit) return;
        if (!(await onCreate(body))) return;
        setBody('');
        input_ref.current?.focus();
    };

    if (!can_comment) return <Alert severity="info" sx={{ mt: 2 }} data-testid="todo-comment-readonly">この ToDo にコメントを投稿する権限がありません。</Alert>;
    return (
        <Box component="form" noValidate onSubmit={(event: FormEvent) => void submit(event)} sx={{ mt: 2 }} data-testid="todo-comment-composer">
            <TodoCommentBodyField
                value={body}
                onChange={setBody}
                onSubmit={() => void submit()}
                label="コメントを書く"
                hint="Ctrl / ⌘ + Enter で投稿"
                read_only={pending}
                input_ref={input_ref}
                test_id="todo-comment-input"
            />
            <Button
                type="submit"
                variant="contained"
                disabled={!can_submit}
                startIcon={pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : <SendIcon />}
                sx={{ mt: 1 }}
                data-testid="todo-comment-submit"
            >
                {pending ? '投稿中…' : '投稿'}
            </Button>
        </Box>
    );
};

export default TodoCommentComposer;
