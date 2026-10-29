#!/usr/bin/env python
# coding:utf-8
"""ToDo の閲覧範囲（AP-VIS）と操作の権限（ToDoApp.md §3）の定義。**判定はここだけで行う**（AP-VIS-09）。

閲覧範囲は SQL の条件（:func:`visible_condition`）としてだけ定義し、一覧のクエリと単体の取得（詳細・更新・削除・
担当者の変更・アクティビティ）の両方が ``WHERE`` にこの条件を付ける。Python 側に同じ判定を二重に持たない
（定義がずれて一覧と詳細で見え方が変わるのを防ぐ）。閲覧範囲外は「存在しない」と同じ 404 にする（03 §2）。

閲覧できる ToDo（論理削除済みは誰も閲覧できない。AP-TODO-05）:

| 条件 | 根拠 |
| --- | --- |
| 操作者が ``tenant_admin`` | AP-VIS-05（閲覧範囲に関わらず全件） |
| 作成者が操作者 | AP-VIS-02..04 |
| 担当者に操作者が含まれる | AP-VIS-02..04 |
| ``visibility = 'tenant'`` | AP-VIS-04 |
| ``visibility = 'organization'`` かつ、公開先の**有効な**（論理削除されていない）組織のいずれかに操作者が所属 | AP-VIS-03、AP-VIS-08（削除された組織は除外。すべて削除されていれば ``private`` と同じ） |

他テナントの行は RLS で見えない（AP-VIS-06。最終防衛線）。加えて、部分インデックス（``deleted_at IS NULL``）と
``tenant_id`` 先頭のインデックスを使えるよう、``tenant_id`` の条件も明示する。

操作の権限（閲覧できる ToDo に対して判定する。:func:`todo_permissions`）:

| 操作（:class:`TodoOperation`） | ``tenant_admin`` | 作成者 | 担当者 | それ以外 |
| --- | --- | --- | --- | --- |
| 項目（タイトル・説明・期限・優先度）の変更 ``edit_fields`` | ○ | ○ | × | × |
| ステータスの変更 ``change_status`` | ○ | ○ | ○（AP-ASN-03） | × |
| 閲覧範囲・公開先組織の変更 ``change_visibility`` | ○ | ○ | × | × |
| 担当者の変更 ``change_assignees`` | ○ | ○ | ○ | × |
| 削除 ``delete`` | ○ | ○ | × | × |
| コメントの参照・投稿（``can_comment``） | ○ | ○ | ○ | ○（閲覧できれば誰でも。AP-CMT-01） |
| チェックリスト項目の追加・名前変更・削除・並べ替え ``edit_checklist`` | ○ | ○ | × | × |
| チェックリスト項目の完了・未完了の切り替え ``check_checklist_item`` | ○ | ○ | ○ | × |

コメントごとの権限（:func:`comment_permissions`。閲覧できる ToDo のコメントに対して判定する）:

| 操作（:class:`TodoOperation`） | 投稿者 | ``tenant_admin``（投稿者以外） | それ以外 |
| --- | --- | --- | --- |
| 編集 ``edit_comment`` | ○ | ×（AP-CMT-04） | × |
| 削除 ``delete_comment`` | ○ | ○ | × |

一覧の表示範囲（AP-TODO-07。:func:`scope_condition`。いずれも閲覧できるものに限る）:
``mine``（作成者が自分）/ ``assigned``（担当者に自分）/ ``shared``（作成者でも担当者でもない）/ ``all``（すべて）。
"""
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import Select, and_, false, not_, or_, select, true
from sqlalchemy.sql import ColumnElement
from sqlmodel import col

from main_app.models import TodoVisibility, TOrganization, TOrganizationMember, TTodo, TTodoAssignee, TTodoOrganization

# テナント管理者のロール（01 §7.5）
ROLE_TENANT_ADMIN = "tenant_admin"


class TodoScope(StrEnum):
    """一覧の表示範囲（AP-TODO-07）。"""

    MINE = "mine"
    ASSIGNED = "assigned"
    SHARED = "shared"
    ALL = "all"


class TodoOperation(StrEnum):
    """権限を判定する操作（ToDoApp.md §3）。"""

    EDIT_FIELDS = "edit_fields"
    CHANGE_STATUS = "change_status"
    CHANGE_VISIBILITY = "change_visibility"
    CHANGE_ASSIGNEES = "change_assignees"
    DELETE = "delete"
    EDIT_CHECKLIST = "edit_checklist"
    CHECK_CHECKLIST_ITEM = "check_checklist_item"
    EDIT_COMMENT = "edit_comment"
    DELETE_COMMENT = "delete_comment"


