// テナントコード (tenant_code) の形式と予約語 (01 §5.1、§5.2)
// 予約語の一覧の正は FastAPI の modules/tenancy/tenant_code.py (RESERVED_TENANT_CODES)。
// React 側ではこのファイルの 1 箇所だけに写し、変更する場合はバックエンドと同時に揃える。
// フロントでの判定は「API を呼ぶまでもなく弾ける URL を弾く」ための補助であり、
// 最終的な判定は公開のテナント存在確認 API (予約語・形式不正は 404) が行う。

/**
 * テナントコードの形式 (3〜32 文字、英小文字・数字・ハイフン。先頭・末尾・連続のハイフンは不可)。
 * FastAPI の TENANT_CODE_PATTERN と同じ。
 */
export const TENANT_CODE_PATTERN = /^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){2,31}$/;

/**
 * 予約語。URL の第 1 セグメントがこれらの場合はテナントとして解釈しない。
 */
export const RESERVED_TENANT_CODES: ReadonlySet<string> = new Set([
    'cp', 'api', 'auth', 'login', 'logout', 'callback', 'dev-login', 'link',
    'assets', 'static', 'public', 'health', 'admin', 'keycloak',
    'www', 'app', 'docs', 'help', 'support', 'status', 'signup', 'settings',
]);

/**
 * テナントコードとして受け付けられない理由。
 * - empty: 未入力
 * - format: 形式違反 (大文字を含む場合も形式違反。正規化はしない)
 * - reserved: 予約語
 */
export type TenantCodeViolation = 'empty' | 'format' | 'reserved';

/**
 * 予約語かどうかを判定する関数 (大文字小文字を区別しない)
 * @param {string} value 判定対象
 * @returns {boolean} 予約語なら true
*/
export const isReservedTenantCode = (value: string): boolean => RESERVED_TENANT_CODES.has(value.toLowerCase());

/**
 * テナントコードとして受け付けられない理由を返す関数
 * 形式を先に、予約語を後に判定する (FastAPI の tenant_code_violation と同じ順)。
 * @param {string} value 判定対象 (URL のセグメントや入力値)
 * @returns {TenantCodeViolation | null} 理由。受け付けられる場合は null
*/
export const tenantCodeViolationOf = (value: string): TenantCodeViolation | null => {
    if (value === '') return 'empty';
    if (!TENANT_CODE_PATTERN.test(value)) return 'format';
    if (isReservedTenantCode(value)) return 'reserved';
    return null;
};

/**
 * 利用者の入力をテナントコードとして扱える形に整える関数 (前後の空白を除き、小文字にする)
 * URL のセグメントには使わない (URL の大文字は形式違反として扱う)。
 * @param {string} input 入力値
 * @returns {string} 整えた値
*/
export const normalizeTenantCodeInput = (input: string): string => input.trim().toLowerCase();
