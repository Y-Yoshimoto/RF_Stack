// 一時パスワードのダイアログのテスト (表示・コピー・閉じる・背景クリックでは閉じない)
import { afterEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { IssuedUserCredentials } from '@/main_app/users/useUserActions';
import { CredentialsDialog } from './CredentialsDialog';

const CREDENTIALS: IssuedUserCredentials = { username: 'taro@alpha.example', temporary_password: 'Tmp-Secret-123!', user_id: 'u-1', display_name: 'Taro Yamada' };

afterEach(() => {
    vi.restoreAllMocks();
});

describe('CredentialsDialog', () => {
    it('認証情報が無ければ何も表示しない', () => {
        render(<CredentialsDialog credentials={null} onClose={vi.fn()} />);
        expect(screen.queryByTestId('credentials-dialog')).toBeNull();
    });

    it('ユーザー名と一時パスワードを表示し、閉じると消える旨を明示する', () => {
        render(<CredentialsDialog credentials={CREDENTIALS} onClose={vi.fn()} />);
        expect(screen.getByRole('dialog', { name: '一時パスワード' })).toBeInTheDocument();
        expect(screen.getByTestId('credentials-dialog-username')).toHaveTextContent('taro@alpha.example');
        expect(screen.getByTestId('credentials-dialog-password')).toHaveTextContent('Tmp-Secret-123!');
        expect(screen.getByTestId('credentials-dialog-warning')).toHaveTextContent('再表示できません');
        expect(screen.getByTestId('credentials-dialog-close')).toHaveTextContent('パスワードは消えます');
    });

    it('初期フォーカスは「コピー」ボタンにある', () => {
        render(<CredentialsDialog credentials={CREDENTIALS} onClose={vi.fn()} />);
        expect(screen.getByTestId('credentials-dialog-copy')).toHaveFocus();
    });

    it('コピーに成功すると、結果を role="status" で知らせる', async () => {
        const user = userEvent.setup();
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
        render(<CredentialsDialog credentials={CREDENTIALS} onClose={vi.fn()} />);
        await user.click(screen.getByTestId('credentials-dialog-copy'));
        expect(writeText).toHaveBeenCalledWith('Tmp-Secret-123!');
        expect(await screen.findByText('一時パスワードをクリップボードにコピーしました。')).toBeInTheDocument();
        expect(screen.getByTestId('credentials-dialog-copy-status')).toHaveAttribute('role', 'status');
    });

    it('コピーに失敗すると、手動でコピーするよう案内する', async () => {
        const user = userEvent.setup();
        Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) }, configurable: true });
        render(<CredentialsDialog credentials={CREDENTIALS} onClose={vi.fn()} />);
        await user.click(screen.getByTestId('credentials-dialog-copy'));
        expect(await screen.findByText(/手動でコピーしてください/)).toBeInTheDocument();
    });

    it('「閉じる」と Esc で onClose を呼ぶが、背景のクリックでは呼ばない', async () => {
        const user = userEvent.setup();
        const onClose = vi.fn();
        render(<CredentialsDialog credentials={CREDENTIALS} onClose={onClose} />);
        await user.keyboard('{Escape}');
        expect(onClose).toHaveBeenCalledTimes(1);
        await user.click(document.querySelector('.MuiBackdrop-root') as HTMLElement);
        expect(onClose).toHaveBeenCalledTimes(1);
        await user.click(screen.getByTestId('credentials-dialog-close'));
        expect(onClose).toHaveBeenCalledTimes(2);
    });
});
