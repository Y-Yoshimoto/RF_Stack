/**
 * @desc ToDo のコメント (古い順の一覧・投稿・編集・削除。AP-CMT)
 * - 投稿は ToDo の permissions.can_comment、編集・削除はコメントごとの permissions で出し分ける。削除は確認ダイアログを経由する
 * - 投稿したコメントは末尾に加わる。続きのページがあるときは「さらに読み込む」で読み込む
 * - コメントの変更に成功したら onChanged で通知する (タブの件数の更新に使う。ToDo の comment_count は自動では変わらないため)
 * - 失敗は role="alert" で読み上げる。412 / 404 (他の人が編集・削除した) では「再読み込み」を出す
 */
import { useState } from 'react';
import { Box } from '@mui/material';
import type { TodoCommentRead } from '@/main_app/api/contract';
import { ConfirmDialog } from '@/main_app/components/ConfirmDialog';
import { TodoErrorAlert } from '@/main_app/pages/TodoCommon/TodoErrorAlert';
import { useTodoComments, type TodoCommentChange } from '@/main_app/todos/useTodoComments';
import { TodoCommentComposer } from './TodoCommentComposer';
import { TodoCommentsList } from './TodoCommentsList';

export type TodoCommentsProps = {
    todo_id: string;
    /** ToDo の permissions.can_comment。 */
    can_comment: boolean;
    onChanged: (change: TodoCommentChange) => void;
};

export const TodoComments = ({ todo_id, can_comment, onChanged }: TodoCommentsProps) => {
    const comments = useTodoComments(todo_id, { can_comment, onChanged });
    const [deleting, setDeleting] = useState<TodoCommentRead | null>(null);
    const { failure, pending } = comments;
    const delete_failed = failure !== null && failure.action === 'delete';

    const create = async (body: string): Promise<boolean> => (await comments.create(body)).ok;
    const update = async (comment: TodoCommentRead, body: string): Promise<boolean> => (await comments.update(comment, body)).ok;
    const confirmDelete = async () => {
        if (deleting === null) return;
        const result = await comments.remove(deleting);
        if (result.ok) setDeleting(null);
    };
    const reload = () => {
        comments.clearFailure();
        setDeleting(null);
        comments.reload();
    };

    return (
        <Box data-testid="todo-comments">
            <TodoCommentsList
                comments={comments}
                saving={pending === 'update'}
                onUpdate={update}
                onRequestDelete={(target) => { comments.clearFailure(); setDeleting(target); }}
            />
            {failure && !delete_failed && <Box sx={{ mt: 2 }}><TodoErrorAlert error={failure} test_id="todo-comments-error" onReload={reload} /></Box>}
            {comments.status === 'success' && <TodoCommentComposer can_comment={can_comment} pending={pending === 'create'} onCreate={create} />}

            <ConfirmDialog
                open={deleting !== null}
                title="コメントを削除しますか"
                description={deleting ? `${deleting.author.display_name} のコメントを削除します。削除すると、一覧に表示されなくなります。` : ''}
                confirm_label="削除する"
                confirm_color="error"
                pending={pending === 'delete'}
                onConfirm={() => void confirmDelete()}
                onCancel={() => setDeleting(null)}
                test_id="todo-comment-delete-dialog"
            >
                {failure && delete_failed && <TodoErrorAlert error={failure} test_id="todo-comment-delete-error" onReload={reload} />}
            </ConfirmDialog>
        </Box>
    );
};

export default TodoComments;
