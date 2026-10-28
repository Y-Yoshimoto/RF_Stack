/**
 * @desc ユーザーの編集フォーム (姓名・ロール。tenant_admin のみ)
 * 変更した項目だけを送る。自分自身の tenant_admin の解除は、API を呼ぶ前に selfModificationOf で判定し、無効化して理由を表示する。
 * 姓名の初期値は表示名 (`"{名} {姓}"`) から推定するため、姓名の入力欄を変更したときだけ姓名を送る。
 */
import { useRef, useState, type FormEvent } from 'react';
import { Box, Button, Checkbox, CircularProgress, FormControl, FormControlLabel, FormGroup, FormHelperText, FormLabel, Paper, Stack, TextField, Typography } from '@mui/material';
import { APP_ROLE, type AppRole, type UserDetail } from '@/main_app/api/contract';
import { selfModificationOf, type UserChanges } from '@/main_app/api/users';
import { APP_ROLE_LABELS } from '@/main_app/layouts/AppLayout/labels';
import { nameErrorOf } from '@/main_app/pages/UserCreate/validation';
import { namePartsOf } from './name_parts';

const ROLE_OPTIONS: readonly AppRole[] = [APP_ROLE.MEMBER, APP_ROLE.TENANT_ADMIN];
const ROLE_LOCK_ID = 'user-edit-role-lock';

export type UserEditFormProps = {
    user: UserDetail;
    /** 自分のユーザー ID (未取得なら null)。 */
    self_user_id: string | null;
    /** 変更を保存する (成功したら true)。 */
    onSave: (changes: UserChanges) => Promise<boolean>;
    /** 保存中 (入力を無効にする)。 */
    pending: boolean;
};

type FieldErrors = { last_name?: string; first_name?: string; roles?: string };

/**
 * ロールの集合が等しいかを判定する関数
 * @param {readonly AppRole[]} a 一方
 * @param {readonly AppRole[]} b 他方
 * @returns {boolean} 等しければ true
*/
const sameRoles = (a: readonly AppRole[], b: readonly AppRole[]): boolean => a.length === b.length && a.every((role) => b.includes(role));

export const UserEditForm = ({ user, self_user_id, onSave, pending }: UserEditFormProps) => {
    const initial = namePartsOf(user.display_name);
    const [last_name, setLastName] = useState(initial.last_name);
    const [first_name, setFirstName] = useState(initial.first_name);
    const [roles, setRoles] = useState<readonly AppRole[]>(user.roles);
    const [errors, setErrors] = useState<FieldErrors>({});
    const last_name_ref = useRef<HTMLInputElement | null>(null);
    const first_name_ref = useRef<HTMLInputElement | null>(null);
    const roles_ref = useRef<HTMLInputElement | null>(null);

    // 自分自身の tenant_admin は外せない (API の 409 user_self_modification_forbidden と同じ条件)
    const is_admin_locked = user.roles.includes(APP_ROLE.TENANT_ADMIN) && selfModificationOf(user.id, self_user_id, { roles: [APP_ROLE.MEMBER] }) === 'remove_tenant_admin';
    const is_name_changed = last_name.trim() !== initial.last_name || first_name.trim() !== initial.first_name;
    const is_roles_changed = !sameRoles(roles, user.roles);

    const toggleRole = (role: AppRole, checked: boolean) => {
        setRoles((prev) => (checked ? [...prev, role] : prev.filter((known) => known !== role)));
    };

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        const found: FieldErrors = {};
        if (is_name_changed) {
            found.last_name = nameErrorOf(last_name, '姓');
            found.first_name = nameErrorOf(first_name, '名');
        }
        if (roles.length === 0) found.roles = 'ロールを 1 つ以上選んでください。';
        setErrors(found);
        if (found.last_name) last_name_ref.current?.focus();
        else if (found.first_name) first_name_ref.current?.focus();
        else if (found.roles) roles_ref.current?.focus();
        if (found.last_name || found.first_name || found.roles) return;
        const changes: UserChanges = {
            ...(is_name_changed ? { name: { first_name: first_name.trim(), last_name: last_name.trim() } } : {}),
            ...(is_roles_changed ? { roles } : {}),
        };
        await onSave(changes);
    };

    return (
        <Paper variant="outlined" component="section" aria-labelledby="user-edit-heading" sx={{ p: 2 }} data-testid="user-edit">
            <Typography id="user-edit-heading" variant="h6" component="h2" gutterBottom>編集</Typography>
            <Box component="form" noValidate onSubmit={(event: FormEvent) => void submit(event)} aria-labelledby="user-edit-heading" data-testid="user-edit-form" sx={{ maxWidth: 560 }}>
                <Stack spacing={3}>
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                        <TextField
                            label="姓"
                            required
                            fullWidth
                            value={last_name}
                            onChange={(event) => setLastName(event.target.value)}
                            error={errors.last_name !== undefined}
                            helperText={errors.last_name}
                            inputRef={last_name_ref}
                            slotProps={{ htmlInput: { 'data-testid': 'user-edit-last-name', autoComplete: 'off' } }}
                        />
                        <TextField
                            label="名"
                            required
                            fullWidth
                            value={first_name}
                            onChange={(event) => setFirstName(event.target.value)}
                            error={errors.first_name !== undefined}
                            helperText={errors.first_name}
                            inputRef={first_name_ref}
                            slotProps={{ htmlInput: { 'data-testid': 'user-edit-first-name', autoComplete: 'off' } }}
                        />
                    </Stack>
                    <FormControl component="fieldset" required error={errors.roles !== undefined} data-testid="user-edit-roles">
                        <FormLabel component="legend">ロール</FormLabel>
                        <FormGroup>
                            {ROLE_OPTIONS.map((role) => {
                                const is_locked = role === APP_ROLE.TENANT_ADMIN && is_admin_locked;
                                return (
                                    <FormControlLabel
                                        key={role}
                                        label={APP_ROLE_LABELS[role]}
                                        control={
                                            <Checkbox
                                                checked={roles.includes(role)}
                                                disabled={is_locked}
                                                onChange={(event) => toggleRole(role, event.target.checked)}
                                                slotProps={{ input: { 'data-testid': `user-edit-role-${role}`, ref: role === ROLE_OPTIONS[0] ? roles_ref : undefined, ...(is_locked ? { 'aria-describedby': ROLE_LOCK_ID } : {}) } as object }}
                                            />
                                        }
                                    />
                                );
                            })}
                        </FormGroup>
                        {is_admin_locked && (
                            <FormHelperText id={ROLE_LOCK_ID} data-testid="user-edit-role-lock">自分自身のテナント管理者ロールは解除できません。別のテナント管理者に依頼してください。</FormHelperText>
                        )}
                        {errors.roles && <FormHelperText data-testid="user-edit-roles-error">{errors.roles}</FormHelperText>}
                    </FormControl>
                    <Box>
                        <Button
                            type="submit"
                            variant="contained"
                            disabled={pending || (!is_name_changed && !is_roles_changed)}
                            startIcon={pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                            data-testid="user-edit-submit"
                        >
                            {pending ? '保存中…' : '変更を保存'}
                        </Button>
                    </Box>
                </Stack>
            </Box>
        </Paper>
    );
};

export default UserEditForm;
