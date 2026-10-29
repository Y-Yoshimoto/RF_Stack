/**
 * @desc ToDo 一覧が空のときの案内 (AP-UX-06)
 * 表示範囲ごとに文言を変え、作成への導線を出す。絞り込み中は「条件に合う ToDo がありません」と「絞り込みをクリア」を出す。
 */
import { Link as RouterLink } from 'react-router-dom';
import { Box, Button, Stack, Typography } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import ChecklistIcon from '@mui/icons-material/Checklist';
import type { TodoScope } from '@/main_app/api/contract';

export type TodoEmptyStateProps = {
    scope: TodoScope;
    /** 絞り込み (表示範囲と並び順を除く) が指定されている。 */
    has_conditions: boolean;
    onClear: () => void;
    /** ToDo の作成画面のパス。 */
    create_to: string;
};

/** 表示範囲ごとの案内 (絞り込みが無いとき) */
const EMPTY_TEXTS: Readonly<Record<TodoScope, { title: string; hint: string }>> = {
    all: { title: 'ToDo がありません。', hint: '最初の ToDo を作成して、やることを書き出しましょう。' },
    mine: { title: '自分が作成した ToDo はありません。', hint: 'ToDo を作成すると、ここに表示されます。' },
    assigned: { title: '自分が担当の ToDo はありません。', hint: '担当者に指定されると、ここに表示されます。自分で ToDo を作成して担当することもできます。' },
    shared: { title: '共有された ToDo はありません。', hint: '他の人が組織やテナント全体に公開した ToDo が、ここに表示されます。' },
};

export const TodoEmptyState = ({ scope, has_conditions, onClear, create_to }: TodoEmptyStateProps) => {
    const text = has_conditions ? { title: '条件に合う ToDo がありません。', hint: '絞り込みの条件を変えるか、クリアしてください。' } : EMPTY_TEXTS[scope];
    return (
        <Box data-testid="todo-list-empty" data-scope={scope} data-filtered={has_conditions} sx={{ py: 6, px: 2, textAlign: 'center' }}>
            <Stack spacing={1.5} sx={{ alignItems: 'center' }}>
                <ChecklistIcon color="disabled" sx={{ fontSize: 48 }} aria-hidden />
                <Typography variant="h6" component="h2" data-testid="todo-list-empty-title">{text.title}</Typography>
                <Typography variant="body2" color="text.secondary">{text.hint}</Typography>
                <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', justifyContent: 'center' }}>
                    {has_conditions && <Button variant="outlined" onClick={onClear} data-testid="todo-list-empty-clear">絞り込みをクリア</Button>}
                    <Button component={RouterLink} to={create_to} variant={has_conditions ? 'text' : 'contained'} startIcon={<AddIcon />} data-testid="todo-list-empty-create">ToDo を作成</Button>
                </Stack>
            </Stack>
        </Box>
    );
};

export default TodoEmptyState;