@dataclass(frozen=True, slots=True)
class TodoActor:
    """操作者。

    Attributes:
        tenant_id: テナント ID（テナントコンテキストの値）。
        user_id: AP のユーザー ID（``t_user.id``）。
        roles: テナントのロール（``tenant_admin`` / ``member``）。
    """

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    roles: frozenset[str]

    @property
    def is_tenant_admin(self) -> bool:
        """``tenant_admin`` か。"""
        return ROLE_TENANT_ADMIN in self.roles


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoPermissions:
    """操作者が 1 件の ToDo に対して行える操作（画面のボタンの出し分けにも使う）。

    Attributes:
        can_edit_fields: 項目（タイトル・説明・期限・優先度）を変更できるか。
        can_change_status: ステータスを変更できるか。
        can_change_visibility: 閲覧範囲・公開先組織を変更できるか。
        can_change_assignees: 担当者を変更できるか。
        can_delete: 削除できるか。
        can_comment: コメントを参照・投稿できるか（閲覧できる ToDo なら常に ``True``。AP-CMT-01）。
        can_edit_checklist: チェックリスト項目を追加・名前変更・削除・並べ替えできるか（AP-CHK-03）。
        can_check_checklist: チェックリスト項目の完了・未完了を切り替えられるか（AP-CHK-04）。
    """

    can_edit_fields: bool
    can_change_status: bool
    can_change_visibility: bool
    can_change_assignees: bool
    can_delete: bool
    can_comment: bool
    can_edit_checklist: bool
    can_check_checklist: bool

    def allows(self, operation: TodoOperation) -> bool:
        """操作が許可されているか。

        Raises:
            ValueError: コメントごとの操作（``edit_comment`` / ``delete_comment``）。:func:`comment_permissions` で判定する。
        """
        allowed = {
            TodoOperation.EDIT_FIELDS: self.can_edit_fields,
            TodoOperation.CHANGE_STATUS: self.can_change_status,
            TodoOperation.CHANGE_VISIBILITY: self.can_change_visibility,
            TodoOperation.CHANGE_ASSIGNEES: self.can_change_assignees,
            TodoOperation.DELETE: self.can_delete,
            TodoOperation.EDIT_CHECKLIST: self.can_edit_checklist,
            TodoOperation.CHECK_CHECKLIST_ITEM: self.can_check_checklist,
        }
        if operation not in allowed:
            raise ValueError(f"{operation} is judged per comment (comment_permissions)")
        return allowed[operation]

    @property
    def checklist(self) -> "TodoChecklistPermissions":
        """チェックリストの画面向けの権限（``can_edit_checklist`` / ``can_check_checklist`` と同じ値）。"""
        return TodoChecklistPermissions(can_edit=self.can_edit_checklist, can_check=self.can_check_checklist)


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoChecklistPermissions:
    """チェックリストに対する操作者の権限（チェックリストの応答に付ける。:attr:`TodoPermissions.checklist`）。

    Attributes:
        can_edit: 項目の追加・名前変更・削除・並べ替え（作成者・``tenant_admin``）。
        can_check: 完了・未完了の切り替え（作成者・担当者・``tenant_admin``）。
    """

    can_edit: bool
    can_check: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TodoCommentPermissions:
    """1 件のコメントに対する操作者の権限（:func:`comment_permissions`）。

    Attributes:
        can_edit: 編集できるか（投稿者のみ。``tenant_admin`` も他人のコメントは編集できない。AP-CMT-03, 04）。
        can_delete: 削除できるか（投稿者・``tenant_admin``）。
    """

    can_edit: bool
    can_delete: bool

    def allows(self, operation: TodoOperation) -> bool:
        """操作が許可されているか（``edit_comment`` / ``delete_comment`` のみ）。

        Raises:
            ValueError: コメントの操作以外。
        """
        match operation:
            case TodoOperation.EDIT_COMMENT:
                return self.can_edit
            case TodoOperation.DELETE_COMMENT:
                return self.can_delete
        raise ValueError(f"{operation} is not a comment operation")


# --------------------------------------------------------------------------- 閲覧範囲（SQL）


def assigned_todo_ids(tenant_id: uuid.UUID, user_id: uuid.UUID) -> Select:
    """ユーザーが担当している ToDo の ID の副問い合わせ（インデックス ``ix_t_todo_assignee_tenant_id_user_id``）。

    Args:
        tenant_id: テナント ID。
        user_id: ユーザー ID。

    Returns:
        Select: ``SELECT todo_id``。
    """
    return select(col(TTodoAssignee.todo_id)).where(col(TTodoAssignee.tenant_id) == tenant_id, col(TTodoAssignee.user_id) == user_id)


