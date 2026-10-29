# -*- coding: utf-8 -*-
"""UserService による t_user の写し(first_name / last_name / roles)の更新のテスト(create_user / update_user / get_user)。

仕様は docs/architecture/02 §4.7・§5.1・05-decisions #33。Keycloak が正で、AP の DB の写しは次のときに更新する。

- 作成・更新: IdP に設定した値を写しにする(ロールは「直接付与したロール + 既定ロール member」)
- 詳細の取得(``get_user``): IdP から取り直し、写しと違えば更新して ``version`` を +1(初回の埋め込みだけなら上げない)

Keycloak は ``TenantRealmIdp``(状態を持つフェイク)、DB は開発 DB の ``app_db``(使い捨てのテナント。終了時に削除)。
"""
import logging
import uuid
from dataclasses import dataclass

import pytest
import pytest_check as check

from main_app.models import TUser
from main_app.services.errors import IdentityProviderOperationError, UserNotFoundError
from main_app.services.user_service import UserService
from modules.keycloak_admin.templates import tenant_realm_name
from modules.tenancy.context import TenantContext


@dataclass
class Env:
    ctx: TenantContext
    realm: str
    actor_sub: str


@pytest.fixture
def env(ap_db, idp) -> Env:
    """使い捨てのテナントと、操作者(IdP・AP の両方に存在する tenant_admin)。"""
    ctx = ap_db.tenant()
    realm = tenant_realm_name(ctx.tenant_code)
    sub = idp.seed_user(realm, username="admin@example.com", email="admin@example.com", first_name="Ada", last_name="Admin", roles=("tenant_admin",))
    ap_db.add_user(ctx, sub=sub, email="admin@example.com", display_name="Ada Admin")
    return Env(ctx=ctx, realm=realm, actor_sub=sub)


@pytest.fixture
def run(ap_db, idp, env):
    """``run(lambda service: ...)`` でセッション・サービスを作って呼ぶ(``ctx`` を変えられる)。"""

    def call(func, *, ctx=None):
        with ap_db.session(ctx or env.ctx) as session:
            return func(UserService(session, idp.factory, actor_subject=env.actor_sub, password_generator=lambda: "Sentinel-Passw0rd-VALUE-1!"))

    return call


@pytest.fixture
def make_user(ap_db, idp, env):
    """IdP と AP の両方にユーザーを作る。``copies=False`` で写しは未同期(姓・名 NULL、ロール空)にする。"""

    def create(*, email="bob@example.com", first="Bob", last="Builder", roles=("member",), copies=True, ctx=None, active=True, name=None):
        target = ctx or env.ctx
        realm = tenant_realm_name(target.tenant_code)
        sub = idp.seed_user(realm, username=email, email=email, first_name=first, last_name=last, roles=roles, enabled=active)
        with ap_db.session(target) as session:
            user = TUser(
                tenant_id=target.tenant_id, idp_subject=sub, email=email, display_name=name or f"{first} {last}", is_active=active,
                first_name=first if copies else None, last_name=last if copies else None, roles=(["member"] if copies else []),
            )
            session.add(user)
            session.commit()
            return user.id, sub

    return create


def row(ap_db, ctx, user_id) -> dict:
    return ap_db.user(ctx, user_id)


def create_args(**overrides):
    args = {"email": "alice@example.com", "first_name": "Alice", "last_name": "Liddell"}
    args.update(overrides)
    return args


