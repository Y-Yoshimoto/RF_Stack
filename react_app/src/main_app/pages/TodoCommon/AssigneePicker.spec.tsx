// 担当者の選択のテスト (最大 20 人の上限・無効なユーザーの表示)
import { describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TODO_LIMITS } from '@/main_app/api/contract';
import type { TodoAssigneeOption } from '@/main_app/todos/useTodoChoices';
import { AssigneePicker } from './AssigneePicker';

/**
 * 選択肢を作る関数
 * @param {number} count 人数
 * @returns {TodoAssigneeOption[]} 選択肢 (user-1 ... user-N)
*/
const optionsOf = (count: number): TodoAssigneeOption[] => Array.from({ length: count }, (_, index) => ({ user_id: `user-${index + 1}`, display_name: `User ${index + 1}`, is_active: true, is_assigned: false }));

describe('AssigneePicker', () => {
    it('選択中の人数を「n / 20 人」で示す', () => {
        render(<AssigneePicker options={optionsOf(3)} value={['user-1']} onChange={vi.fn()} test_id="picker" />);
        expect(screen.getByTestId('picker-count')).toHaveTextContent(`選択中 1 / ${TODO_LIMITS.ASSIGNEES_MAX} 人`);
        expect(screen.getByTestId('picker-count')).toHaveAttribute('data-at-limit', 'false');
    });

    it('20 人に達すると、未選択のユーザーは選べず、上限であることを示す', async () => {
        const user = userEvent.setup();
        const selected = optionsOf(20).map((option) => option.user_id);
        render(<AssigneePicker options={optionsOf(21)} value={selected} onChange={vi.fn()} test_id="picker" />);
        expect(screen.getByTestId('picker-count')).toHaveAttribute('data-at-limit', 'true');
        expect(screen.getByTestId('picker-count')).toHaveTextContent('上限に達している');
        await user.click(screen.getByRole('combobox', { name: '担当者' }));
        const option = await screen.findByRole('option', { name: 'User 21' });
        // 無効な選択肢は aria-disabled で、ポインターも受け付けない (クリックできない)
        expect(option).toHaveAttribute('aria-disabled', 'true');
        expect(option).toHaveStyle({ pointerEvents: 'none' });
        expect(screen.getByRole('option', { name: 'User 1' })).toHaveAttribute('aria-selected', 'true');
    });

    it('19 人なら、あと 1 人を追加できる', async () => {
        const user = userEvent.setup();
        const onChange = vi.fn();
        render(<AssigneePicker options={optionsOf(21)} value={optionsOf(19).map((option) => option.user_id)} onChange={onChange} test_id="picker" />);
        await user.click(screen.getByRole('combobox', { name: '担当者' }));
        await user.click(await screen.findByRole('option', { name: 'User 20' }));
        expect(onChange).toHaveBeenCalledTimes(1);
        expect(onChange.mock.calls[0][0]).toHaveLength(20);
    });

    it('無効化されたユーザーは「無効」と示し、外すことができる', async () => {
        const user = userEvent.setup();
        const onChange = vi.fn();
        const options: TodoAssigneeOption[] = [{ user_id: 'u1', display_name: 'Jiro', is_active: false, is_assigned: true }];
        render(<AssigneePicker options={options} value={['u1']} onChange={onChange} test_id="picker" />);
        expect(screen.getByTestId('picker-chip-u1')).toHaveTextContent('Jiro (無効)');
        await user.click(screen.getByTestId('picker-chip-u1').querySelector('svg') as Element);
        expect(onChange).toHaveBeenCalledWith([]);
    });

    it('disabled なら操作できない', () => {
        render(<AssigneePicker options={optionsOf(2)} value={[]} onChange={vi.fn()} disabled test_id="picker" />);
        expect(screen.getByRole('combobox', { name: '担当者' })).toBeDisabled();
    });
});
