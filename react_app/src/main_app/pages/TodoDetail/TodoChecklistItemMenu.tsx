/**
 * @desc チェックリスト項目のメニュー (キーボードで操作できる「上へ移動」「下へ移動」と削除。並べ替えのドラッグの代替手段)
 */
import { forwardRef, useState } from 'react';
import { IconButton, ListItemIcon, ListItemText, Menu, MenuItem } from '@mui/material';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import DeleteIcon from '@mui/icons-material/Delete';
import MoreVertIcon from '@mui/icons-material/MoreVert';

export type TodoChecklistItemMenuProps = {
    item_id: string;
    title: string;
    is_first: boolean;
    is_last: boolean;
    onMove: (delta: -1 | 1) => void;
    onRemove: () => void;
};

export const TodoChecklistItemMenu = forwardRef<HTMLButtonElement, TodoChecklistItemMenuProps>(({ item_id, title, is_first, is_last, onMove, onRemove }, button_ref) => {
    const [anchor, setAnchor] = useState<HTMLElement | null>(null);
    const menu_id = `todo-checklist-item-${item_id}-menu`;
    const act = (action: () => void) => () => {
        setAnchor(null);
        action();
    };
    return (
        <>
            <IconButton
                ref={button_ref}
                size="small"
                aria-label={`「${title}」のその他の操作 (並べ替え・削除)`}
                aria-haspopup="menu"
                aria-expanded={anchor !== null}
                aria-controls={anchor !== null ? menu_id : undefined}
                onClick={(event) => setAnchor(event.currentTarget)}
                data-testid={`todo-checklist-item-${item_id}-menu-button`}
            >
                <MoreVertIcon fontSize="small" />
            </IconButton>
            <Menu id={menu_id} anchorEl={anchor} open={anchor !== null} onClose={() => setAnchor(null)} data-testid={menu_id}>
                <MenuItem disabled={is_first} onClick={act(() => onMove(-1))} data-testid={`todo-checklist-item-${item_id}-move-up`}>
                    <ListItemIcon><ArrowUpwardIcon fontSize="small" /></ListItemIcon>
                    <ListItemText>上へ移動</ListItemText>
                </MenuItem>
                <MenuItem disabled={is_last} onClick={act(() => onMove(1))} data-testid={`todo-checklist-item-${item_id}-move-down`}>
                    <ListItemIcon><ArrowDownwardIcon fontSize="small" /></ListItemIcon>
                    <ListItemText>下へ移動</ListItemText>
                </MenuItem>
                <MenuItem onClick={act(onRemove)} sx={{ color: 'error.main' }} data-testid={`todo-checklist-item-${item_id}-delete`}>
                    <ListItemIcon sx={{ color: 'inherit' }}><DeleteIcon fontSize="small" /></ListItemIcon>
                    <ListItemText>削除</ListItemText>
                </MenuItem>
            </Menu>
        </>
    );
});
TodoChecklistItemMenu.displayName = 'TodoChecklistItemMenu';

export default TodoChecklistItemMenu;