class TestCreate:
    """create_user: IdP に設定した値を写しにする。"""

    @pytest.mark.parametrize(
        ("given", "expected"),
        [(["member"], ["member"]), (["tenant_admin"], ["tenant_admin", "member"]), (["member", "tenant_admin"], ["tenant_admin", "member"]), (["tenant_admin", "tenant_admin"], ["tenant_admin", "member"])],
        ids=["member", "admin-includes-default-member", "both", "duplicates"],
    )
    def test_copies_are_stored(self, run, ap_db, env, given, expected):
        """姓・名と、実効ロール(直接付与 + 既定ロール member を tenant_admin, member の順で)が AP の行に入る。応答のビューも同じ。"""
        result = run(lambda s: s.create_user(**create_args(roles=given)))
        stored = row(ap_db, env.ctx, result.user.id)
        check.equal((stored["first_name"], stored["last_name"], stored["roles"], stored["version"]), ("Alice", "Liddell", expected, 1))
        check.equal((result.user.first_name, result.user.last_name, list(result.user.roles)), ("Alice", "Liddell", expected))

    def test_names_are_trimmed(self, run, ap_db, env):
        """姓・名の前後の空白は除いた値が IdP にも写しにも入る。"""
        result = run(lambda s: s.create_user(**create_args(first_name="  Alice ", last_name=" Liddell  ")))
        stored = row(ap_db, env.ctx, result.user.id)
        check.equal((stored["first_name"], stored["last_name"], stored["display_name"]), ("Alice", "Liddell", "Alice Liddell"))

    def test_roles_in_idp_and_copy_agree(self, run, idp, env):
        """直接付与するロール(IdP)と写しのロールは、写しが「直接付与 + 既定ロール」の関係になる。"""
        result = run(lambda s: s.create_user(**create_args(roles=["tenant_admin"])))
        sub = next(u["id"] for u in idp.users(env.realm).values() if u["email"] == "alice@example.com")
        check.equal(idp.direct_roles(env.realm, sub), ["tenant_admin"])
        check.equal(list(result.user.roles), ["tenant_admin", "member"])