def organization_shared_todo_ids(tenant_id: uuid.UUID, user_id: uuid.UUID) -> Select:
    """ユーザーが所属する**有効な**組織を公開先に含む ToDo の ID の副問い合わせ（AP-VIS-03, 08）。

    論理削除された組織は除外する（所属・公開先の行は残っているため、ここで落とす）。

    Args:
        tenant_id: テナント ID。
        user_id: ユーザー ID。

    Returns:
        Select: ``SELECT todo_id``。
    """
    return (
        select(col(TTodoOrganization.todo_id))
        .join(TOrganization, and_(col(TOrganization.tenant_id) == col(TTodoOrganization.tenant_id), col(TOrganization.id) == col(TTodoOrganization.organization_id)))
        .join(TOrganizationMember, and_(col(TOrganizationMember.tenant_id) == col(TTodoOrganization.tenant_id), col(TOrganizationMember.organization_id) == col(TTodoOrganization.organization_id)))
        .where(col(TTodoOrganization.tenant_id) == tenant_id, col(TOrganizationMember.user_id) == user_id, col(TOrganization.deleted_at).is_(None))
    )


def visible_condition(actor: TodoActor) -> ColumnElement[bool]:
    """操作者が閲覧できる ToDo の条件（``t_todo`` に対する WHERE 句。論理削除の条件は含まない）。

    一覧・詳細・更新・削除・担当者の変更・アクティビティのすべてがこの条件を使う（AP-VIS-09）。
    副問い合わせは相関させず ``id IN (...)`` にする（PostgreSQL がハッシュ化して 1 回だけ評価できる）。

    Args:
        actor: 操作者。

    Returns:
        ColumnElement[bool]: 条件。
    """
    if actor.is_tenant_admin:
        return true()
    return or_(
        col(TTodo.created_by) == actor.user_id,
        col(TTodo.visibility) == TodoVisibility.TENANT.value,
        col(TTodo.id).in_(assigned_todo_ids(actor.tenant_id, actor.user_id)),
        and_(col(TTodo.visibility) == TodoVisibility.ORGANIZATION.value, col(TTodo.id).in_(organization_shared_todo_ids(actor.tenant_id, actor.user_id))),
    )


def scope_condition(actor: TodoActor, scope: TodoScope) -> ColumnElement[bool]:
    """一覧の表示範囲の条件（:func:`visible_condition` と AND で使う）。

    Args:
        actor: 操作者。
        scope: 表示範囲。

    Returns:
        ColumnElement[bool]: 条件。
    """
    match scope:
        case TodoScope.MINE:
            return col(TTodo.created_by) == actor.user_id
        case TodoScope.ASSIGNED:
            return col(TTodo.id).in_(assigned_todo_ids(actor.tenant_id, actor.user_id))
        case TodoScope.SHARED:
            return and_(col(TTodo.created_by) != actor.user_id, not_(col(TTodo.id).in_(assigned_todo_ids(actor.tenant_id, actor.user_id))))
        case TodoScope.ALL:
            return true()
    return false()


def effective_visibility(visibility: str, active_organization_count: int) -> TodoVisibility:
    """実際に効いている閲覧範囲（AP-VIS-08: 公開先の組織がすべて削除された ``organization`` は ``private`` と同じ）。

    :func:`visible_condition` の結果と一致する（表示用。判定には使わない）。

    Args:
        visibility: 設定された閲覧範囲。
        active_organization_count: 公開先のうち有効な組織の数。

    Returns:
        TodoVisibility: 実際の閲覧範囲。
    """
    value = TodoVisibility(visibility)
    if value is TodoVisibility.ORGANIZATION and active_organization_count == 0:
        return TodoVisibility.PRIVATE
    return value


# --------------------------------------------------------------------------- 操作の権限


def todo_permissions(actor: TodoActor, *, created_by: uuid.UUID, assignee_ids: Collection[uuid.UUID]) -> TodoPermissions:
    """閲覧できる ToDo に対する操作者の権限（ToDoApp.md §3）。

    閲覧できるかは判定しない（呼び出し側が :func:`visible_condition` で取得した ToDo に対して使う）。

    Args:
        actor: 操作者。
        created_by: ToDo の作成者。
        assignee_ids: ToDo の担当者（無効化されたユーザーを含む）。

    Returns:
        TodoPermissions: 権限。
    """
    is_admin = actor.is_tenant_admin
    is_creator = created_by == actor.user_id
    is_assignee = actor.user_id in assignee_ids
    owner = is_admin or is_creator
    return TodoPermissions(
        can_edit_fields=owner,
        can_change_status=owner or is_assignee,
        can_change_visibility=owner,
        can_change_assignees=owner or is_assignee,
        can_delete=owner,
        can_comment=True,
        can_edit_checklist=owner,
        can_check_checklist=owner or is_assignee,
    )


def comment_permissions(actor: TodoActor, *, author_id: uuid.UUID) -> TodoCommentPermissions:
    """閲覧できる ToDo のコメントに対する操作者の権限（AP-CMT-03, 04）。

    ToDo を閲覧できるかは判定しない（呼び出し側が :func:`visible_condition` で ToDo を取得してから使う）。

    Args:
        actor: 操作者。
        author_id: コメントの投稿者。

    Returns:
        TodoCommentPermissions: 権限。
    """
    is_author = author_id == actor.user_id
    return TodoCommentPermissions(can_edit=is_author, can_delete=is_author or actor.is_tenant_admin)
