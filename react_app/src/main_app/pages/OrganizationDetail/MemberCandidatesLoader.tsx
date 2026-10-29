/**
 * @desc メンバーの選択肢 (候補) の取得。メンバーの選択 UI を開いたときにだけ描画する (何も表示しない)
 * ユーザーの検索 API が無いため、候補にはテナントの全ユーザー (有効・無効) の全ページが必要になる。
 * メンバーの名前の表示は useUsersByIds (ID 指定の取得) で行い、この全件取得とは分ける。
 * 使うフック: useUserList (一覧)、useLoadAllPages (全ページの取得)。結果は onChange で呼び出し側の状態に渡す。
 */
import { useEffect } from 'react';
import type { UserRead } from '@/main_app/api/contract';
import type { AppErrorInfo } from '@/main_app/api/errors';
import { useLoadAllPages } from '@/main_app/components/useLoadAllPages';
import { useUserList } from '@/main_app/users/useUserList';

/** 1 回の取得の件数 (API の上限) */
const PAGE_LIMIT = 200;

/**
 * メンバーの候補の取得状態。idle は選択 UI を開く前 (まだ取得していない)。
 */
export type MemberCandidates = {
    status: 'idle' | 'loading' | 'success' | 'error';
    /** 取得済みのユーザー (有効・無効の両方)。 */
    users: readonly UserRead[];
    /** 取得の失敗 (先頭ページ、または続きのページ)。 */
    error: AppErrorInfo | null;
    /** 先頭から取り直す (idle では何もしない)。 */
    reload: () => void;
};

const NO_USERS: readonly UserRead[] = [];

/** 選択 UI を開く前の状態 */
export const IDLE_CANDIDATES: MemberCandidates = { status: 'idle', users: [], error: null, reload: () => undefined };

export type MemberCandidatesLoaderProps = {
    onChange: (candidates: MemberCandidates) => void;
};

export const MemberCandidatesLoader = ({ onChange }: MemberCandidatesLoaderProps) => {
    const list = useUserList({ limit: PAGE_LIMIT });
    const { is_complete } = useLoadAllPages(list);
    const error = list.error ?? list.load_more_error;
    const { reload } = list;
    // 取得前の items は描画のたびに新しい配列になるため、固定の空配列にする (effect が毎回走って無限に再描画しない)
    const items = list.status === 'success' ? list.items : NO_USERS;
    const status: MemberCandidates['status'] = error !== null ? 'error' : is_complete ? 'success' : 'loading';

    useEffect(() => {
        onChange({ status, users: items, error, reload });
    }, [onChange, status, items, error, reload]);

    return null;
};

export default MemberCandidatesLoader;
