// Vitestのテストコード
import { describe, it, expect } from 'vitest';

// テスト対象の関数
describe('Vitestの実行環境チェック', () => {
    const add = (a: number, b: number) => a + b;
    it('関数動作確認', () => {
        expect(add(1, 2)).toBe(3);
    });
});
