// 組織名の入力検証 (純粋関数。API の制約: OrganizationCreate / OrganizationUpdate)

/** 組織名の最大長 */
export const ORGANIZATION_NAME_MAX_LENGTH = 100;

/**
 * 組織名の入力を検証する関数
 * @param {string} value 入力値
 * @returns {string | undefined} エラー文言 (問題が無ければ undefined)
*/
export const organizationNameErrorOf = (value: string): string | undefined => {
    const trimmed = value.trim();
    if (trimmed === '') return '組織名を入力してください。';
    if (trimmed.length > ORGANIZATION_NAME_MAX_LENGTH) return `組織名は ${ORGANIZATION_NAME_MAX_LENGTH} 文字以内で入力してください。`;
    return undefined;
};
