/**
 * @description:
 * ToDo の担当者・公開先組織の選択肢を作るカスタムフック (作成・編集フォーム、一覧の絞り込みに使う)
 * ID 指定でユーザー・組織を引く API は無いため、既存の一覧フック (useUserList / useOrganizationList) の全ページを取得して選択肢にする
 * (1 テナントのユーザー・組織は数十件程度の前提。増えたら API 側に検索・ID 指定の取得を用意して置き換える)。
 * - 担当者: 有効なユーザーだけを新規の選択肢にする (AP-ASN-02)。既に割り当て済みの無効なユーザーは選択肢に残し is_active: false で示す
 *   (外すことはできる。AP-ASN-04)。一覧に無い割り当て済みのユーザーも ToDo の担当者の情報で残す
 * - 公開先組織: 有効な組織 (一覧は論理削除済みを除く) と、既に公開先の組織
*/
import { useMemo } from 'react';
import type { OrganizationRead, TodoAssigneeRead, TodoOrganizationRead, UserRead } from '@/main_app/api/contract';
import type { AppErrorInfo } from '@/main_app/api/errors';
import { useLoadAllPages } from '@/main_app/components/useLoadAllPages';
import { useOrganizationList } from '@/main_app/organizations/useOrganizationList';
import { useUserList } from '@/main_app/users/useUserList';
import type { CursorListState } from '@/shared/hooks/useCursorList';

/** 1 回の取得の件数 (API の上限) */
const PAGE_LIMIT = 200;

/**
 * 担当者の選択肢。
 */
export type TodoAssigneeOption = {
    user_id: string;
    display_name: string;
    /** false は無効化されたユーザー (既に割り当て済みのものだけが選択肢に残る。画面では「無効」と表示し、新たには選ばせない)。 */
    is_active: boolean;
    /** 現在の担当者か。 */
    is_assigned: boolean;
};

/**
 * 公開先組織の選択肢。
 */
export type TodoOrganizationOption = {
    organization_id: string;
    name: string;
    /** 現在の公開先か。 */
    is_selected: boolean;
};

/**
 * 選択肢の取得状態。
 */
export type TodoChoicesState<T> = {
    /** 全ページの取得が終わるまでは loading (取得済みの分は options に入る)。 */
    status: 'loading' | 'success' | 'error';
    options: T[];
    /** 取得の失敗 (先頭ページ、または続きのページ)。 */
    error: AppErrorInfo | null;
    /** 先頭から取り直す。 */
    reload: () => void;
};

/**
 * 担当者の選択肢を作る関数
 * @param {readonly UserRead[]} users テナントのユーザー (有効・無効の両方)
 * @param {readonly TodoAssigneeRead[]} assigned 現在の担当者
 * @returns {TodoAssigneeOption[]} 選択肢 (ユーザー一覧の順。一覧に無い担当者は末尾)
*/
export const todoAssigneeOptionsOf = (users: readonly UserRead[], assigned: readonly TodoAssigneeRead[]): TodoAssigneeOption[] => {
    const assigned_ids = new Set(assigned.map((assignee) => assignee.user_id));
    const known = new Set(users.map((user) => user.id));
    const from_users = users
        .filter((user) => user.is_active || assigned_ids.has(user.id))
        .map((user) => ({ user_id: user.id, display_name: user.display_name, is_active: user.is_active, is_assigned: assigned_ids.has(user.id) }));
    const missing = assigned
        .filter((assignee) => !known.has(assignee.user_id))
        .map((assignee) => ({ user_id: assignee.user_id, display_name: assignee.display_name, is_active: assignee.is_active, is_assigned: true }));
    return [...from_users, ...missing];
};

/**
 * 公開先組織の選択肢を作る関数
 * @param {readonly OrganizationRead[]} organizations テナントの組織 (論理削除済みを除く)
 * @param {readonly TodoOrganizationRead[]} selected 現在の公開先
 * @returns {TodoOrganizationOption[]} 選択肢 (組織一覧の順。一覧に無い公開先は末尾)
*/
export const todoOrganizationOptionsOf = (organizations: readonly OrganizationRead[], selected: readonly TodoOrganizationRead[]): TodoOrganizationOption[] => {
    const selected_ids = new Set(selected.map((organization) => organization.id));
    const known = new Set(organizations.map((organization) => organization.id));
    return [
        ...organizations.map((organization) => ({ organization_id: organization.id, name: organization.name, is_selected: selected_ids.has(organization.id) })),
        ...selected.filter((organization) => !known.has(organization.id)).map((organization) => ({ organization_id: organization.id, name: organization.name, is_selected: true })),
    ];
};

/**
 * 全ページ取得中の一覧から、取得状態を作る関数
 * @param {CursorListState<I>} list 一覧
 * @param {boolean} is_complete 全ページを取得し終えた
 * @param {T[]} options 選択肢
 * @returns {TodoChoicesState<T>} 取得状態
*/
const choicesStateOf = <T, I>(list: CursorListState<I>, is_complete: boolean, options: T[]): TodoChoicesState<T> => {
    const error = list.error ?? list.load_more_error;
    if (error !== null) return { status: 'error', options, error, reload: list.reload };
    return { status: is_complete ? 'success' : 'loading', options, error: null, reload: list.reload };
};

const NO_ASSIGNEES: readonly TodoAssigneeRead[] = [];
const NO_ORGANIZATIONS: readonly TodoOrganizationRead[] = [];

/**
 * 担当者の選択肢を取得するカスタムフック (AppAuthProvider の内側で使う)
 * @param {readonly TodoAssigneeRead[]} assigned 現在の担当者 (作成・絞り込みでは省略)
 * @returns {TodoChoicesState<TodoAssigneeOption>} 選択肢の取得状態
*/
export const useTodoAssigneeChoices = (assigned: readonly TodoAssigneeRead[] = NO_ASSIGNEES): TodoChoicesState<TodoAssigneeOption> => {
    const list = useUserList({ limit: PAGE_LIMIT });
    const { is_complete } = useLoadAllPages(list);
    const options = useMemo(() => todoAssigneeOptionsOf(list.items, assigned), [list.items, assigned]);
    return choicesStateOf(list, is_complete, options);
};

/**
 * 公開先組織の選択肢を取得するカスタムフック (AppAuthProvider の内側で使う)
 * @param {readonly TodoOrganizationRead[]} selected 現在の公開先 (作成・絞り込みでは省略)
 * @returns {TodoChoicesState<TodoOrganizationOption>} 選択肢の取得状態
*/
export const useTodoOrganizationChoices = (selected: readonly TodoOrganizationRead[] = NO_ORGANIZATIONS): TodoChoicesState<TodoOrganizationOption> => {
    const list = useOrganizationList({ limit: PAGE_LIMIT });
    const { is_complete } = useLoadAllPages(list);
    const options = useMemo(() => todoOrganizationOptionsOf(list.items, selected), [list.items, selected]);
    return choicesStateOf(list, is_complete, options);
};
