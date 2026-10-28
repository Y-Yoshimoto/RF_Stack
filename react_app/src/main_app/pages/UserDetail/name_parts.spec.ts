// 表示名の分割のテスト
import { describe, expect, it } from 'vitest';
import { namePartsOf } from './name_parts';

describe('namePartsOf', () => {
    it('"{名} {姓}" を名と姓に分ける', () => {
        expect(namePartsOf('Taro Yamada')).toEqual({ first_name: 'Taro', last_name: 'Yamada' });
    });

    it('空白が無ければ全体を名とし、姓は空にする', () => {
        expect(namePartsOf('alpha-admin')).toEqual({ first_name: 'alpha-admin', last_name: '' });
    });

    it('最初の空白で分け、残りを姓とする (前後の空白は除く)', () => {
        expect(namePartsOf(' Mary Ann Smith ')).toEqual({ first_name: 'Mary', last_name: 'Ann Smith' });
    });
});
