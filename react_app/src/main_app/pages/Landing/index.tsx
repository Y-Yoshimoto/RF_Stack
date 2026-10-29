/**
 * @desc ランディング (`/`)。テナントコードを入力し `/{tenant_code}/login` へ遷移する。
 * 検証と遷移は useTenantCodeEntry が行う。この画面は入力欄・エラー表示・フォーカスのみを担当する。
 * 認証関連ページの外枠 (AuthLayout) の外に置かれるため、AuthContainer で自分を包む。
 */
import { useRef, useState } from 'react';
import { Box, Button, TextField, Typography, type FormHelperTextProps } from '@mui/material';
import BusinessIcon from '@mui/icons-material/Business';
import { useTenantCodeEntry } from '@/main_app/tenant/useTenantCodeEntry';
import { AuthCard } from '@/shared/components/AuthCard';
import { LoginErrorAlert } from '@/shared/components/LoginErrorAlert';
import { AuthContainer } from '@/shared/layouts/AuthLayout';
import type { TenantCodeViolation } from '@/shared/tenant_code';

/** 入力値を受け付けられない理由ごとの文言。予約語は形式違反と同じ文言にする (予約語の一覧を画面から推測させない)。 */
export const TENANT_CODE_VIOLATION_MESSAGES: Readonly<Record<TenantCodeViolation, string>> = {
    empty: 'テナントコードを入力してください',
    format: 'テナントコードは 3〜32 文字の英小文字・数字・ハイフンで入力してください (先頭と末尾にハイフンは使えません)',
    reserved: 'テナントコードが正しくありません。入力内容を確認してください',
};

export const LandingPage = () => {
    const { error_code, submit } = useTenantCodeEntry();
    const [input, setInput] = useState('');
    const [violation, setViolation] = useState<TenantCodeViolation | null>(null);
    const input_ref = useRef<HTMLInputElement>(null);
    return (
        <AuthContainer>
            <AuthCard
                test_id="landing-page"
                title="テナントにログイン"
                description="ご利用の組織のテナントコードを入力してください"
                icon={<BusinessIcon />}
            >
                <Box
                    component="form"
                    noValidate
                    onSubmit={(e) => {
                        e.preventDefault();
                        const result = submit(input);
                        setViolation(result.ok ? null : result.violation);
                        // 入力に誤りがあるときは入力欄に戻し、エラーの文言 (aria-describedby) を読み上げさせる
                        if (!result.ok) input_ref.current?.focus();
                    }}
                    sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}
                >
                    {!violation && <LoginErrorAlert error_code={error_code} />}
                    <TextField
                        id="tenant-code"
                        name="tenant_code"
                        label="テナントコード"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        error={violation !== null}
                        helperText={violation ? TENANT_CODE_VIOLATION_MESSAGES[violation] : '英小文字・数字・ハイフン (例: acme-corp)'}
                        required
                        fullWidth
                        autoFocus
                        inputRef={input_ref}
                        slotProps={{
                            htmlInput: { 'data-testid': 'login-tenant-code', autoComplete: 'off', autoCapitalize: 'none', spellCheck: false },
                            // エラーの文言は表示と同時に読み上げさせる (入力欄の aria-describedby は TextField が結びつける)
                            formHelperText: violation ? { role: 'alert', 'data-testid': 'tenant-code-violation', 'data-violation': violation } as FormHelperTextProps : undefined,
                        }}
                    />
                    <Button type="submit" variant="contained" size="large" fullWidth data-testid="login-submit">次へ</Button>
                    <Typography variant="caption" component="p" color="text.secondary" sx={{ textAlign: 'center' }}>
                        テナントコードは、管理者からの案内に記載されています
                    </Typography>
                </Box>
            </AuthCard>
        </AuthContainer>
    );
};

export default LandingPage;
