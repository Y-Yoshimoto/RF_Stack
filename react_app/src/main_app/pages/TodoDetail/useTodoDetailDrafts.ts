/**
 * @description:
 * 詳細画面の 3 つのフォーム (項目・閲覧範囲・担当者) の下書きをまとめるカスタムフック (AP-UX-07・AP-UX-08)
 * useRebasedDraft をフォームごとに使うだけで、独自の状態は持たない。詳細が変わっても (別のフォームの保存・412 の後の再表示)、
 * 触っていない項目だけが新しい値になり、入力中の項目は残る。他の人の変更と重なった項目は conflict_labels に集める。
*/
import type { TodoDetail } from '@/main_app/api/contract';
import { useRebasedDraft, type RebasedDraftState } from '@/main_app/todos/useRebasedDraft';
import {
    ASSIGNEES_EQUALS,
    AUDIENCE_EQUALS,
    assigneesDraftOf,
    audienceDraftOf,
    conflictLabelsOf,
    fieldsDraftOf,
    type AssigneesDraft,
    type AudienceDraft,
    type FieldsDraft,
} from './detail_drafts';

/**
 * 詳細画面のフォームの下書き。
 */
export type TodoDetailDrafts = {
    fields: RebasedDraftState<FieldsDraft>;
    audience: RebasedDraftState<AudienceDraft>;
    assignees: RebasedDraftState<AssigneesDraft>;
    /** 現在の入力値 (詳細から作った値に、入力中の項目を重ねたもの)。 */
    fields_values: FieldsDraft;
    audience_value: AudienceDraft;
    assignee_ids: string[];
    /** 他の人の変更と重なった項目の名前。 */
    conflict_labels: string[];
};

/**
 * 詳細画面のフォームの下書きのカスタムフック
 * @param {TodoDetail} todo 詳細
 * @returns {TodoDetailDrafts} 下書き
*/
export const useTodoDetailDrafts = (todo: TodoDetail): TodoDetailDrafts => {
    const server_fields = fieldsDraftOf(todo);
    const server_audience = audienceDraftOf(todo);
    const server_assignees = assigneesDraftOf(todo);
    const fields = useRebasedDraft<FieldsDraft>(server_fields);
    const audience = useRebasedDraft<AudienceDraft>(server_audience, AUDIENCE_EQUALS);
    const assignees = useRebasedDraft<AssigneesDraft>(server_assignees, ASSIGNEES_EQUALS);
    return {
        fields,
        audience,
        assignees,
        fields_values: fields.draft ?? server_fields,
        audience_value: audience.draft ?? server_audience,
        assignee_ids: (assignees.draft ?? server_assignees).assignee_ids,
        conflict_labels: conflictLabelsOf([...fields.conflicts, ...audience.conflicts, ...assignees.conflicts]),
    };
};

export default useTodoDetailDrafts;