class TestUpdate:
    """update_user: 姓・名を変えたら姓・名の写し、ロールを変えたらロールの写しを更新する。"""

    def test_names_update_the_copies(self, run, ap_db, idp, env, make_user):
        """姓・名の更新は IdP と AP の写しと表示名を更新し、version を +1 する。ロールの写しは変えない。"""
        user_id, sub = make_user(roles=("tenant_admin",))
        view = run(lambda s: s.update_user(user_id, expected_version=1, first_name="Robert", last_name="Builder-Smith"))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((stored["first_name"], stored["last_name"], stored["display_name"], stored["version"]), ("Robert", "Builder-Smith", "Robert Builder-Smith", 2))
        check.equal(stored["roles"], ["member"])
        check.equal((idp.users(env.realm)[sub]["firstName"], idp.users(env.realm)[sub]["lastName"]), ("Robert", "Builder-Smith"))
        check.equal((view.first_name, view.last_name, view.version), ("Robert", "Builder-Smith", 2))

    @pytest.mark.parametrize(
        ("roles", "expected"), [(["tenant_admin"], ["tenant_admin", "member"]), (["member"], ["member"]), (["member", "tenant_admin"], ["tenant_admin", "member"])]
    )
    def test_roles_update_the_copy(self, run, ap_db, env, make_user, roles, expected):
        """ロールの更新は写しを「直接付与 + 既定ロール」の実効ロールにする。姓・名の写しは変えない。"""
        user_id, _ = make_user()
        view = run(lambda s: s.update_user(user_id, expected_version=1, roles=roles))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((stored["roles"], stored["first_name"], stored["last_name"]), (expected, "Bob", "Builder"))
        check.equal(list(view.roles), expected)

    def test_demoting_to_member_updates_the_copy(self, run, ap_db, env, make_user):
        """tenant_admin だったユーザーを member にすると、写しも ["member"] になる。"""
        user_id, _ = make_user(roles=("tenant_admin",))
        with ap_db.session(env.ctx) as session:
            session.connection().exec_driver_sql("UPDATE t_user SET roles = ARRAY['tenant_admin', 'member'] WHERE id = %s", (user_id,))
            session.commit()
        run(lambda s: s.update_user(user_id, expected_version=1, roles=["member"]))
        check.equal(row(ap_db, env.ctx, user_id)["roles"], ["member"])

    def test_is_active_only_leaves_the_copies(self, run, ap_db, env, make_user):
        """有効/無効だけの更新では、姓・名・ロールの写しは変わらない。"""
        user_id, _ = make_user()
        run(lambda s: s.update_user(user_id, expected_version=1, is_active=False))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((stored["first_name"], stored["last_name"], stored["roles"], stored["is_active"], stored["version"]), ("Bob", "Builder", ["member"], False, 2))

    def test_noop_update_changes_nothing(self, run, ap_db, env, make_user):
        """同じ値での更新は何もしない(IdP にも書かず、version も写しも変わらない)。"""
        user_id, _ = make_user()
        run(lambda s: s.update_user(user_id, expected_version=1, first_name="Bob", last_name="Builder"))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((stored["first_name"], stored["last_name"], stored["version"]), ("Bob", "Builder", 1))

    def test_same_display_name_with_different_split_updates_the_copies(self, run, ap_db, env, make_user):
        """表示名が同じでも姓・名の区切りが変わる更新(Mary Ann + Smith -> Mary + Ann Smith)は、写しが既知なら変更として写しを更新する。"""
        user_id, _ = make_user(first="Mary Ann", last="Smith")
        view = run(lambda s: s.update_user(user_id, expected_version=1, first_name="Mary", last_name="Ann Smith"))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((stored["first_name"], stored["last_name"], stored["display_name"], stored["version"]), ("Mary", "Ann Smith", "Mary Ann Smith", 2))
        check.equal(view.version, 2)

    def test_unsynced_copy_is_not_filled_by_a_noop_update(self, run, ap_db, env, make_user):
        """写しが未同期(NULL)の行に、表示名と同じ姓・名で更新しても変更なし(写しは NULL のまま。埋めるのは get_user とログイン)。"""
        user_id, _ = make_user(copies=False)
        view = run(lambda s: s.update_user(user_id, expected_version=1, first_name="Bob", last_name="Builder"))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((stored["first_name"], stored["last_name"], stored["version"], view.first_name), (None, None, 1, None))

    def test_idp_failure_leaves_copies_unchanged(self, run, ap_db, idp, env, make_user):
        """IdP の更新が失敗したら 502 相当(IdentityProviderOperationError)で、AP の写しも version も変えない。"""
        user_id, _ = make_user()
        idp.fail("PUT", r"/users/[^/]+$", 500)
        with pytest.raises(IdentityProviderOperationError):
            run(lambda s: s.update_user(user_id, expected_version=1, first_name="Robert", last_name="Builder"))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((stored["first_name"], stored["version"]), ("Bob", 1))

    def test_audit_changes_include_names_only_when_known(self, run, ap_db, env, make_user):
        """監査ログの差分に姓・名を含めるのは、写しが既知だった場合だけ(未同期の行では表示名の差分のみ)。"""
        known_id, _ = make_user(email="k@example.com")
        unsynced_id, _ = make_user(email="u@example.com", copies=False)
        run(lambda s: s.update_user(known_id, expected_version=1, first_name="Robert", last_name="Builder"))
        run(lambda s: s.update_user(unsynced_id, expected_version=1, first_name="Robert", last_name="Builder"))
        audits = {a["target_id"]: a["payload"]["changes"] for a in ap_db.audits(env.ctx, "user.update")}
        check.equal(set(audits[str(known_id)]), {"display_name", "first_name"})
        check.equal(set(audits[str(unsynced_id)]), {"display_name"})


