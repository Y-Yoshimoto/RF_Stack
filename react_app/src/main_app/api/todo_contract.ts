// ToDo (テーマ固有) の API 契約の型 (`/api/v1/todos`、tags: app)。contract.ts から再公開する (利用側は contract から import する)
// 正は FastAPI の OpenAPI (`GET /openapi.json`) と docs/spec/ToDoApp.md §6・§9.5・§10。パスとエラーコードは contract.ts の
// APP_API_PATHS / APP_PROBLEM_CODE。
//
// - tenant_admin / member のどちらも使える。閲覧できない ToDo は 404 todo_not_found (存在を明かさない)、
//   権限の無い操作は 403 todo_operation_forbidden (拡張メンバー operation)。権限は詳細の permissions で事前に分かる。
// - PATCH / PUT / DELETE は If-Match が必須 (無ければ 428、不一致は 412 todo_version_conflict、形式不正は 400 invalid_if_match)。
// - PATCH の権限は「実際に値が変わる項目」で判定する (同じ値を送った項目は変更とみなさない。ToDoApp.md §10 #7)。
// - 日付 (due_date・due_before・due_after) は `YYYY-MM-DD`、日時は UTC の ISO 8601 (`Z` 付き)。

/** ステータス (AP-TODO-02。既定 `open`)。 */
export type TodoStatus = 'open' | 'in_progress' | 'done';
/** 優先度 (AP-TODO-03。既定 `medium`。並び順は `low < medium < high`)。 */
export type TodoPriority = 'low' | 'medium' | 'high';
/** 閲覧範囲 (AP-VIS-01。既定 `private`)。 */
export type TodoVisibility = 'private' | 'organization' | 'tenant';
/** 一覧の表示範囲 (AP-TODO-07。既定 `all`)。いずれも閲覧できるものに限る。 */
export type TodoScope = 'mine' | 'assigned' | 'shared' | 'all';
/** 一覧の並び替えのキー。 */
export type TodoSortField = 'due_date' | 'priority' | 'created_at' | 'updated_at';
/** 一覧の並び順 (キーは 1 つだけ。先頭に `-` で降順。既定 `-created_at`。期限なしは昇順で末尾・降順で先頭)。 */
export type TodoSortKey = TodoSortField | `-${TodoSortField}`;
/**
 * 権限の判定対象の操作 (403 todo_operation_forbidden の拡張メンバー operation)。
 * edit_comment / delete_comment はコメントごとの permissions、edit_checklist / check_checklist_item は ToDo の permissions で事前に分かる。
 */
export type TodoOperation =
    | 'edit_fields'
    | 'change_status'
    | 'change_visibility'
    | 'change_assignees'
    | 'delete'
    | 'edit_comment'
    | 'delete_comment'
    | 'edit_checklist'
    | 'check_checklist_item';
/** アクティビティの種別 (AP-ACT-01・AP-ACT-05)。 */
export type TodoActivityAction = 'created' | 'updated' | 'status_changed' | 'assignees_changed' | 'visibility_changed' | 'deleted' | 'checklist_changed';
/** checklist_changed の payload.op (§10 #20。並べ替えは記録しない)。 */
export type TodoChecklistActivityOp = 'added' | 'renamed' | 'removed' | 'checked' | 'unchecked';

/** ステータスの値 (表示順)。 */
export const TODO_STATUSES: readonly TodoStatus[] = ['open', 'in_progress', 'done'];
/** 優先度の値 (低い順)。 */
export const TODO_PRIORITIES: readonly TodoPriority[] = ['low', 'medium', 'high'];
/** 閲覧範囲の値。 */
export const TODO_VISIBILITIES: readonly TodoVisibility[] = ['private', 'organization', 'tenant'];
/** 表示範囲の値。 */
export const TODO_SCOPES: readonly TodoScope[] = ['mine', 'assigned', 'shared', 'all'];
/** 並び順の値。 */
export const TODO_SORT_KEYS: readonly TodoSortKey[] = ['due_date', '-due_date', 'priority', '-priority', 'created_at', '-created_at', 'updated_at', '-updated_at'];

/** サーバーの既定値 (省略時の値)。 */
export const TODO_DEFAULTS = {
    SCOPE: 'all' satisfies TodoScope,
    SORT: '-created_at' satisfies TodoSortKey,
    STATUS: 'open' satisfies TodoStatus,
    PRIORITY: 'medium' satisfies TodoPriority,
    VISIBILITY: 'private' satisfies TodoVisibility,
} as const;

