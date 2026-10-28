/**
 * @desc CP のテナント作成 (`/cp/tenant-create`。CP-ONB-01 / 02。saas_admin のみ)
 * saas_viewer には画面を出さない (NotFound)。API 側でも 403 で拒否される (01 §11.2)。
 * 払い出しは同期実行で最大 30 秒ほどかかる (CP-ONB-05 / 06)。成功すると一時パスワードを一度だけダイアログに表示し、閉じると詳細へ移る。
 * 払い出しが途中で失敗 (502) した場合は、テナントが FAILED で残るため、詳細画面で再実行できる。
 */
import { useState, type ChangeEvent } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { Box, Button, CircularProgress, Link, Paper, Stack, TextField, Typography } from '@mui/material';
import { useCpPermissions } from '@/control_plane_app/auth/useCpAuth';
import { CpErrorAlert } from '@/control_plane_app/components/CpErrorAlert';
import { problemStringOf } from '@/control_plane_app/components/error_text';
import { CredentialsDialog } from '@/control_plane_app/components/CredentialsDialog';
import { CP_HOME_PATH, CP_TENANTS_PATH, cpTenantPathOf } from '@/control_plane_app/paths';
import { useTenantActions } from '@/control_plane_app/tenants/useTenantActions';
import { NotFoundPage } from '@/shared/pages/NotFound';
import { normalizeTenantCodeInput } from '@/shared/tenant_code';
import {
    EMPTY_TENANT_CREATE_FORM,
    serverErrorsToFormErrors,
    TENANT_CREATE_FIELDS,
    toTenantCreate,
    validateTenantCreateForm,
    type TenantCreateErrors,
    type TenantCreateField,
    type TenantCreateForm,
} from './validation';

/** 入力欄の id (最初のエラーの欄へフォーカスを移すために使う) */
const fieldIdOf = (field: TenantCreateField): string => `tenant-create-field-${field}`;

