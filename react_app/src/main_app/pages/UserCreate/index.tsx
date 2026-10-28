/**
 * @desc ユーザー作成 (`/{tenant_code}/users/new`。tenant_admin のみ)
 * メール・姓・名・ロールを入力して作成する。発行された一時パスワードは、ダイアログに一度だけ表示する (閉じると消える)。
 * 使うフック: useUserActions (作成・一時パスワード)、useAppPermissions (権限)。
 * member がこの URL を開いた場合は、フォームを出さずに権限がないことを案内する。
 */
import { useRef, useState, type FormEvent } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { Alert, Box, Button, Checkbox, CircularProgress, FormControl, FormControlLabel, FormGroup, FormHelperText, FormLabel, Stack, TextField } from '@mui/material';
import { APP_ROLE, type AppRole } from '@/main_app/api/contract';
import { useAppPermissions, useAppSession } from '@/main_app/auth/useAppAuth';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import { CredentialsDialog } from '@/main_app/components/CredentialsDialog';
import { PageHeader } from '@/main_app/components/PageHeader';
import { APP_ROLE_LABELS } from '@/main_app/layouts/AppLayout/labels';
import { appUserPath, appUsersPath } from '@/main_app/paths';
import { useUserActions } from '@/main_app/users/useUserActions';
import { USER_CREATE_FIELD_ORDER, validateUserCreate, type UserCreateErrors, type UserCreateValues } from './validation';

const ROLE_OPTIONS: readonly AppRole[] = [APP_ROLE.MEMBER, APP_ROLE.TENANT_ADMIN];

const INITIAL_VALUES: UserCreateValues = { email: '', last_name: '', first_name: '', roles: [APP_ROLE.MEMBER] };

/** 作成の結果 (一時パスワードは含まない。パスワードはフックの issued_credentials にだけある) */
type CreatedUser = { user_id: string; display_name: string };

