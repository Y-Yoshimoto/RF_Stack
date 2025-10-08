// vitestの動作環境確認サンプルコード
import { it, expect, describe } from 'vitest';

// テスト対象の関数
import id from '.';

// テストコード
describe('Vitest 環境確認', () => {
    it('サンプルテスト', () => expect(id(1)).toBe(1));
});
