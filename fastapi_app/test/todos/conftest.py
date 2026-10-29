# -*- coding: utf-8 -*-
"""ToDo のサービス・API のテスト用フィクスチャ。

- DB は開発 DB の ``app_db``。**使い捨てのテナント(``ap_db.tenant()``)にだけ書き込み**、終了時に監査ログ・アクティビティを含めて削除する
  (``ap_services/conftest.py``)。alpha / beta のデータには触れない。
- ``TodoFactory``: サービスを通さずに ToDo(担当者・公開先組織付き)を直接作る。閲覧範囲の期待値(オラクル)を実装とは独立に作るための準備用。
- ``world``: 1 つの使い捨てテナントに、役割の違うユーザーと組織を揃えたもの(``TodoWorld``)。
"""
import datetime as dt
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from ap_services.conftest import ApDb, ap_db, app_cp_agent_engine, app_owner_engine, app_runtime_engine  # noqa: F401
from sqlalchemy import insert

from main_app.models import TTodo, TTodoAssignee, TTodoOrganization
from main_app.services.todo_service import TodoService
from modules.tenancy.context import TenantContext

__all__ = ["Person", "TodoFactory", "TodoWorld", "ap_db", "app_cp_agent_engine", "app_owner_engine", "app_runtime_engine", "world"]


@dataclass(frozen=True)
class Person:
    """テナントのユーザー(``t_user`` の行)と、そのセッションのロール。"""

    id: uuid.UUID
    sub: str
    name: str
    roles: tuple[str, ...]

    @property
    def is_admin(self) -> bool:
        return "tenant_admin" in self.roles


