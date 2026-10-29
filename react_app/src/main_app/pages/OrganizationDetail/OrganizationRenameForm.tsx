/**
 * @desc 組織名の表示・変更 (変更は tenant_admin のみ。member は読み取り専用の表示)
 */
import { useRef, useState, type FormEvent } from 'react';
import { Box, Button, CircularProgress, Paper, Stack, TextField, Typography } from '@mui/material';
import { formatDateTime } from '@/main_app/components/format';
import type { OrganizationDetail } from '@/main_app/api/contract';
import { organizationNameErrorOf } from './validation';

export type OrganizationRenameFormProps = {
    organization: OrganizationDetail;
    can_write: boolean;
    /** 組織名を変更する (成功したら true)。 */
    onRename: (name: string) => Promise<boolean>;
    pending: boolean;
};

export const OrganizationRenameForm = ({ organization, can_write, onRename, pending }: OrganizationRenameFormProps) => {
    const [name, setName] = useState(organization.name);
    const [error, setError] = useState<string | undefined>(undefined);
    const input_ref = useRef<HTMLInputElement | null>(null);

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        const found = organizationNameErrorOf(name);
        setError(found);
        if (found) {
            input_ref.current?.focus();
            return;
        }
        await onRename(name.trim());
    };

    return (
        <Paper variant="outlined" component="section" aria-labelledby="organization-info-heading" sx={{ p: 2 }} data-testid="organization-info">
            <Typography id="organization-info-heading" variant="h6" component="h2" gutterBottom>基本情報</Typography>
            {can_write ? (
                <Box component="form" noValidate onSubmit={(event: FormEvent) => void submit(event)} aria-labelledby="organization-info-heading" data-testid="organization-rename-form" sx={{ maxWidth: 560 }}>
                    <Stack spacing={2}>
                        <TextField
                            label="組織名"
                            required
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                            error={error !== undefined}
                            helperText={error}
                            inputRef={input_ref}
                            slotProps={{ htmlInput: { 'data-testid': 'organization-rename-name', autoComplete: 'off' } }}
                        />
                        <Box>
                            <Button
                                type="submit"
                                variant="contained"
                                disabled={pending || name.trim() === organization.name}
                                startIcon={pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                                data-testid="organization-rename-submit"
                            >
                                {pending ? '保存中…' : '名前を変更'}
                            </Button>
                        </Box>
                    </Stack>
                </Box>
            ) : (
                <Box component="dl" sx={{ m: 0, display: 'grid', gridTemplateColumns: 'max-content 1fr', columnGap: 3, rowGap: 1.5, alignItems: 'baseline' }}>
                    <Typography component="dt" variant="body2" color="text.secondary">組織名</Typography>
                    <Typography component="dd" variant="body1" sx={{ m: 0, overflowWrap: 'anywhere' }} data-testid="organization-info-name">{organization.name}</Typography>
                </Box>
            )}
            <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 2 }} data-testid="organization-info-created-at">作成日時: {formatDateTime(organization.created_at)}</Typography>
        </Paper>
    );
};

export default OrganizationRenameForm;
