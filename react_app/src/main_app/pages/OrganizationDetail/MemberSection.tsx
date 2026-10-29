/**
 * @desc 組織のメンバー (tenant_admin は複数選択して置き換え、member は一覧の閲覧のみ)
 * メンバーの名前は、メンバーの ID だけを指定して取得したユーザー (useUsersByIds。呼び出し側で取得) から引く。
 * テナントの全ユーザーの取得 (選択肢) は、tenant_admin が選択 UI を開いたときだけ行う (MemberPicker)。
 * 名前を引けないメンバー (存在しない ID など) は「不明なユーザー」と表示する。
 */
import { Box, CircularProgress, Paper, Typography } from '@mui/material';
import { AppErrorAlert } from '@/main_app/components/AppErrorAlert';
import type { UsersByIdsState } from '@/main_app/users/useUsersByIds';
import { MemberPicker } from './MemberPicker';
import { optionOfUser, unknownOptionOf } from './member_options';

export type MemberSectionProps = {
    /** 現在のメンバーのユーザー ID。 */
    member_ids: readonly string[];
    /** メンバーのユーザーの取得状態 (useUsersByIds(member_ids))。 */
    members: UsersByIdsState;
    can_write: boolean;
    /** メンバーを置き換える (成功したら true)。 */
    onSave: (user_ids: string[]) => Promise<boolean>;
    pending: boolean;
};

export const MemberSection = ({ member_ids, members, can_write, onSave, pending }: MemberSectionProps) => {
    const labelOf = (user_id: string): string => {
        const user = members.userOf(user_id);
        return user === null ? unknownOptionOf(user_id).label : optionOfUser(user).label;
    };

    return (
        <Paper variant="outlined" component="section" aria-labelledby="organization-members-heading" sx={{ p: 2 }} data-testid="organization-members">
            <Typography id="organization-members-heading" variant="h6" component="h2" gutterBottom>メンバー ({member_ids.length} 人)</Typography>
            {members.status === 'loading' && (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                    <CircularProgress size={24} aria-label="メンバーを読み込み中" data-testid="organization-members-loading" />
                </Box>
            )}
            {members.status === 'error' && members.error && <AppErrorAlert error={members.error} test_id="organization-members-error" onReload={members.reload} always_retry />}
            {members.status === 'success' && can_write && <MemberPicker member_ids={member_ids} members={members.items} onSave={onSave} pending={pending} />}
            {members.status === 'success' && !can_write && (member_ids.length === 0 ? (
                <Typography variant="body2" color="text.secondary" data-testid="organization-members-empty">メンバーはいません。</Typography>
            ) : (
                <Box component="ul" sx={{ m: 0, pl: 3 }} data-testid="organization-members-list">
                    {member_ids.map((id) => <li key={id} data-testid={`organization-member-${id}`}>{labelOf(id)}</li>)}
                </Box>
            ))}
        </Paper>
    );
};

export default MemberSection;