export const AppUserCreatePage = () => {
    const { tenant_code } = useAppSession();
    const { can_write } = useAppPermissions();
    // 作成では自分自身の判定を使わない
    const actions = useUserActions({ self_user_id: null });
    const [values, setValues] = useState<UserCreateValues>(INITIAL_VALUES);
    const [errors, setErrors] = useState<UserCreateErrors>({});
    const [created, setCreated] = useState<CreatedUser | null>(null);
    const field_refs = useRef<Partial<Record<keyof UserCreateValues, HTMLInputElement | null>>>({});

    const toggleRole = (role: AppRole, checked: boolean) => {
        setValues((prev) => ({ ...prev, roles: checked ? [...prev.roles, role] : prev.roles.filter((known) => known !== role) }));
    };

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        const found = validateUserCreate(values);
        setErrors(found);
        const first_invalid = USER_CREATE_FIELD_ORDER.find((key) => found[key] !== undefined);
        if (first_invalid) {
            field_refs.current[first_invalid]?.focus();
            return;
        }
        const result = await actions.create({ email: values.email.trim(), last_name: values.last_name.trim(), first_name: values.first_name.trim(), roles: [...values.roles] });
        if (result.ok) setCreated({ user_id: result.user.id, display_name: result.user.display_name });
    };

    const createAnother = () => {
        setCreated(null);
        setValues(INITIAL_VALUES);
        setErrors({});
        actions.clearFailure();
    };

    if (!can_write) {
        return (
            <Stack spacing={3} data-testid="app-user-create-page" data-can-write="false">
                <PageHeader test_id="user-create" title="ユーザーの作成" back={{ to: appUsersPath(tenant_code), label: 'ユーザー管理へ戻る' }} />
                <Alert severity="warning" data-testid="user-create-forbidden">ユーザーを作成するにはテナント管理者の権限が必要です。</Alert>
            </Stack>
        );
    }

    const is_pending = actions.pending === 'create';
    return (
        <Stack spacing={3} data-testid="app-user-create-page" data-can-write="true">
            <PageHeader
                test_id="user-create"
                title="ユーザーの作成"
                description="メールは送信されません。作成後に表示される一時パスワードを、安全な方法で本人に伝えてください。"
                back={{ to: appUsersPath(tenant_code), label: 'ユーザー管理へ戻る' }}
            />

            {created === null ? (
                <Box component="form" noValidate onSubmit={(event: FormEvent) => void submit(event)} aria-label="ユーザーの作成" data-testid="user-create-form" sx={{ maxWidth: 560 }}>
                    <Stack spacing={3}>
                        {actions.failure && <AppErrorAlert error={actions.failure} test_id="user-create-error" />}
                        <TextField
                            label="メールアドレス"
                            type="email"
                            required
                            value={values.email}
                            onChange={(event) => setValues((prev) => ({ ...prev, email: event.target.value }))}
                            error={errors.email !== undefined}
                            helperText={errors.email ?? 'ログインのユーザー名にも使われます。テナント内で一意にしてください。'}
                            inputRef={(element: HTMLInputElement | null) => { field_refs.current.email = element; }}
                            slotProps={{ htmlInput: { 'data-testid': 'user-create-email', autoComplete: 'off' } }}
                        />
                        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                            <TextField
                                label="姓"
                                required
                                fullWidth
                                value={values.last_name}
                                onChange={(event) => setValues((prev) => ({ ...prev, last_name: event.target.value }))}
                                error={errors.last_name !== undefined}
                                helperText={errors.last_name}
                                inputRef={(element: HTMLInputElement | null) => { field_refs.current.last_name = element; }}
                                slotProps={{ htmlInput: { 'data-testid': 'user-create-last-name', autoComplete: 'off' } }}
                            />
                            <TextField
                                label="名"
                                required
                                fullWidth
                                value={values.first_name}
                                onChange={(event) => setValues((prev) => ({ ...prev, first_name: event.target.value }))}
                                error={errors.first_name !== undefined}
                                helperText={errors.first_name}
                                inputRef={(element: HTMLInputElement | null) => { field_refs.current.first_name = element; }}
                                slotProps={{ htmlInput: { 'data-testid': 'user-create-first-name', autoComplete: 'off' } }}
                            />
                        </Stack>
                        <FormControl component="fieldset" required error={errors.roles !== undefined} data-testid="user-create-roles">
                            <FormLabel component="legend">ロール</FormLabel>
                            <FormGroup>
                                {ROLE_OPTIONS.map((role) => (
                                    <FormControlLabel
                                        key={role}
                                        label={APP_ROLE_LABELS[role]}
                                        control={
                                            <Checkbox
                                                checked={values.roles.includes(role)}
                                                onChange={(event) => toggleRole(role, event.target.checked)}
                                                slotProps={{ input: { 'data-testid': `user-create-role-${role}`, ref: role === ROLE_OPTIONS[0] ? (element: HTMLInputElement | null) => { field_refs.current.roles = element; } : undefined } as object }}
                                            />
                                        }
                                    />
                                ))}
                            </FormGroup>
                            <FormHelperText>{errors.roles ?? 'テナント管理者はユーザー・組織を変更できます。メンバーは閲覧のみです。'}</FormHelperText>
                        </FormControl>
                        <Stack direction="row" spacing={2}>
                            <Button
                                type="submit"
                                variant="contained"
                                disabled={is_pending}
                                startIcon={is_pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                                data-testid="user-create-submit"
                            >
                                {is_pending ? '作成中…' : '作成する'}
                            </Button>
                            <Button component={RouterLink} to={appUsersPath(tenant_code)} disabled={is_pending} data-testid="user-create-cancel">キャンセル</Button>
                        </Stack>
                    </Stack>
                </Box>
            ) : (
                <Alert severity="success" role="status" data-testid="user-create-done">
                    {created.display_name} を作成しました。{actions.issued_credentials === null ? '一時パスワードの表示は終了しました。再表示はできません。' : ''}
                    <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 1, flexWrap: 'wrap' }}>
                        <Button size="small" variant="outlined" color="inherit" component={RouterLink} to={appUserPath(tenant_code, created.user_id)} data-testid="user-create-done-detail">詳細を開く</Button>
                        <Button size="small" variant="outlined" color="inherit" component={RouterLink} to={appUsersPath(tenant_code)} data-testid="user-create-done-list">一覧へ戻る</Button>
                        <Button size="small" variant="outlined" color="inherit" onClick={createAnother} data-testid="user-create-done-again">続けて作成する</Button>
                    </Stack>
                </Alert>
            )}

            <CredentialsDialog credentials={actions.issued_credentials} onClose={actions.dismissCredentials} />
        </Stack>
    );
};

export default AppUserCreatePage;
