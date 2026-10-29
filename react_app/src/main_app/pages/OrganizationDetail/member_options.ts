// 組織のメンバーの選択肢 (表示ラベル) を作る関数
import type { UserRead } from '@/main_app/api/contract';

/** メンバーの選択肢。 */
export type MemberOption = {
    id: string;
    label: string;
};

/**
 * ユーザーを選択肢にする関数 (メールと無効の表示を含める。無効は色だけでなく文字でも示す)
 * @param {UserRead} user ユーザー
 * @returns {MemberOption} 選択肢
*/
export const optionOfUser = (user: UserRead): MemberOption => ({
    id: user.id,
    label: `${user.display_name}${user.email ? ` (${user.email})` : ''}${user.is_active ? '' : ' [無効]'}`,
});

/**
 * 名前を引けないユーザー ID の選択肢を作る関数 (存在しない・他テナントの ID)
 * @param {string} user_id ユーザー ID
 * @returns {MemberOption} 選択肢
*/
export const unknownOptionOf = (user_id: string): MemberOption => ({ id: user_id, label: `不明なユーザー (${user_id.slice(0, 8)})` });

/**
 * ID の集合が等しいかを判定する関数
 * @param {readonly string[]} a 一方
 * @param {readonly string[]} b 他方
 * @returns {boolean} 等しければ true
*/
export const sameIds = (a: readonly string[], b: readonly string[]): boolean => a.length === b.length && a.every((id) => b.includes(id));