const TenantCreateFormView = () => {
    const navigate = useNavigate();
    const actions = useTenantActions();
    const [form, setForm] = useState<TenantCreateForm>(EMPTY_TENANT_CREATE_FORM);
    const [errors, setErrors] = useState<TenantCreateErrors>({});
    const is_pending = actions.pending === 'create';

    const focusFirstError = (next: TenantCreateErrors) => {
        const first = TENANT_CREATE_FIELDS.find((field) => next[field] !== undefined);
        if (first) document.getElementById(fieldIdOf(first))?.focus();
    };

    const handleChange = (field: TenantCreateField) => (event: ChangeEvent<HTMLInputElement>) => {
        setForm((prev) => ({ ...prev, [field]: event.target.value }));
        if (errors[field] !== undefined) setErrors((prev) => ({ ...prev, [field]: undefined }));
    };

    const handleSubmit = async (event: { preventDefault: () => void }) => {
        event.preventDefault();
        if (is_pending) return;
        const client_errors = validateTenantCreateForm(form);
        setErrors(client_errors);
        if (Object.keys(client_errors).length > 0) {
            actions.clearFailure();
            focusFirstError(client_errors);
            return;
        }
        const result = await actions.create(toTenantCreate(form));
        if (!result.ok) {
            const server_errors = serverErrorsToFormErrors(result.failure);
            setErrors(server_errors);
            focusFirstError(server_errors);
        }
    };

    // ダイアログを閉じると一時パスワードを破棄し、作成したテナントの詳細へ移る
    const handleCredentialsClose = () => {
        const tenant_id = actions.issued_credentials?.tenant_id;
        actions.dismissCredentials();
        if (tenant_id) void navigate(cpTenantPathOf(tenant_id));
    };

    const failed_tenant_id = actions.failure?.kind === 'external_failure' ? problemStringOf(actions.failure, 'tenant_id') : null;
    const fieldProps = (field: TenantCreateField) => ({
        value: form[field],
        onChange: handleChange(field),
        error: errors[field] !== undefined,
        helperText: errors[field],
        disabled: is_pending,
        id: fieldIdOf(field),
        slotProps: { htmlInput: { 'data-testid': `tenant-create-${field.replace('_', '-')}` } },
    });

    return (
        <Stack spacing={3} data-testid="cp-tenant-create-page">
            <Box>
                <Typography variant="h4" component="h1" gutterBottom>テナント作成</Typography>
                <Typography variant="body1" color="text.secondary">
                    テナントと初期管理者を払い出します。処理は同期で実行され、最大 30 秒ほどかかります。
                </Typography>
            </Box>

            {actions.failure && (
                <CpErrorAlert error={actions.failure} test_id="tenant-create-error">
                    {failed_tenant_id && (
                        <Typography variant="body2" sx={{ mt: 1 }}>
                            テナントは「払い出し失敗」の状態で残っています。
                            <Link component={RouterLink} to={cpTenantPathOf(failed_tenant_id)} data-testid="tenant-create-error-detail-link">テナントの詳細で払い出しを再実行</Link>
                            してください。
                        </Typography>
                    )}
                </CpErrorAlert>
            )}

            <Paper component="form" variant="outlined" noValidate onSubmit={(event) => void handleSubmit(event)} aria-busy={is_pending} sx={{ p: { xs: 2, sm: 3 }, maxWidth: 640 }} data-testid="tenant-create-form">
                <Stack spacing={3}>
                    <Stack component="section" spacing={2} aria-labelledby="tenant-create-tenant-heading">
                        <Typography id="tenant-create-tenant-heading" variant="h6" component="h2">テナント</Typography>
                        <TextField
                            {...fieldProps('tenant_code')}
                            label="テナントコード"
                            required
                            autoComplete="off"
                            onBlur={() => setForm((prev) => ({ ...prev, tenant_code: normalizeTenantCodeInput(prev.tenant_code) }))}
                            helperText={errors.tenant_code ?? '英小文字・数字・ハイフンの 3〜32 文字。URL の一部になり、作成後は変更できません。'}
                        />
                        <TextField {...fieldProps('name')} label="テナント名" required autoComplete="off" />
                    </Stack>
                    <Stack component="section" spacing={2} aria-labelledby="tenant-create-admin-heading">
                        <Typography id="tenant-create-admin-heading" variant="h6" component="h2">初期管理者</Typography>
                        <TextField
                            {...fieldProps('email')}
                            label="メールアドレス"
                            type="email"
                            required
                            autoComplete="off"
                            helperText={errors.email ?? '初期管理者のメールアドレスです。一時パスワードはこの画面に一度だけ表示します。'}
                        />
                        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                            <TextField {...fieldProps('last_name')} label="姓" autoComplete="off" fullWidth />
                            <TextField {...fieldProps('first_name')} label="名" autoComplete="off" fullWidth />
                        </Stack>
                    </Stack>
                    <Stack direction="row" spacing={2} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
                        <Button type="submit" variant="contained" disabled={is_pending} startIcon={is_pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined} data-testid="tenant-create-submit">
                            {is_pending ? '払い出し中…' : 'テナントを作成'}
                        </Button>
                        <Button component={RouterLink} to={CP_TENANTS_PATH} disabled={is_pending} data-testid="tenant-create-cancel">一覧へ戻る</Button>
                        <Typography variant="body2" color="text.secondary" role="status" data-testid="tenant-create-status">
                            {is_pending ? '払い出しを実行しています。完了までこの画面を閉じないでください。' : ''}
                        </Typography>
                    </Stack>
                </Stack>
            </Paper>

            <CredentialsDialog credentials={actions.issued_credentials} onClose={handleCredentialsClose} />
        </Stack>
    );
};

export const CpTenantCreatePage = () => {
    const { can_write } = useCpPermissions();
    // saas_viewer には変更操作の画面を出さない
    if (!can_write) return <NotFoundPage embedded home_path={CP_HOME_PATH} home_label="ダッシュボードへ戻る" />;
    return <TenantCreateFormView />;
};

export default CpTenantCreatePage;