class TodoFactory:
    """ToDo を直接作る(コミット済み)。"""

    def __init__(self, ap_db: ApDb) -> None:
        self.ap_db = ap_db

    def add(
        self,
        ctx: TenantContext,
        creator: Person | uuid.UUID,
        *,
        title: str = "todo",
        description: str | None = None,
        status: str = "open",
        priority: str = "medium",
        due_date: dt.date | None = None,
        visibility: str = "private",
        orgs: Sequence[uuid.UUID] = (),
        assignees: Sequence[Person | uuid.UUID] = (),
        deleted: bool = False,
        created_at: dt.datetime | None = None,
        updated_at: dt.datetime | None = None,
        assigned_at: dt.datetime | None = None,
    ) -> uuid.UUID:
        """ToDo(と公開先・担当者)を作って ID を返す。"""
        creator_id = creator.id if isinstance(creator, Person) else creator
        values: dict[str, Any] = {
            "tenant_id": ctx.tenant_id, "created_by": creator_id, "updated_by": creator_id, "title": title, "description": description,
            "status": status, "priority": priority, "due_date": due_date, "visibility": visibility,
        }
        if created_at is not None:
            values["created_at"] = created_at
            values["updated_at"] = updated_at or created_at
        if updated_at is not None:
            values["updated_at"] = updated_at
        if deleted:
            values["deleted_at"] = dt.datetime.now(dt.UTC)
        with self.ap_db.session(ctx) as session:
            todo = TTodo(**values)
            session.add(todo)
            session.flush()
            for org_id in orgs:
                session.add(TTodoOrganization(tenant_id=ctx.tenant_id, todo_id=todo.id, organization_id=org_id))
            for user in assignees:
                user_id = user.id if isinstance(user, Person) else user
                extra = {"assigned_at": assigned_at} if assigned_at else {}
                session.add(TTodoAssignee(tenant_id=ctx.tenant_id, todo_id=todo.id, user_id=user_id, assigned_by=creator_id, **extra))
            session.commit()
            return todo.id

    def bulk(self, ctx: TenantContext, creator: Person, count: int, *, assignee_pool: Sequence[Person] = (), org_pool: Sequence[uuid.UUID] = ()) -> list[uuid.UUID]:
        """大量の ToDo を高速に作る(性能の確認用。ステータス・優先度・期限・閲覧範囲・担当者・公開先を循環させる)。"""
        statuses, priorities, visibilities = ("open", "in_progress", "done"), ("low", "medium", "high"), ("private", "organization", "tenant")
        base = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        todos, assignees, orgs, ids = [], [], [], []
        for index in range(count):
            todo_id = uuid.uuid7()
            ids.append(todo_id)
            visibility = visibilities[index % 3]
            created = base + dt.timedelta(seconds=index)
            todos.append(
                {
                    "id": todo_id, "tenant_id": ctx.tenant_id, "created_by": creator.id, "updated_by": creator.id, "title": f"bulk todo {index}", "status": statuses[index % 3],
                    "priority": priorities[(index // 3) % 3], "due_date": None if index % 5 == 0 else base.date() + dt.timedelta(days=index % 60), "visibility": visibility,
                    "version": 1, "created_at": created, "updated_at": created,
                }
            )
            if visibility == "organization" and org_pool:
                orgs.append({"tenant_id": ctx.tenant_id, "todo_id": todo_id, "organization_id": org_pool[index % len(org_pool)]})
            for offset in range(min(len(assignee_pool), index % 3)):
                assignees.append({"tenant_id": ctx.tenant_id, "todo_id": todo_id, "user_id": assignee_pool[(index + offset) % len(assignee_pool)].id, "assigned_by": creator.id})
        with self.ap_db.session(ctx) as session:
            session.execute(insert(TTodo), todos)
            if orgs:
                session.execute(insert(TTodoOrganization), orgs)
            if assignees:
                session.execute(insert(TTodoAssignee), assignees)
            session.commit()
        return ids


@dataclass
class TodoWorld:
    """1 つの使い捨てテナントと、役割の違うユーザー・組織。

    ユーザー: ``admin``(tenant_admin)/ ``creator`` / ``assignee`` / ``m1``(組織 O1 の所属)/ ``m2``(組織 O2 の所属)/
    ``outsider``(どの組織にも所属しない)/ ``n3``(論理削除済みの組織 O3 だけに所属)/ ``inactive``(無効化されたユーザー)。
    組織: ``o1`` / ``o2``(有効)、``o3``(論理削除済み)。
    """

    ap_db: ApDb
    ctx: TenantContext
    factory: TodoFactory
    people: dict[str, Person] = field(default_factory=dict)
    orgs: dict[str, uuid.UUID] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        if name in ("people", "orgs"):
            raise AttributeError(name)
        if name in self.people:
            return self.people[name]
        if name in self.orgs:
            return self.orgs[name]
        raise AttributeError(name)

    def add_person(self, key: str, *, roles: tuple[str, ...] = ("member",), active: bool = True, ctx: TenantContext | None = None) -> Person:
        sub = str(uuid.uuid4())
        user = self.ap_db.add_user(ctx or self.ctx, sub=sub, email=f"{key}-{sub[:6]}@example.com", display_name=f"User {key}", is_active=active)
        person = Person(id=user.id, sub=sub, name=f"User {key}", roles=roles)
        if ctx is None:
            self.people[key] = person
        return person

    @contextmanager
    def service(self, person: Person, *, ctx: TenantContext | None = None) -> Iterator[TodoService]:
        """``person`` として動く ``TodoService``(テナントコンテキスト + ``app_runtime`` のセッション)。"""
        with self.ap_db.session(ctx or self.ctx) as session:
            yield TodoService(session, actor_user_id=person.id, actor_roles=person.roles)

    def call(self, person: Person, func: Callable[[TodoService], Any], *, ctx: TenantContext | None = None) -> Any:
        """``func(service)`` を ``person`` として 1 回呼ぶ。"""
        with self.service(person, ctx=ctx) as service:
            return func(service)

    def todo(self, todo_id: uuid.UUID, ctx: TenantContext | None = None) -> dict[str, Any]:
        """ToDo の行(論理削除済みを含む)。"""
        return self.ap_db.rows(ctx or self.ctx, "SELECT * FROM t_todo WHERE id = :id", id=todo_id)[0]

    def assignee_rows(self, todo_id: uuid.UUID) -> list[dict[str, Any]]:
        return self.ap_db.rows(self.ctx, "SELECT * FROM t_todo_assignee WHERE todo_id = :id ORDER BY user_id", id=todo_id)

    def org_rows(self, todo_id: uuid.UUID) -> list[uuid.UUID]:
        return [row["organization_id"] for row in self.ap_db.rows(self.ctx, "SELECT organization_id FROM t_todo_organization WHERE todo_id = :id ORDER BY organization_id", id=todo_id)]

    def activities(self, todo_id: uuid.UUID) -> list[dict[str, Any]]:
        return self.ap_db.rows(self.ctx, "SELECT * FROM t_todo_activity WHERE todo_id = :id ORDER BY created_at, id", id=todo_id)

    def todo_audits(self, todo_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        rows = [row for row in self.ap_db.audits(self.ctx) if row["target_type"] == "todo"]
        return [row for row in rows if todo_id is None or row["target_id"] == str(todo_id)]


def build_world(ap_db: ApDb) -> TodoWorld:
    ctx = ap_db.tenant()
    world = TodoWorld(ap_db=ap_db, ctx=ctx, factory=TodoFactory(ap_db))
    world.add_person("admin", roles=("tenant_admin",))
    for key in ("creator", "assignee", "m1", "m2", "outsider", "n3"):
        world.add_person(key)
    world.add_person("inactive", active=False)
    world.orgs["o1"] = ap_db.add_org(ctx, "Org One", members=(world.m1.id,)).id
    world.orgs["o2"] = ap_db.add_org(ctx, "Org Two", members=(world.m2.id,)).id
    world.orgs["o3"] = ap_db.add_org(ctx, "Org Three (deleted)", deleted=True, members=(world.n3.id,)).id
    return world


@pytest.fixture
def world(ap_db) -> TodoWorld:  # noqa: F811
    """使い捨てのテナント + 役割の違うユーザー + 組織。"""
    return build_world(ap_db)
