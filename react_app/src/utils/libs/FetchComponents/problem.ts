// エラーレスポンス (RFC 9457 Problem Details) の共通型と関数
// 正は FastAPI 側の modules/errors/problem.py (ProblemDetails) と docs/architecture/03-conventions.md §2。
// FastAPI のエラーは application/problem+json で返り、フロントは code で分岐する (title / detail は利用者向けの日本語)。

//// Problem Details のメディアタイプ
export const PROBLEM_MEDIA_TYPE = 'application/problem+json';

//// フロントで分岐に使う共通のエラーコード (modules/errors/catalog.py の一部)
//// プレーン固有のコード (CP の払い出し等) は各プレーンの API 定義側で扱う。
export const PROBLEM_CODE = {
    // 401: 未認証・セッション切れ
    UNAUTHENTICATED: 'unauthenticated',
    SESSION_EXPIRED: 'session_expired',
    // 403: 権限不足・CSRF 検証失敗
    FORBIDDEN: 'forbidden',
    CSRF_VALIDATION_FAILED: 'csrf_validation_failed',
    // 403: AP のテナント (停止中・削除要求中 / それ以外は存在有無を推測させないため集約)
    TENANT_INACTIVE: 'tenant_inactive',
    TENANT_UNAVAILABLE: 'tenant_unavailable',
    // 404 / 422 / 412 / 428
    NOT_FOUND: 'not_found',
    VALIDATION_ERROR: 'validation_error',
    PRECONDITION_FAILED: 'precondition_failed',
    PRECONDITION_REQUIRED: 'precondition_required',
    // 400: If-Match の形式不正 (modules/api_common/etag.py)
    INVALID_IF_MATCH: 'invalid_if_match',
} as const;

//// 422 validation_error の errors[].code のうち、プレーン共通で分岐に使うもの (modules/api_common/pagination.py)
export const FIELD_ERROR_CODE = {
    /** cursor が壊れている・並び順が変わった (field: cursor)。先頭から取得し直す。 */
    INVALID_CURSOR: 'invalid_cursor',
} as const;

/**
 * 入力検証エラーの 1 件 (FastAPI の FieldError)。
 */
export type ProblemFieldError = {
    /** エラーのあった項目 (ドット区切り。例: `initial_admin.email`)。 */
    field: string;
    /** エラーの種類 (`snake_case`。例: `missing`, `string_too_long`)。 */
    code: string;
    /** 利用者向けのメッセージ (日本語)。 */
    message: string;
};

/**
 * エラーレスポンスの本文 (RFC 9457 Problem Details)。
 * 標準メンバー以外に、エンドポイント固有の拡張メンバー (例: 払い出し失敗の `tenant_id` / `step`、
 * 状態遷移の不正の `operation` / `current_status`) が付くことがある。
 */
export type ProblemDetails = {
    /** エラー種別の URI (`code` から機械的に作られる。解決できる URL とは限らない)。 */
    type: string;
    /** エラーの短い要約 (日本語)。 */
    title: string;
    /** HTTP ステータスコード。 */
    status: number;
    /** 利用者向けの説明 (日本語)。 */
    detail: string;
    /** エラーが発生したリクエストのパス。 */
    instance: string;
    /** 機械判定用のエラーコード (`snake_case`)。フロントはこれで分岐する。 */
    code: string;
    /** リクエスト ID (`X-Request-ID` ヘッダーと同じ)。 */
    request_id?: string | null;
    /** 入力検証エラーの詳細。無い場合は空配列。 */
    errors?: ProblemFieldError[];
    /** 拡張メンバー。 */
    [extension: string]: unknown;
};

/**
 * 値が Problem Details の形かどうかを判定する関数
 * @param {unknown} value 判定対象 (レスポンス本文など)
 * @returns {boolean} `code` (文字列) と `status` (数値) を持つ場合は true
*/
export const isProblemDetails = (value: unknown): value is ProblemDetails => {
    if (typeof value !== 'object' || value === null) return false;
    const candidate = value as { code?: unknown; status?: unknown };
    return typeof candidate.code === 'string' && typeof candidate.status === 'number';
};

/**
 * API がエラーステータス (2xx 以外) を返したことを表す例外。
 * `message` は従来どおり HTTP のステータステキストとし、Problem Details は `problem` に保持する。
 */
export class ApiError extends Error {
    /** HTTP ステータスコード。 */
    readonly status: number;
    /** レスポンス本文の Problem Details (problem+json でない応答では undefined)。 */
    readonly problem: ProblemDetails | undefined;

    constructor(status: number, message: string, problem?: ProblemDetails) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.problem = problem;
    }
}

/**
 * レスポンスから Problem Details を読み取る関数
 * Content-Type が application/problem+json でない場合や、本文が読めない場合は undefined を返す。
 * @param {Response} res レスポンス
 * @returns {Promise<ProblemDetails | undefined>} Problem Details
*/
export const readProblem = async (res: Response): Promise<ProblemDetails | undefined> => {
    const content_type = res.headers.get('Content-Type') ?? '';
    if (!content_type.toLowerCase().includes(PROBLEM_MEDIA_TYPE)) return undefined;
    try {
        const body: unknown = await res.json();
        return isProblemDetails(body) ? body : undefined;
    } catch {
        return undefined;
    }
};

/**
 * エラーステータスのレスポンスから ApiError を生成する関数
 * @param {Response} res レスポンス (res.ok が false のもの)
 * @returns {Promise<ApiError>} 例外オブジェクト
*/
export const toApiError = async (res: Response): Promise<ApiError> => {
    return new ApiError(res.status, res.statusText, await readProblem(res));
};

/**
 * 例外から Problem Details を取り出す関数
 * @param {unknown} error catch した値
 * @returns {ProblemDetails | undefined} Problem Details (無ければ undefined)
*/
export const problemOf = (error: unknown): ProblemDetails | undefined => {
    if (error instanceof ApiError) return error.problem;
    return isProblemDetails(error) ? error : undefined;
};

/**
 * 例外から Problem Details の code を取り出す関数
 * ネットワークエラーや problem+json でない応答では undefined を返す。
 * @param {unknown} error catch した値
 * @returns {string | undefined} エラーコード
*/
export const problemCodeOf = (error: unknown): string | undefined => {
    return problemOf(error)?.code;
};
