// チェックリストの画面で使う、表示用の計算と文言 (純粋関数。AP-CHK)
import type { Announcements } from '@dnd-kit/core';
import type { TodoChecklistItemRead } from '@/main_app/api/contract';
import { formatDateTime } from '@/main_app/components/format';
import { todoUserTextOf } from './todo_user_text';

/**
 * 進捗の割合を返す関数 (項目が無ければ 0)
 * @param {number} done 完了数
 * @param {number} total 総数
 * @returns {number} 0〜100 の整数
*/
export const checklistPercentOf = (done: number, total: number): number => (total <= 0 ? 0 : Math.round((done / total) * 100));

/**
 * 進捗を文にする関数
 * @param {number} done 完了数
 * @param {number} total 総数
 * @returns {string} 「3 / 5 完了」の形
*/
export const checklistProgressTextOf = (done: number, total: number): string => `${done} / ${total} 完了`;

/**
 * 項目を表示する順に並べる関数 (並べ替えの結果を待つ間は、移した後の並びを先に出す)
 * @param {readonly TodoChecklistItemRead[]} items サーバーの並び
 * @param {readonly string[] | null} order 先に出す項目 ID の並び (無ければ null)
 * @returns {TodoChecklistItemRead[]} 表示する並び (order が項目と食い違えばサーバーの並び)
*/
export const orderChecklistItems = (items: readonly TodoChecklistItemRead[], order: readonly string[] | null): TodoChecklistItemRead[] => {
    if (order === null || order.length !== items.length) return [...items];
    const by_id = new Map(items.map((item) => [item.id, item]));
    const ordered = order.map((id) => by_id.get(id));
    return ordered.every((item): item is TodoChecklistItemRead => item !== undefined) ? ordered : [...items];
};

/**
 * 完了した人と日時を文にする関数
 * @param {TodoChecklistItemRead} item 項目
 * @returns {string | null} 「Taro Yamada が 2026/10/02 9:00 に完了」の形 (未完了なら null)
*/
export const checklistDoneTextOf = (item: TodoChecklistItemRead): string | null => {
    if (!item.is_done) return null;
    const who = item.done_by !== null ? `${todoUserTextOf(item.done_by)} が ` : '';
    return `${who}${formatDateTime(item.done_at)} に完了`;
};

/**
 * 項目を移した結果の読み上げ文を返す関数
 * @param {string} title 項目名
 * @param {number} index 移した後の位置 (0 から)
 * @param {number} count 項目数
 * @returns {string} 読み上げ文
*/
export const checklistMovedTextOf = (title: string, index: number, count: number): string => `「${title}」を ${index + 1} 番目に移動しました (全 ${count} 件)`;

/** ドラッグ & ドロップの操作方法の説明 (スクリーンリーダー向け) */
export const CHECKLIST_DRAG_INSTRUCTIONS = 'ドラッグハンドルでスペースキーを押すと項目を持ち上げます。矢印キーの上下で移動し、スペースキーで置きます。Esc で取り消します。メニューの「上へ移動」「下へ移動」でも並べ替えられます。';

/**
 * ドラッグ & ドロップの読み上げ文を作る関数 (dnd-kit の accessibility.announcements)
 * @param {readonly TodoChecklistItemRead[]} items 表示中の項目
 * @returns {Announcements} 読み上げ文
*/
export const checklistAnnouncementsOf = (items: readonly TodoChecklistItemRead[]): Announcements => {
    const titleOf = (id: string | number): string => items.find((item) => item.id === id)?.title ?? '項目';
    const positionOf = (id: string | number): number => items.findIndex((item) => item.id === id) + 1;
    return {
        onDragStart: ({ active }) => `「${titleOf(active.id)}」を持ち上げました。現在 ${positionOf(active.id)} 番目です (全 ${items.length} 件)`,
        onDragOver: ({ active, over }) => (over ? `「${titleOf(active.id)}」を ${positionOf(over.id)} 番目の位置に移動しています` : `「${titleOf(active.id)}」は並べ替えの範囲の外です`),
        onDragEnd: ({ active, over }) => (over ? `「${titleOf(active.id)}」を ${positionOf(over.id)} 番目に置きました` : `「${titleOf(active.id)}」を元の位置に戻しました`),
        onDragCancel: ({ active }) => `並べ替えを取り消しました。「${titleOf(active.id)}」は元の位置です`,
    };
};
