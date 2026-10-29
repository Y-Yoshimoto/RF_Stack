// ToDo の日付の扱い (純粋関数。ブラウザのタイムゾーンのローカル日付を `YYYY-MM-DD` で扱う)
// 画面 (pages/TodoCommon/TodoBadges.tsx は再公開している) とフック (useTodoSummary) が共通で使う。
import type { TodoStatus } from '@/main_app/api/contract';

/**
 * 今日の日付 (ブラウザのタイムゾーン) を `YYYY-MM-DD` で返す関数
 * @param {Date} now 現在時刻
 * @returns {string} 今日の日付
*/
export const todayOf = (now: Date = new Date()): string => `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;

/**
 * 期限切れかを判定する関数 (完了していない ToDo の期限が今日より前)
 * @param {string | null} due_date 期限
 * @param {TodoStatus} status ステータス
 * @param {string} today 今日の日付
 * @returns {boolean} 期限切れなら true
*/
export const isOverdue = (due_date: string | null, status: TodoStatus, today: string = todayOf()): boolean => due_date !== null && status !== 'done' && due_date < today;

/**
 * 日付 (`YYYY-MM-DD`) に日数を足す関数 (暦どおり。月末・閏年をまたぐ)
 * @param {string} date 日付
 * @param {number} days 日数 (負なら前の日)
 * @returns {string} 日付
*/
export const addDays = (date: string, days: number): string => {
    const [year, month, day] = date.split('-').map(Number);
    const shifted = new Date(Date.UTC(year, month - 1, day + days));
    return shifted.toISOString().slice(0, 10);
};

/**
 * 期限間近かを判定する関数 (完了していない ToDo の期限が today 〜 until。§10 #21)
 * @param {string | null} due_date 期限
 * @param {TodoStatus} status ステータス
 * @param {string} today 今日の日付
 * @param {string} until 期限間近の終端 (この日を含む。要約の due_soon_until)
 * @returns {boolean} 期限間近なら true
*/
export const isDueSoon = (due_date: string | null, status: TodoStatus, today: string, until: string): boolean => due_date !== null && status !== 'done' && today <= due_date && due_date <= until;
