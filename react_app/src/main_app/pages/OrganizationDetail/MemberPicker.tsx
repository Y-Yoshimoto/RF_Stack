/**
 * @desc 組織のメンバーの選択 (tenant_admin 用。複数選択して置き換える)
 * 選択済みのメンバーの名前は呼び出し側が ID 指定で取得したもの (members) を使い、候補 (全ユーザー) は選択 UI を開いたときに初めて取得する。
 * 候補に無い選択済みの ID (取得後に削除されたユーザーなど) も、選択から外さずに保持して送る。
 */
import { useCallback, useState } from 'react';
import { Autocomplete, Box, Button, Chip, CircularProgress, Stack, TextField } from '@mui/material';
import type { UserRead } from '@/main_app/api/contract';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import { IDLE_CANDIDATES, MemberCandidatesLoader, type MemberCandidates } from './MemberCandidatesLoader';
import { optionOfUser, sameIds, unknownOptionOf, type MemberOption } from './member_options';

export type MemberPickerProps = {
    /** 現在のメンバーのユーザー ID。 */
    member_ids: readonly string[];
    /** 現在のメンバーのユーザー (ID 指定で取得したもの。見つからない ID は含まれない)。 */
    members: readonly UserRead[];
    /** メンバーを置き換える (成功したら true)。 */
    onSave: (user_ids: string[]) => Promise<boolean>;
    pending: boolean;
};

export const MemberPicker = ({ member_ids, members, onSave, pending }: MemberPickerProps) => {
    const [selected_ids, setSelectedIds] = useState<string[]>([...member_ids]);
    const [is_opened, setIsOpened] = useState(false);
    const [candidates, setCandidates] = useState<MemberCandidates>(IDLE_CANDIDATES);
    const handleCandidates = useCallback((next: MemberCandidates) => setCandidates(next), []);

    // 候補と現在のメンバーを合わせる (候補を取得する前でも、選択済みの値を表示できる)
    const option_by_id = new Map<string, MemberOption>();
    for (const user of [...members, ...candidates.users]) option_by_id.set(user.id, optionOfUser(user));
    const optionOf = (user_id: string): MemberOption => option_by_id.get(user_id) ?? unknownOptionOf(user_id);
    const all_options = [...option_by_id.values(), ...member_ids.filter((id) => !option_by_id.has(id)).map(unknownOptionOf)];
    const is_changed = !sameIds(selected_ids, member_ids);
    const is_loading_candidates = is_opened && (candidates.status === 'idle' || candidates.status === 'loading');

    return (
        <Stack spacing={2} sx={{ maxWidth: 640 }}>
            {is_opened && <MemberCandidatesLoader onChange={handleCandidates} />}
            <Autocomplete<MemberOption, true>
                multiple
                disableCloseOnSelect
                filterSelectedOptions
                options={all_options}
                value={selected_ids.map(optionOf)}
                onOpen={() => setIsOpened(true)}
                loading={is_loading_candidates}
                loadingText="ユーザーを読み込み中…"
                onChange={(_event, next) => setSelectedIds(next.map((option) => option.id))}
                getOptionLabel={(option) => option.label}
                isOptionEqualToValue={(option, value) => option.id === value.id}
                noOptionsText="該当するユーザーがいません"
                renderValue={(value, getItemProps) => value.map((option, index) => {
                    const { key, ...item_props } = getItemProps({ index });
                    return <Chip key={key} size="small" label={option.label} {...item_props} />;
                })}
                renderInput={(params) => (
                    <TextField
                        {...params}
                        label="メンバー"
                        placeholder="ユーザーを検索して追加"
                        helperText="名前またはメールアドレスで検索できます。変更は「メンバーを保存」で反映されます。"
                        slotProps={{ ...params.slotProps, htmlInput: { ...params.slotProps.htmlInput, 'data-testid': 'organization-members-input' } as object }}
                    />
                )}
                data-testid="organization-members-select"
            />
            {candidates.status === 'error' && candidates.error && (
                <AppErrorAlert error={candidates.error} test_id="organization-candidates-error" onReload={candidates.reload} always_retry />
            )}
            <Box>
                <Button
                    variant="contained"
                    disabled={pending || !is_changed}
                    onClick={() => void onSave(selected_ids)}
                    startIcon={pending ? <CircularProgress size={16} color="inherit" aria-hidden /> : undefined}
                    data-testid="organization-members-save"
                >
                    {pending ? '保存中…' : 'メンバーを保存'}
                </Button>
            </Box>
        </Stack>
    );
};

export default MemberPicker;