/** 入力の上限 (AP-TODO-04・AP-ASN-01・§10 #14)。 */
export const TODO_LIMITS = {
    TITLE_MAX: 200,
    DESCRIPTION_MAX: 10000,
    /** 一覧の q (タイトルの部分一致) の最大長。 */
    QUERY_MAX: 200,
    ASSIGNEES_MAX: 20,
    ORGANIZATIONS_MAX: 100,
    /** コメントの本文の最大長 (AP-CMT-01。1 文字以上)。 */
    COMMENT_BODY_MAX: 4000,
    /** チェックリスト項目名の最大長 (AP-CHK-02。1 文字以上)。 */
    CHECKLIST_ITEM_TITLE_MAX: 200,
    /** 1 件の ToDo のチェックリスト項目の最大数 (AP-CHK-01)。 */
    CHECKLIST_ITEMS_MAX: 100,
} as const;

/** ホームの要約の「期限間近」の既定の日数 (§10 #21。1〜30)。 */
export const TODO_SUMMARY_DUE_SOON_DAYS = 7;

/** 422 invalid_todo_assignees の errors[].code。 */
export const TODO_ASSIGNEE_ERROR_CODE = {
    /** テナント内に存在しないユーザー (他テナントを含む)。 */
    NOT_FOUND: 'not_found',
    /** 無効化されたユーザーの新規の割り当て。 */
    INACTIVE: 'inactive',
} as const;

/** 公開先の組織 (OpenAPI: TodoOrganizationRead。有効なもののみ)。 */
export type TodoOrganizationRead = {
    id: string;
    name: string;
};

/** 担当者 (OpenAPI: TodoAssigneeRead)。 */
export type TodoAssigneeRead = {
    /** ユーザー ID (`GET /api/v1/users` の id と同じ値)。 */
    user_id: string;
    display_name: string;
    /** 無効化されたユーザーも割り当ては残る (画面では「無効」と表示する。AP-ASN-04)。 */
    is_active: boolean;
    assigned_at: string;
    /** 割り当てたユーザーの ID。 */
    assigned_by: string;
};

/** 操作者がその ToDo に対して行える操作 (OpenAPI: TodoPermissionsRead。画面のボタンの出し分け用。判定はサーバーも行う)。 */
export type TodoPermissions = {
    /** 項目 (タイトル・説明・期限・優先度) の変更 (作成者・tenant_admin)。 */
    can_edit_fields: boolean;
    /** ステータスの変更 (作成者・担当者・tenant_admin)。 */
    can_change_status: boolean;
    /** 閲覧範囲・公開先組織の変更 (作成者・tenant_admin)。 */
    can_change_visibility: boolean;
    /** 担当者の変更 (作成者・担当者・tenant_admin)。 */
    can_change_assignees: boolean;
    /** 削除 (作成者・tenant_admin)。 */
    can_delete: boolean;
    /** コメントの投稿 (閲覧できる人は誰でも。AP-CMT-01)。 */
    can_comment: boolean;
    /** チェックリスト項目の追加・名前変更・削除・並べ替え (作成者・tenant_admin。AP-CHK-03)。 */
    can_edit_checklist: boolean;
    /** チェックリスト項目の完了・未完了の切り替え (作成者・担当者・tenant_admin。AP-CHK-04)。 */
    can_check_checklist: boolean;
};

/** ToDo・コメント・チェックリストが参照するユーザー (OpenAPI: UserNameRead)。無効化されたユーザーも含む (画面では「無効」と表示する)。 */
export type TodoUserRef = {
    id: string;
    display_name: string;
    is_active: boolean;
};

/** チェックリストの進捗 (OpenAPI: TodoChecklistSummary。AP-CHK-06)。項目が無ければ 0 / 0。 */
export type TodoChecklistProgress = {
    done_count: number;
    total_count: number;
};

