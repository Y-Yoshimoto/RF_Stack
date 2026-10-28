// 認証後レイアウトのナビゲーション項目 (プレーン固有のロジックは含めない。項目の一覧は各プレーンのレイアウトが決める)
import type { ReactNode } from 'react';

export type NavItem = {
    /** 項目の識別子 (data-testid の `nav-${id}` に使う)。 */
    id: string;
    /** 表示名。 */
    label: string;
    /** 遷移先のパス。null は未実装の画面で、押せない表示 (準備中) にする。 */
    to: string | null;
    /** 先頭の項目など、配下のパスでは現在地として扱わない場合は true。 */
    end?: boolean;
    /** 表示名の前に出すアイコン (装飾)。 */
    icon?: ReactNode;
};
