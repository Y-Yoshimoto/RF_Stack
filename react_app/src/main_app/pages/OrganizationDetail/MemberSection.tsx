/**
 * @desc 組織のメンバー (tenant_admin は複数選択して置き換え、member は一覧の閲覧のみ)
 * メンバーは API ではユーザー ID でしか分からないため、名前はテナントの全ユーザー (useAllUsers) から引く。
 * 一覧に無い ID (取得後に削除されたユーザーなど) も、選択から外さずに保持して送る。
 */
import { useState } from 'react';
import { Autocomplete, Box, Button, Chip, CircularProgress, Paper, Stack, TextField, Typography } from '@mui/material';
import type { UserRead } from '@/main_app/api/contract';

export type MemberSectionProps = {
    /** 現在のメンバーのユーザー ID。 */
    member_ids: readonly string[];
    /** テナントの全ユーザー (名前を引く・選択肢)。 */
    users: readonly UserRead[];
    can_write: boolean;
    /** メンバーを置き換える (成功したら true)。 */
    onSave: (user_ids: string[]) => Promise<boolean>;
    pending: boolean;
};

type MemberOption = {
    id: string;
    label: string;
};

/**
 * ユーザーを選択肢にする関数 (メールと無効の表示を含める)
 * @param {UserRead} user ユーザー
 * @returns {MemberOption} 選択肢
*/
const optionOfUser = (user: UserRead): MemberOption => ({
    id: user.id,
    label: `${user.display_name}${user.email ? ` (${user.email})` : ''}${user.is_active ? '' : ' [無効]'}`,
});

/**
 * 一覧に無いユーザー ID の選択肢を作る関数
 * @param {string} user_id ユーザー ID
 * @returns {MemberOption} 選択肢
*/
const unknownOptionOf = (user_id: string): MemberOption => ({ id: user_id, label: `不明なユーザー (${user_id.slice(0, 8)})` });

/**
 * ID の集合が等しいかを判定する関数
 * @param {readonly string[]} a 一方
 * @param {readonly string[]} b 他方
 * @returns {boolean} 等しければ true
*/
const sameIds = (a: readonly string[], b: readonly string[]): boolean => a.length === b.length && a.every((id) => b.includes(id));

export const MemberSection = ({ member_ids, users, can_write, onSave, pending }: MemberSectionProps) => {
    const [selected_ids, setSelectedIds] = useState<string[]>([...member_ids]);
    const options = users.map(optionOfUser);
    const option_by_id = new Map(options.map((option) => [option.id, option]));
    const optionOf = (user_id: string): MemberOption => option_by_id.get(user_id) ?? unknownOptionOf(user_id);
    // 一覧に無いメンバーも選択肢に含める (含めないと選択済みの値として表示できない)
    const all_options = [...options, ...member_ids.filter((id) => !option_by_id.has(id)).map(unknownOptionOf)];
    const is_changed = !sameIds(selected_ids, member_ids);

    return (
        <Paper variant="outlined" component="section" aria-labelledby="organization-members-heading" sx={{ p: 2 }} data-testid="organization-members">
            <Typography id="organization-members-heading" variant="h6" component="h2" gutterBottom>メンバー ({member_ids.length} 人)</Typography>
            {can_write ? (
                <Stack spacing={2} sx={{ maxWidth: 640 }}>
                    <Autocomplete<MemberOption, true>
                        multiple
                        disableCloseOnSelect
                        filterSelectedOptions
                        options={all_options}
                        value={selected_ids.map(optionOf)}
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
            ) : member_ids.length === 0 ? (
                <Typography variant="body2" color="text.secondary" data-testid="organization-members-empty">メンバーはいません。</Typography>
            ) : (
                <Box component="ul" sx={{ m: 0, pl: 3 }} data-testid="organization-members-list">
                    {member_ids.map((id) => <li key={id} data-testid={`organization-member-${id}`}>{optionOf(id).label}</li>)}
                </Box>
            )}
        </Paper>
    );
};

export default MemberSection;
