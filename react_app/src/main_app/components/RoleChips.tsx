/**
 * @desc ロールの表示 (Chip の並び。表示名は layouts/AppLayout/labels.tsx のロール表示名)
 */
import { Chip, Stack, Typography } from '@mui/material';
import { appRoleLabelsOf } from '@/main_app/layouts/AppLayout/labels';

export type RoleChipsProps = {
    roles: readonly string[];
    test_id: string;
};

export const RoleChips = ({ roles, test_id }: RoleChipsProps) => {
    if (roles.length === 0) return <Typography variant="body2" color="text.secondary" data-testid={test_id}>—</Typography>;
    return (
        <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }} data-testid={test_id}>
            {appRoleLabelsOf([...roles]).map((label) => <Chip key={label} size="small" label={label} />)}
        </Stack>
    );
};

export default RoleChips;
