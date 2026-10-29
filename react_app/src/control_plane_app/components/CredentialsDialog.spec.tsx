// 一時パスワードのダイアログのテスト (一度だけの表示・閉じると消える・コピー)
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { IssuedCredentials } from '@/control_plane_app/tenants/useTenantActions';
import { CredentialsDialog } from './CredentialsDialog';

const CREDENTIALS: IssuedCredentials = { tenant_id: 't1', tenant_code: 'alpha', username: 'admin@example.com', temporary_password: 'Secret-Temp-1!' };

/** フックの issued_credentials と同じく、閉じると破棄する親 */
const Host = () => {
    const [credentials, setCredentials] = useState<IssuedCredentials | null>(CREDENTIALS);
    return <CredentialsDialog credentials={credentials} onClose={() => setCredentials(null)} />;
};

describe('CredentialsDialog', () => {
    it('一時パスワードと、閉じると消える旨を表示する', () => {
        render(<Host />);
        expect(screen.getByRole('dialog', { name: '初期管理者の一時パスワード' })).toBeInTheDocument();
        expect(screen.getByTestId('credentials-dialog-password')).toHaveTextContent('Secret-Temp-1!');
        expect(screen.getByTestId('credentials-dialog-warning')).toHaveTextContent('閉じると消え、再表示できません');
    });

    it('閉じると、ダイアログも一時パスワードも DOM から消える', async () => {
        const user = userEvent.setup();
        render(<Host />);
        await user.click(screen.getByTestId('credentials-dialog-close'));
        expect(screen.queryByTestId('credentials-dialog')).toBeNull();
        expect(document.body).not.toHaveTextContent('Secret-Temp-1!');
    });

    it('背景のクリックでは閉じない (誤って一時パスワードを失わないため)', async () => {
        const user = userEvent.setup();
        const onClose = vi.fn();
        render(<CredentialsDialog credentials={CREDENTIALS} onClose={onClose} />);
        const backdrop = document.querySelector('.MuiBackdrop-root');
        expect(backdrop).not.toBeNull();
        await user.click(backdrop as Element);
        expect(onClose).not.toHaveBeenCalled();
    });

    it('Esc では閉じられる', async () => {
        const user = userEvent.setup();
        const onClose = vi.fn();
        render(<CredentialsDialog credentials={CREDENTIALS} onClose={onClose} />);
        await user.keyboard('{Escape}');
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('認証情報が無ければ何も表示しない', () => {
        render(<CredentialsDialog credentials={null} onClose={vi.fn()} />);
        expect(screen.queryByTestId('credentials-dialog')).toBeNull();
    });

    it('コピーに成功すると、結果を読み上げ用の領域に出す', async () => {
        const user = userEvent.setup();
        const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
        render(<Host />);
        await user.click(screen.getByTestId('credentials-dialog-copy'));
        expect(writeText).toHaveBeenCalledWith('Secret-Temp-1!');
        expect(await screen.findByTestId('credentials-dialog-copy-status')).toHaveTextContent('コピーしました');
        writeText.mockRestore();
    });

    it('コピーに失敗すると、手動でのコピーを案内する', async () => {
        const user = userEvent.setup();
        const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('denied'));
        render(<Host />);
        await user.click(screen.getByTestId('credentials-dialog-copy'));
        expect(await screen.findByTestId('credentials-dialog-copy-status')).toHaveTextContent('手動でコピー');
        writeText.mockRestore();
    });
});