/** ToDo (OpenAPI: TodoRead)。一覧の要素 (説明・権限を含まない)。version は ETag と同じ値。 */
export type TodoRead = {
    id: string;
    /** タイトル (1〜200 文字)。 */
    title: string;
    status: TodoStatus;
    priority: TodoPriority;
    /** 期限 (`YYYY-MM-DD`)。期限なしは null。 */
    due_date: string | null;
    /** 設定された閲覧範囲。 */
    visibility: TodoVisibility;
    /** 実際の閲覧範囲。`organization` で有効な公開先組織が無い (すべて削除された) 場合は `private` (AP-VIS-08。再指定を促す)。 */
    effective_visibility: TodoVisibility;
    /** 有効な公開先組織 (組織名順。削除された組織は含まない)。 */
    organizations: TodoOrganizationRead[];
    /** 担当者 (割り当て日時順。無効化されたユーザーを含む)。 */
    assignees: TodoAssigneeRead[];
    /** 作成者のユーザー ID。 */
    created_by: string;
    /** 最終更新者のユーザー ID。 */
    updated_by: string;
    /** 作成者 (表示名・有効/無効。AP-UX-03・AP-UX-09)。 */
    creator: TodoUserRef;
    /** 最終更新者 (表示名・有効/無効)。 */
    updater: TodoUserRef;
    /** チェックリストの進捗。 */
    checklist: TodoChecklistProgress;
    /** コメント数 (削除済みを除く)。 */
    comment_count: number;
    /** ToDo 本体の版 (ETag と同じ値)。コメント・チェックリストの変更では変わらない (§10 #16)。 */
    version: number;
    created_at: string;
    /** ToDo 本体の更新日時。コメント・チェックリストの変更では変わらない (§10 #16)。 */
    updated_at: string;
};

/** ToDo の詳細 (OpenAPI: TodoDetail)。GET / POST / PATCH / PUT .../assignees のレスポンス。ETag ヘッダー付き。 */
export type TodoDetail = TodoRead & {
    /** 説明 (最大 10,000 文字)。無ければ null。 */
    description: string | null;
    permissions: TodoPermissions;
};

/** `GET /api/v1/todos` のレスポンス (OpenAPI: TodoPage)。 */
export type TodoPage = {
    items: TodoRead[];
    next_cursor: string | null;
    /** 総件数 (include_total=true のときだけ数値。それ以外は null)。 */
    total?: number | null;
};

/** `GET /api/v1/todos` のクエリ (API に送る形)。不正な値・壊れたカーソル・複数キーの sort は 422。 */
export type TodoListQuery = {
    /** 1 ページの件数 (既定 50、1〜200)。 */
    limit?: number;
    cursor?: string;
    scope?: TodoScope;
    /** ステータス (カンマ区切り。例: `open,in_progress`)。 */
    status?: string;
    /** 優先度 (カンマ区切り)。 */
    priority?: string;
    /** タイトルの部分一致 (大文字小文字を区別しない。最大 200 文字)。 */
    q?: string;
    /** 公開先に含まれる (有効な) 組織。 */
    organization_id?: string;
    /** 担当者に含まれるユーザー。 */
    assignee_id?: string;
    /** 期限がこの日以前 (この日を含む。期限なしは除く)。 */
    due_before?: string;
    /** 期限がこの日以降 (この日を含む。期限なしは除く)。 */
    due_after?: string;
    sort?: TodoSortKey;
    /** true のとき TodoPage.total に絞り込み後の総件数を入れる (先頭ページだけで指定する。AP-UX-02)。 */
    include_total?: boolean;
};

/** `POST /api/v1/todos` のリクエスト (OpenAPI: TodoCreate)。201、Location / ETag 付きで TodoDetail を返す。 */
export type TodoCreate = {
    title: string;
    /** 空文字は null として扱われる。 */
    description?: string | null;
    due_date?: string | null;
    priority?: TodoPriority;
    status?: TodoStatus;
    visibility?: TodoVisibility;
    /** `organization` のときは有効な組織を 1 つ以上必須。それ以外では指定できない (422)。最大 100。 */
    organization_ids?: string[];
    /** テナント内の有効なユーザー (最大 20 人)。 */
    assignee_ids?: string[];
};

/**
 * `PATCH /api/v1/todos/{todo_id}` のリクエスト (OpenAPI: TodoUpdate)。送った項目だけを更新する。
 * description / due_date の null は値を消す。それ以外の項目の null は 422。
 */
export type TodoUpdate = {
    title?: string;
    description?: string | null;
    due_date?: string | null;
    priority?: TodoPriority;
    /** 担当者もこの項目だけは変更できる。 */
    status?: TodoStatus;
    visibility?: TodoVisibility;
    /** 公開先の組織 ID の全件 (置き換え)。`organization` 以外にすると公開先は空になる。 */
    organization_ids?: string[];
};

/** `PUT /api/v1/todos/{todo_id}/assignees` のリクエスト (OpenAPI: TodoAssigneesReplace)。全置換。最大 20 人。 */
export type TodoAssigneesReplace = {
    user_ids: string[];
};

