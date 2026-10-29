/**
 * @desc 閲覧範囲 (private / organization / tenant) と、organization の公開先組織の選択
 * organization を選ぶと組織の選択欄を出す (1 つ以上が必須: AP-VIS-07)。作成と詳細の編集で共有する。
 */
import { Checkbox, CircularProgress, FormControl, FormControlLabel, FormGroup, FormHelperText, FormLabel, Radio, RadioGroup, Stack, Typography } from '@mui/material';
import { TODO_VISIBILITIES, type TodoVisibility } from '@/main_app/api/contract';
import type { AppErrorInfo } from '@/main_app/api/errors';
import type { TodoOrganizationOption } from '@/main_app/todos/useTodoChoices';
import { TODO_VISIBILITY_HINTS, TODO_VISIBILITY_LABELS } from './todo_labels';
import { TodoErrorAlert } from './TodoErrorAlert';

/**
 * 閲覧範囲の入力値。
 */
export type AudienceValue = {
    visibility: TodoVisibility;
    organization_ids: string[];
};

export type AudienceFieldsProps = {
    value: AudienceValue;
    onChange: (value: AudienceValue) => void;
    organizations: readonly TodoOrganizationOption[];
    organizations_status: 'loading' | 'success' | 'error';
    organizations_error?: AppErrorInfo | null;
    onReloadOrganizations?: () => void;
    /** 公開先組織の検証エラー (organization で 1 つも選んでいない)。 */
    organizations_error_text?: string;
    disabled?: boolean;
    /** data-testid の接頭辞。 */
    test_id: string;
};

export const AudienceFields = ({ value, onChange, organizations, organizations_status, organizations_error = null, onReloadOrganizations, organizations_error_text, disabled = false, test_id }: AudienceFieldsProps) => {
    const toggleOrganization = (organization_id: string, checked: boolean) => {
        const ids = checked ? [...value.organization_ids, organization_id] : value.organization_ids.filter((known) => known !== organization_id);
        onChange({ ...value, organization_ids: ids });
    };
    return (
        <Stack spacing={2}>
            <FormControl component="fieldset" disabled={disabled} data-testid={`${test_id}-visibility`}>
                <FormLabel component="legend" id={`${test_id}-visibility-label`}>閲覧範囲</FormLabel>
                <RadioGroup
                    aria-labelledby={`${test_id}-visibility-label`}
                    value={value.visibility}
                    onChange={(event) => onChange({ ...value, visibility: event.target.value as TodoVisibility })}
                >
                    {TODO_VISIBILITIES.map((visibility) => (
                        <FormControlLabel
                            key={visibility}
                            value={visibility}
                            control={<Radio slotProps={{ input: { 'data-testid': `${test_id}-visibility-${visibility}` } as object }} />}
                            label={(
                                <>
                                    {TODO_VISIBILITY_LABELS[visibility]}
                                    <Typography variant="body2" color="text.secondary" component="span">{` — ${TODO_VISIBILITY_HINTS[visibility]}`}</Typography>
                                </>
                            )}
                        />
                    ))}
                </RadioGroup>
            </FormControl>

            {value.visibility === 'organization' && (
                <FormControl component="fieldset" required disabled={disabled} error={organizations_error_text !== undefined} data-testid={`${test_id}-organizations`}>
                    <FormLabel component="legend">公開先の組織</FormLabel>
                    {organizations_status === 'loading' && <CircularProgress size={20} aria-label="組織を読み込み中" />}
                    {organizations_error && <TodoErrorAlert error={organizations_error} test_id={`${test_id}-organizations-load-error`} onReload={onReloadOrganizations} always_retry />}
                    <FormGroup>
                        {organizations.map((organization) => (
                            <FormControlLabel
                                key={organization.organization_id}
                                label={organization.name}
                                control={(
                                    <Checkbox
                                        checked={value.organization_ids.includes(organization.organization_id)}
                                        onChange={(event) => toggleOrganization(organization.organization_id, event.target.checked)}
                                        slotProps={{ input: { 'data-testid': `${test_id}-organization-${organization.organization_id}` } as object }}
                                    />
                                )}
                            />
                        ))}
                    </FormGroup>
                    {organizations_status === 'success' && organizations.length === 0 && <FormHelperText>選べる組織がありません。</FormHelperText>}
                    <FormHelperText data-testid={`${test_id}-organizations-help`} role={organizations_error_text !== undefined ? 'alert' : undefined}>
                        {organizations_error_text ?? '1 つ以上の組織を選んでください。'}
                    </FormHelperText>
                </FormControl>
            )}
        </Stack>
    );
};

export default AudienceFields;