class TestGetUser:
    """get_user: IdP の値で写しを更新する。"""

    def test_stale_copy_is_refreshed_and_version_bumped(self, run, ap_db, idp, env, make_user):
        """IdP の姓・名・メール・ロールが写しと違えば、写しと表示名・メールを更新して version を +1 し、user.sync(source=idp)を残す。応答は更新後の値。"""
        user_id, sub = make_user()
        user = idp.users(env.realm)[sub]
        user.update({"firstName": "Robert", "lastName": "Builder-Smith", "email": "robert@example.com"})
        idp.state_for(env.realm).user_realm_roles[sub] = ["tenant_admin"]
        view = run(lambda s: s.get_user(user_id))
        stored = row(ap_db, env.ctx, user_id)
        check.equal(
            (stored["first_name"], stored["last_name"], stored["display_name"], stored["email"], stored["roles"], stored["version"]),
            ("Robert", "Builder-Smith", "Robert Builder-Smith", "robert@example.com", ["tenant_admin", "member"], 2),
        )
        check.equal((view.first_name, view.last_name, list(view.roles), view.version, view.email), ("Robert", "Builder-Smith", ["tenant_admin", "member"], 2, "robert@example.com"))
        sync = ap_db.audits(env.ctx, "user.sync")
        check.equal(len(sync), 1)
        check.equal((sync[0]["payload"]["source"], sync[0]["actor_id"], stored["updated_by"]), ("idp", None, None))
        check.equal(set(sync[0]["payload"]["changes"]), {"display_name", "email", "first_name", "last_name", "roles"})

    def test_matching_copy_changes_nothing(self, run, ap_db, env, make_user):
        """IdP と写しが一致していれば何も更新しない(version は同じ、監査ログも残さない)。"""
        user_id, _ = make_user()
        view = run(lambda s: s.get_user(user_id))
        check.equal((view.version, row(ap_db, env.ctx, user_id)["version"], ap_db.audits(env.ctx, "user.sync")), (1, 1, []))

    def test_unsynced_row_is_filled_without_bumping_version(self, run, ap_db, env, make_user):
        """姓・名が NULL、ロールが空の行(同期前・列の追加前)は、初回の埋め込みとして値を書くが version は上げず、監査ログも残さない。"""
        user_id, _ = make_user(copies=False, roles=("tenant_admin",))
        view = run(lambda s: s.get_user(user_id))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((stored["first_name"], stored["last_name"], stored["roles"], stored["version"]), ("Bob", "Builder", ["tenant_admin", "member"], 1))
        check.equal((view.first_name, list(view.roles), view.version), ("Bob", ["tenant_admin", "member"], 1))
        check.equal(ap_db.audits(env.ctx, "user.sync"), [])
        # 埋め込んだ値は永続化されている(次の取得で変更にならない)
        check.equal(run(lambda s: s.get_user(user_id)).version, 1)

    def test_roles_come_from_effective_realm_roles(self, run, ap_db, idp, env, make_user):
        """ロールの写しは IdP の実効ロール(既定ロール member を含む)のうち tenant_admin / member。realm の他のロールは含めない。"""
        user_id, sub = make_user(copies=False, roles=("member",))
        idp.state_for(env.realm).roles["offline_access"] = {"id": str(uuid.uuid4()), "name": "offline_access"}
        idp.state_for(env.realm).user_realm_roles[sub] = ["offline_access"]
        run(lambda s: s.get_user(user_id))
        check.equal(row(ap_db, env.ctx, user_id)["roles"], ["member"])

    def test_cleared_idp_names_clear_the_copies(self, run, ap_db, idp, env, make_user):
        """IdP の姓・名が空になっていたら写しを NULL にする(変更として version を +1)。表示名は保存済みの値のまま。"""
        user_id, sub = make_user()
        idp.users(env.realm)[sub].update({"firstName": "", "lastName": ""})
        view = run(lambda s: s.get_user(user_id))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((stored["first_name"], stored["last_name"], stored["display_name"], stored["version"]), (None, None, "Bob Builder", 2))
        check.equal((view.first_name, view.last_name, view.display_name), (None, None, "Bob Builder"))

    def test_missing_idp_email_keeps_stored_email(self, run, ap_db, idp, env, make_user):
        """IdP にメールアドレスが無くても、保存済みのメールアドレスは残す。"""
        user_id, sub = make_user()
        idp.users(env.realm)[sub].pop("email")
        view = run(lambda s: s.get_user(user_id))
        check.equal((view.email, row(ap_db, env.ctx, user_id)["email"], view.version), ("bob@example.com", "bob@example.com", 1))

    def test_is_active_is_not_changed(self, run, ap_db, idp, env, make_user):
        """有効/無効は AP の DB が正。IdP が有効でも、AP で無効化されたユーザーは無効のまま(get_user で変えない)。"""
        user_id, sub = make_user(active=False)
        idp.users(env.realm)[sub]["enabled"] = True
        view = run(lambda s: s.get_user(user_id))
        check.equal((view.is_active, row(ap_db, env.ctx, user_id)["is_active"]), (False, False))

    def test_user_missing_in_idp_returns_the_copy(self, run, ap_db, idp, env, make_user, caplog):
        """IdP にユーザーが無い(IdP で直接削除された)場合は、警告ログを残して写しのまま返す。version も行も変えない。"""
        user_id, sub = make_user()
        idp.users(env.realm).pop(sub)
        with caplog.at_level(logging.WARNING):
            view = run(lambda s: s.get_user(user_id))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((view.first_name, view.last_name, view.version, stored["version"]), ("Bob", "Builder", 1, 1))
        check.is_in("IdP にユーザーが見つからない", caplog.text)
        check.equal(ap_db.audits(env.ctx, "user.sync"), [])

    def test_idp_user_lookup_failure_is_502(self, run, ap_db, idp, env, make_user):
        """IdP のユーザー取得に失敗したら IdentityProviderOperationError(502)。AP の行は変更しない。"""
        user_id, sub = make_user()
        idp.users(env.realm)[sub].update({"firstName": "Changed"})
        idp.fail("GET", r"/users/[^/]+$", 500)
        with pytest.raises(IdentityProviderOperationError) as caught:
            run(lambda s: s.get_user(user_id))
        check.is_in("get_user", str(caught.value))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((stored["first_name"], stored["version"]), ("Bob", 1))

    def test_idp_role_lookup_failure_is_502(self, run, ap_db, idp, env, make_user):
        """IdP の実効ロールの取得に失敗したら IdentityProviderOperationError(502)。AP の行は変更しない。"""
        user_id, sub = make_user()
        idp.users(env.realm)[sub].update({"firstName": "Changed"})
        idp.fail("GET", r"role-mappings/realm/composite$", 500)
        with pytest.raises(IdentityProviderOperationError) as caught:
            run(lambda s: s.get_user(user_id))
        check.is_in("get_user_roles", str(caught.value))
        stored = row(ap_db, env.ctx, user_id)
        check.equal((stored["first_name"], stored["version"]), ("Bob", 1))

    def test_failure_does_not_leak_idp_detail(self, run, idp, env, make_user):
        """502 のメッセージに IdP のエラー詳細を含めない(操作名とステータスの要約のみ)。"""
        user_id, _ = make_user()
        idp.fail("GET", r"/users/[^/]+$", 500)
        with pytest.raises(IdentityProviderOperationError) as caught:
            run(lambda s: s.get_user(user_id))
        check.is_not_in("injected", repr(caught.value) + str(caught.value.args))

    def test_other_tenant_user_is_not_found_without_asking_idp(self, run, ap_db, idp, env, make_user):
        """他テナントのユーザー ID は存在しないのと同じ(UserNotFoundError)で、IdP には問い合わせない。他テナントの写しも変わらない。"""
        other = ap_db.tenant()
        foreign_id, foreign_sub = make_user(ctx=other, email="foreign@example.com")
        idp.users(tenant_realm_name(other.tenant_code))[foreign_sub].update({"firstName": "Changed"})
        before = len(idp.factory_realms)
        with pytest.raises(UserNotFoundError):
            run(lambda s: s.get_user(foreign_id))
        check.equal(len(idp.factory_realms), before)
        check.equal(row(ap_db, other, foreign_id)["first_name"], "Bob")
        check.equal(row(ap_db, other, foreign_id)["version"], 1)

    def test_unknown_user_is_not_found(self, run, idp):
        """存在しない ID は UserNotFoundError。IdP に問い合わせない。"""
        with pytest.raises(UserNotFoundError):
            run(lambda s: s.get_user(uuid.uuid4()))
        check.equal(idp.factory_realms, [])

    def test_listing_shows_the_refreshed_copy(self, run, ap_db, idp, env, make_user):
        """詳細の取得で更新した写しが、一覧(IdP に問い合わせない)にも反映される。取得するまでは古い値のまま。"""
        user_id, sub = make_user()
        idp.users(env.realm)[sub].update({"firstName": "Robert"})
        idp.state_for(env.realm).user_realm_roles[sub] = ["tenant_admin"]
        before = {v.id: v for v in run(lambda s: s.list_users()).items}[user_id]
        check.equal((before.first_name, list(before.roles)), ("Bob", ["member"]))
        run(lambda s: s.get_user(user_id))
        after = {v.id: v for v in run(lambda s: s.list_users()).items}[user_id]
        check.equal((after.first_name, list(after.roles)), ("Robert", ["tenant_admin", "member"]))