/**
 * アクティビティ (OpenAPI: TodoActivityRead)。payload の形は action ごとに異なる (activity_payload.ts で読む):
 * created `{values: {...}}` / updated・status_changed `{changes: {<項目>: {before, after}}}` /
 * visibility_changed `{changes?: {visibility: {before, after}}, organization_ids?: {added, removed}}` /
 * assignees_changed `{added, removed}` / deleted `{title}` /
 * checklist_changed `{op, item_id, title, before?, after?}` (op は TodoChecklistActivityOp。renamed は before / after に名前)。
 */
export type TodoActivityRead = {
    id: string;
    todo_id: string;
    actor_id: string;
    /** 操作者の表示名 (ユーザーを特定できなければ null)。無効かどうかはページの users[actor_id] で分かる。 */
    actor_display_name: string | null;
    action: TodoActivityAction;
    payload: Record<string, unknown>;
    /** 記録日時 (1 回の操作で複数の行を記録したときは同じ値)。 */
    created_at: string;
};

/** アクティビティが参照するユーザーの表示用の情報 (OpenAPI: TodoActivityUser)。 */
export type TodoActivityUser = {
    display_name: string;
    /** 無効化されたユーザーも含む (画面では「無効」と表示する)。 */
    is_active: boolean;
};

/**
 * アクティビティが参照するユーザー (キーはユーザー ID)。
 * 対象は操作者 (actor_id) と payload のユーザー ID (created の values.assignee_ids、assignees_changed の added / removed)。
 * 無効化されたユーザー・担当者から外れたユーザーも含む。キーが無い ID (テナント内に存在しない) は「不明なユーザー」と表示する。
 */
export type TodoActivityUsers = Record<string, TodoActivityUser>;

/** `GET /api/v1/todos/{todo_id}/activities` のレスポンス (OpenAPI: TodoActivityPage。新しい順)。 */
export type TodoActivityPage = {
    items: TodoActivityRead[];
    next_cursor: string | null;
    total?: number | null;
    /** このページのアクティビティが参照するユーザー (常にある。参照が無ければ空のオブジェクト)。 */
    users: TodoActivityUsers;
};

/** `GET /api/v1/todos/{todo_id}/activities` のクエリ。 */
export type TodoActivityListQuery = {
    limit?: number;
    cursor?: string;
};

// ホームの要約 (AP-UX-01) ////////////////////////////////////////////////////

/** `GET /api/v1/todos/summary` のクエリ。 */
export type TodoSummaryQuery = {
    /** クライアントのローカル日付 (`YYYY-MM-DD`)。省略時はサーバーの UTC の日付 (§10 #21)。 */
    today?: string;
    /** 期限間近の日数 (既定 7、1〜30)。 */
    due_soon_days?: number;
};

/** 自分が担当の ToDo の件数 (完了を除く。閲覧できるものだけを数える)。 */
export type TodoSummaryAssignedCounts = {
    open: number;
    in_progress: number;
    /** 期限切れ (`due_date < today`)。 */
    overdue: number;
    /** 期限間近 (`today <= due_date <= due_soon_until`)。 */
    due_soon: number;
};

/** 自分が作成した ToDo の件数 (完了を除く)。 */
export type TodoSummaryCreatedCounts = {
    open: number;
    in_progress: number;
    overdue: number;
};

/** `GET /api/v1/todos/summary` のレスポンス (OpenAPI: TodoSummaryRead)。 */
export type TodoSummary = {
    /** 判定に使った今日 (`YYYY-MM-DD`)。 */
    today: string;
    /** 期限間近の終端 (`today + due_soon_days`。この日を含む)。 */
    due_soon_until: string;
    assigned: TodoSummaryAssignedCounts;
    created: TodoSummaryCreatedCounts;
};

// コメント (AP-CMT。ToDo 本体の版を変えない) ////////////////////////////////////

/** コメントに対する操作者の権限 (OpenAPI: TodoCommentPermissionsRead)。 */
export type TodoCommentPermissions = {
    /** 編集 (投稿者のみ。tenant_admin も他人のコメントは編集できない。AP-CMT-03・04)。 */
    can_edit: boolean;
    /** 削除 (投稿者・tenant_admin)。 */
    can_delete: boolean;
};

