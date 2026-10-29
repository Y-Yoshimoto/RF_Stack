/**
 * @description:
 * 一定時間だけ保持する値 (一時パスワードなど、一度だけ表示する秘密) のカスタムフック (プレーン共通)
 * - set から ttl_ms を過ぎると null に戻る。clear でも消える。アンマウントで状態ごと破棄される
 * - 値は React の状態にだけ置き、ストレージ・ログ・URL には出さない (呼び出し側も出さないこと)
*/
import { useCallback, useEffect, useState } from 'react';

/** 一度だけ表示する秘密を保持する既定の時間 (ミリ秒)。画面は表示を閉じたら clear を呼ぶこと */
export const DEFAULT_SECRET_TTL_MS = 10 * 60 * 1000;

/**
 * 一定時間だけ保持する値のカスタムフック
 * @param {number} ttl_ms 保持する時間 (ミリ秒)
 * @returns {{ value: T | null, set: (value: T) => void, clear: () => void }} 値と操作
*/
export const useEphemeralValue = <T,>(ttl_ms: number = DEFAULT_SECRET_TTL_MS) => {
    const [value, setValue] = useState<T | null>(null);

    useEffect(() => {
        if (value === null) return;
        const timer = setTimeout(() => setValue(null), ttl_ms);
        return () => clearTimeout(timer);
    }, [value, ttl_ms]);

    const set = useCallback((next: T) => setValue(next), []);
    const clear = useCallback(() => setValue(null), []);
    return { value, set, clear };
};

export default useEphemeralValue;
