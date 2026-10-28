/**
 * @desc ToDo の画面の区画 (見出し h2 と、それに関連付けた section)
 */
import type { ReactNode } from 'react';
import { Paper, Typography } from '@mui/material';

export type TodoSectionProps = {
    title: string;
    children: ReactNode;
    /** data-testid (見出しは `${test_id}-heading`)。 */
    test_id: string;
};

export const TodoSection = ({ title, children, test_id }: TodoSectionProps) => (
    <Paper variant="outlined" component="section" aria-labelledby={`${test_id}-heading`} sx={{ p: 2 }} data-testid={test_id}>
        <Typography id={`${test_id}-heading`} variant="h6" component="h2" gutterBottom data-testid={`${test_id}-heading`}>{title}</Typography>
        {children}
    </Paper>
);

export default TodoSection;