/** コメント (OpenAPI: TodoCommentRead)。version はコメントの版 (ETag と同じ値。If-Match に使う)。 */
export type TodoCommentRead = {
    id: string;
    todo_id: string;
    /** 投稿者 (無効化されたユーザーも残る。AP-CMT-07)。 */
    author: TodoUserRef;
    /** 本文 (プレーンテキスト。1〜4,000 文字)。 */
    body: string;
    version: number;
    created_at: string;
    updated_at: string;
    /** 本文を編集した日時 (編集していなければ null。null でなければ「編集済み」と表示する)。 */
    edited_at: string | null;
    permissions: TodoCommentPermissions;
};

/** `GET /api/v1/todos/{todo_id}/comments` のレスポンス (OpenAPI: TodoCommentPage。古い順。§10 #19)。 */
export type TodoCommentPage = {
    items: TodoCommentRead[];
    next_cursor: string | null;
    total?: number | null;
};

/** `GET /api/v1/todos/{todo_id}/comments` のクエリ。 */
export type TodoCommentListQuery = {
    limit?: number;
    cursor?: string;
};

/** `POST /api/v1/todos/{todo_id}/comments` (201、ETag) と `PATCH .../comments/{comment_id}` (200、ETag) のリクエスト。 */
export type TodoCommentWrite = {
    body: string;
};

// チェックリスト (AP-CHK。ToDo 本体の版を変えない) //////////////////////////////

/** チェックリストに対する操作者の権限 (OpenAPI: TodoChecklistPermissionsRead。TodoPermissions の can_edit_checklist / can_check_checklist と同じ値)。 */
export type TodoChecklistPermissions = {
    /** 項目の追加・名前変更・削除・並べ替え (作成者・tenant_admin)。 */
    can_edit: boolean;
    /** 完了・未完了の切り替え (作成者・担当者・tenant_admin)。 */
    can_check: boolean;
};

/** チェックリスト項目 (OpenAPI: TodoChecklistItemRead)。version は項目の版 (名前変更・切り替え・削除の If-Match に使う)。 */
export type TodoChecklistItemRead = {
    id: string;
    /** 項目名 (1〜200 文字)。 */
    title: string;
    /** 並び (0 から連番)。 */
    position: number;
    is_done: boolean;
    /** 完了した日時 (未完了なら null)。 */
    done_at: string | null;
    /** 完了した人 (未完了なら null)。 */
    done_by: TodoUserRef | null;
    version: number;
    created_at: string;
    updated_at: string;
};

/**
 * チェックリスト全体 (OpenAPI: TodoChecklistRead)。GET と変更系すべての応答。ETag はチェックリストの版 (version)。
 * version は項目の追加・削除・並べ替えで上がり、並べ替え (`PUT .../checklist/order`) の If-Match に使う (§10 #17)。
 */
export type TodoChecklistRead = {
    todo_id: string;
    version: number;
    /** 項目 (position の順)。 */
    items: TodoChecklistItemRead[];
    done_count: number;
    total_count: number;
    permissions: TodoChecklistPermissions;
};

/** `POST /api/v1/todos/{todo_id}/checklist/items` のリクエスト (201。If-Match 不要)。 */
export type TodoChecklistItemCreate = {
    title: string;
    /** 挿入する位置 (省略時は末尾)。 */
    position?: number;
};

/** `PATCH /api/v1/todos/{todo_id}/checklist/items/{item_id}` のリクエスト (If-Match: 項目の版)。権限は実際に変わる項目で判定する (§10 #18)。 */
export type TodoChecklistItemUpdate = {
    title?: string;
    is_done?: boolean;
};

/** `PUT /api/v1/todos/{todo_id}/checklist/order` のリクエスト (If-Match: チェックリストの版)。現在の項目 ID の集合と一致しなければ 422 (field=item_ids reason=mismatch)。 */
export type TodoChecklistOrder = {
    item_ids: string[];
};

/** 412 todo_checklist_version_conflict の拡張メンバー target (どちらの版が食い違ったか)。 */
export type TodoChecklistConflictTarget = 'item' | 'checklist';

/** 422 invalid_todo_input の errors[] のうち、チェックリストで分岐に使うもの (field と code の組)。 */
export const TODO_CHECKLIST_INPUT_ERROR = {
    /** 項目数が上限 (100) を超える (field: items)。 */
    TOO_MANY_ITEMS: { field: 'items', code: 'too_many' },
    /** 並べ替えの項目 ID の集合が現在の項目と一致しない (field: item_ids)。最新を取り直してやり直す。 */
    ORDER_MISMATCH: { field: 'item_ids', code: 'mismatch' },
} as const;
