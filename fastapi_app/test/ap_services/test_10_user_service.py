# -*- coding: utf-8 -*-
"""main_app.services.user_service(ユーザー管理。PF-USR-01..03)のテスト。

- Keycloak は ``TenantRealmIdp``(状態を持つフェイク)。``kc_admin_factory`` に差し替える。外部の Keycloak には接続しない。
- DB は開発 DB の ``app_db``。使い捨てのテナントを作り、終了時に監査ログを含めて削除する(``ap_db``)。alpha / beta には触れない。
"""
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest
import pytest_check as check

from main_app.services import user_service
from main_app.services.common import UNSET
from main_app.services.errors import (
    IdentityProviderOperationError,
    InvalidUserRoleError,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserSelfModificationError,
    UserValidationError,
    UserVersionConflictError,
)
from main_app.services.user_service import TEMPORARY_PASSWORD_LENGTH, UserService, generate_temporary_password
from modules.keycloak_admin.templates import tenant_realm_name
from modules.tenancy.context import TenantContext

SENTINEL_PASSWORD = "Sentinel-Passw0rd-VALUE-1!"
USERS_PATH = r"/users$"


@dataclass
class Env:
    """1 つの使い捨てテナントと、そのレルム・操作者。"""

    ctx: TenantContext
    realm: str
    actor: object  # 操作者(tenant_admin)の t_user(切り離した値)


@pytest.fixture
def env(ap_db, idp) -> Env:
    """使い捨てのテナントと、操作者(IdP・AP の両方に存在する tenant_admin)。"""
    ctx = ap_db.tenant()
    realm = tenant_realm_name(ctx.tenant_code)
    sub = idp.seed_user(realm, username="admin@example.com", email="admin@example.com", first_name="Ada", last_name="Admin", roles=("tenant_admin",))
    actor = ap_db.add_user(ctx, sub=sub, email="admin@example.com", display_name="Ada Admin")
    return Env(ctx=ctx, realm=realm, actor=actor)


@pytest.fixture
def run(ap_db, idp, env):
    """``run(lambda service: ...)`` でセッション・サービスを作って呼ぶ。``actor`` を変えられる。"""

    def call(func, *, ctx=None, actor_sub=UNSET, password_generator=lambda: SENTINEL_PASSWORD):
        target = ctx or env.ctx
        subject = env.actor.idp_subject if actor_sub is UNSET else actor_sub
        with ap_db.session(target) as session:
            return func(UserService(session, idp.factory, actor_subject=subject, password_generator=password_generator))

    return call


@pytest.fixture
def make_user(ap_db, idp, env):
    """IdP と AP の両方にユーザーを作る(ログイン同期済みの状態)。"""

    def create(*, email="bob@example.com", first="Bob", last="Builder", roles=("member",), ctx=None, active=True):
        target = ctx or env.ctx
        realm = tenant_realm_name(target.tenant_code)
        sub = idp.seed_user(realm, username=email, email=email, first_name=first, last_name=last, roles=roles, enabled=active)
        return ap_db.add_user(target, sub=sub, email=email, display_name=f"{first} {last}", is_active=active)

    return create


def create_args(**overrides):
    args = {"email": "Alice@Example.com", "first_name": "Alice", "last_name": "Liddell"}
    args.update(overrides)
    return args


class TestCreateUser:
    """ユーザーの作成(IdP → AP の順。PF-USR-01 / 02)。"""

    def test_creates_in_idp_and_ap(self, run, ap_db, idp, env):
        """IdP にユーザー(ユーザー名=メールの小文字、有効、メール確認済み、姓・名、初回に UPDATE_PASSWORD)と一時パスワード(temporary)を作り、AP の行を作る。"""
        result = run(lambda s: s.create_user(**create_args()))
        users = idp.users(env.realm)
        created = next(u for u in users.values() if u["username"] == "alice@example.com")
        check.equal((created["email"], created["firstName"], created["lastName"], created["enabled"], created["emailVerified"]), ("Alice@Example.com", "Alice", "Liddell", True, True))
        check.equal(created["requiredActions"], ["UPDATE_PASSWORD"])
        check.equal(idp.passwords(env.realm)[created["id"]], {"value": SENTINEL_PASSWORD, "temporary": True})
        check.equal(idp.direct_roles(env.realm, created["id"]), ["member"])
        check.equal(idp.factory_realms, [env.realm])

        row = ap_db.user(env.ctx, result.user.id)
        check.equal((row["idp_subject"], row["email"], row["display_name"], row["is_active"], row["version"]), (created["id"], "Alice@Example.com", "Alice Liddell", True, 1))
        check.equal((row["created_by"], row["updated_by"]), (env.actor.id, env.actor.id))
        check.equal((result.username, result.roles, result.temporary_password), ("alice@example.com", ("member",), SENTINEL_PASSWORD))
        check.equal((result.user.id, result.user.version, result.user.is_active), (row["id"], 1, True))

    def test_audit_log_has_no_password(self, run, ap_db, env):
        """監査ログ user.create(actor=操作者、source=admin、ユーザー名・メール・表示名・ロール)を残す。一時パスワードは含まない。"""
        result = run(lambda s: s.create_user(**create_args(roles=["tenant_admin", "member"])))
        audit = ap_db.audits(env.ctx, "user.create")
        check.equal(len(audit), 1)
        check.equal((audit[0]["actor_id"], audit[0]["target_type"], audit[0]["target_id"]), (env.actor.id, "user", str(result.user.id)))
        check.equal(audit[0]["payload"], {"source": "admin", "username": "alice@example.com", "email": "Alice@Example.com", "display_name": "Alice Liddell", "roles": ["tenant_admin", "member"]})
        check.is_not_in(SENTINEL_PASSWORD, repr(audit))

    def test_roles_are_assigned_as_given(self, run, idp, env):
        """指定したロールだけを直接付与する(tenant_admin のみを指定すれば member は直接付与しない)。重複は除く。"""
        result = run(lambda s: s.create_user(**create_args(roles=["tenant_admin", "tenant_admin"])))
        sub = next(u["id"] for u in idp.users(env.realm).values() if u["username"] == "alice@example.com")
        check.equal(idp.direct_roles(env.realm, sub), ["tenant_admin"])
        check.equal(result.roles, ("tenant_admin",))

    def test_explicit_username_is_lowercased(self, run, idp, env):
        """username を指定すれば小文字に正規化してログイン名にする(メールとは別)。"""
        result = run(lambda s: s.create_user(**create_args(username="Alice.L")))
        check.equal(result.username, "alice.l")
        check.is_in("alice.l", {u["username"] for u in idp.users(env.realm).values()})

    def test_created_by_is_none_without_actor_row(self, run, ap_db, env):
        """操作者のユーザー行が無い(ログイン同期前)場合は、created_by / actor を NULL(システム処理)にして作成する。"""
        result = run(lambda s: s.create_user(**create_args()), actor_sub="unsynced-subject")
        row = ap_db.user(env.ctx, result.user.id)
        check.is_none(row["created_by"])
        check.is_none(ap_db.audits(env.ctx, "user.create")[0]["actor_id"])

    def test_actor_defaults_to_context_user(self, ap_db, idp, env):
        """actor_subject を省略すると、テナントコンテキストの user_id(セッションの sub)から操作者を解決する。"""
        ctx = TenantContext(tenant_id=env.ctx.tenant_id, tenant_code=env.ctx.tenant_code, user_id=uuid.UUID(env.actor.idp_subject), plane="app")
        with ap_db.session(ctx) as session:
            result = UserService(session, idp.factory, password_generator=lambda: SENTINEL_PASSWORD).create_user(**create_args())
        check.equal(ap_db.user(env.ctx, result.user.id)["created_by"], env.actor.id)

    @pytest.mark.parametrize(
        ("overrides", "field", "reason"),
        [
            ({"email": ""}, "email", "required"),
            ({"email": "   "}, "email", "required"),
            ({"email": "no-at-sign"}, "email", "format"),
            ({"email": "a b@example.com"}, "email", "format"),
            ({"email": "a@b"}, "email", "format"),
            ({"email": "a" * 250 + "@example.com"}, "email", "too_long"),
            ({"first_name": " "}, "first_name", "required"),
            ({"last_name": ""}, "last_name", "required"),
            ({"first_name": "x" * 101}, "first_name", "too_long"),
            ({"last_name": "bad\nname"}, "last_name", "format"),
            ({"username": "ab"}, "username", "format"),
            ({"username": "has space"}, "username", "format"),
            ({"username": "日本語名前"}, "username", "format"),
            ({"roles": []}, "roles", "required"),
            ({"roles": "member"}, "roles", "type"),
        ],
    )
    def test_invalid_input_changes_nothing(self, run, ap_db, idp, env, overrides, field, reason):
        """入力が不正なら UserValidationError(項目と理由付き)。IdP にも AP にも書き込まない。"""
        before = len(idp.users(env.realm))
        with pytest.raises(UserValidationError) as caught:
            run(lambda s: s.create_user(**create_args(**overrides)))
        check.equal((caught.value.field, caught.value.reason), (field, reason))
        check.equal(len(idp.users(env.realm)), before)
        check.equal(idp.writes, [])
        check.equal(len(ap_db.users(env.ctx)), 1)  # 操作者のみ

    @pytest.mark.parametrize("roles", [["saas_admin"], ["member", "admin"], ["manage-users"], ["realm-management"], ["default-roles-x"], ["TENANT_ADMIN"]])
    def test_non_tenant_roles_are_rejected(self, run, ap_db, idp, env, roles):
        """tenant_admin / member 以外のロール(CP のロール・realm-management のロール等)は InvalidUserRoleError。許可外のロールだけを roles に持つ。IdP に書き込まない。"""
        with pytest.raises(InvalidUserRoleError) as caught:
            run(lambda s: s.create_user(**create_args(roles=roles)))
        check.equal(set(caught.value.roles), {r for r in roles if r not in ("member",)})
        check.equal((caught.value.field, caught.value.reason, caught.value.code), ("roles", "not_allowed", "invalid_user_role"))
        check.equal(idp.writes, [])
        check.equal(len(ap_db.users(env.ctx)), 1)

    def test_duplicate_email_in_ap_is_rejected_before_idp(self, run, make_user, idp, env):
        """AP に同じメール(大文字小文字を区別しない)のユーザーがいれば、IdP を呼ぶ前に UserAlreadyExistsError。"""
        make_user(email="alice@example.com")
        with pytest.raises(UserAlreadyExistsError):
            run(lambda s: s.create_user(**create_args(email="ALICE@example.com", username="someone-else")))
        check.equal(idp.writes, [])
        check.equal(idp.factory_realms, [])

    def test_same_email_in_other_tenant_is_allowed(self, run, ap_db, idp, env):
        """別テナントの同じメールは重複にならない(PF-USR-06)。両方のテナントに作成できる。"""
        other = ap_db.tenant()
        first = run(lambda s: s.create_user(**create_args()))
        second = run(lambda s: s.create_user(**create_args()), ctx=other, actor_sub="none")
        check.not_equal(first.user.id, second.user.id)
        check.equal(idp.factory_realms[-1], tenant_realm_name(other.tenant_code))
        check.equal(len(ap_db.users(other)), 1)

    def test_duplicate_in_idp_is_user_already_exists(self, run, idp, ap_db, env):
        """IdP に同じユーザー名・メールが既にある(AP の行は無い。409)と UserAlreadyExistsError。AP には作らない。"""
        idp.seed_user(env.realm, username="alice@example.com", email="alice@example.com")
        with pytest.raises(UserAlreadyExistsError):
            run(lambda s: s.create_user(**create_args()))
        check.equal(len(ap_db.users(env.ctx)), 1)

    def test_idp_failure_is_502_and_ap_unchanged(self, run, idp, ap_db, env, caplog):
        """IdP の作成が失敗(500)したら IdentityProviderOperationError(502 系)。要約に秘匿値を含まず、AP には作らない。"""
        idp.fail("POST", USERS_PATH, 500)
        with caplog.at_level(logging.DEBUG), pytest.raises(IdentityProviderOperationError) as caught:
            run(lambda s: s.create_user(**create_args()))
        check.equal(caught.value.operation, "create_user")
        check.equal(caught.value.error_summary, "operation=create_user; error=KeycloakAdminError; http_status=500")
        check.is_not_in(SENTINEL_PASSWORD, str(caught.value) + repr(caught.value) + caplog.text)
        check.equal(len(ap_db.users(env.ctx)), 1)
        check.equal(ap_db.audits(env.ctx, "user.create"), [])

    def test_failure_after_idp_create_removes_the_idp_user(self, run, idp, ap_db, env):
        """IdP でパスワードの設定に失敗したら、作りかけの IdP のユーザーを残さない(tenant_users の補償)。AP にも作らない。"""
        idp.fail("PUT", r"/reset-password$", 500)
        with pytest.raises(IdentityProviderOperationError):
            run(lambda s: s.create_user(**create_args()))
        check.is_none(idp.user_by_email(env.realm, "alice@example.com"))
        check.equal(len(ap_db.users(env.ctx)), 1)


class TestCreateUserCompensation:
    """AP 側の失敗時に IdP のユーザーを削除する補償。"""

    def test_ap_integrity_error_deletes_idp_user(self, run, idp, ap_db, env):
        """IdP への作成の直後に別のリクエストが同じメールの行を作った(一意制約違反)場合、UserAlreadyExistsError にして IdP のユーザーを削除する。"""
        winner = {}

        def other_request_wins():
            winner["row"] = ap_db.add_user(env.ctx, sub="winner-sub", email="alice@example.com")

        idp.after("POST", USERS_PATH, other_request_wins)
        with pytest.raises(UserAlreadyExistsError):
            run(lambda s: s.create_user(**create_args()))
        check.equal(len(idp.deleted), 1)
        check.is_none(idp.user_by_email(env.realm, "alice@example.com"))
        check.equal([u["idp_subject"] for u in ap_db.users(env.ctx) if u["email"] == "alice@example.com"], ["winner-sub"])
        check.equal(ap_db.audits(env.ctx, "user.create"), [])

    def test_ap_unexpected_error_deletes_idp_user_and_reraises(self, run, idp, ap_db, env, monkeypatch):
        """AP の書き込み中に想定外の例外が起きても、IdP のユーザーを削除してから元の例外を送出する。AP には何も残らない。"""

        def boom(*args, **kwargs):
            raise RuntimeError("db is broken")

        monkeypatch.setattr(user_service, "record_audit", boom)
        with pytest.raises(RuntimeError, match="db is broken"):
            run(lambda s: s.create_user(**create_args()))
        check.equal(len(idp.deleted), 1)
        check.is_none(idp.user_by_email(env.realm, "alice@example.com"))
        check.equal(len(ap_db.users(env.ctx)), 1)

    def test_compensation_failure_keeps_original_error_and_logs(self, run, idp, env, monkeypatch, caplog):
        """補償の削除も失敗(500)した場合は、元の例外を送出し、手動削除が必要なことをエラーログに残す(秘匿値は含めない)。"""

        def boom(*args, **kwargs):
            raise RuntimeError("db is broken")

        monkeypatch.setattr(user_service, "record_audit", boom)
        idp.fail("DELETE", r"/users/[^/]+$", 500)
        with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError, match="db is broken"):
            run(lambda s: s.create_user(**create_args()))
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        check.equal(len(errors), 1)
        check.is_in("手動で削除が必要", errors[0].getMessage())
        check.is_not_in(SENTINEL_PASSWORD, caplog.text)
        check.is_not_none(idp.user_by_email(env.realm, "alice@example.com"))  # 削除できなかったので残っている(ログで検知できる)


class TestTemporaryPassword:
    """一時パスワードはレスポンス(戻り値)にだけ返し、どこにも残さない(PF-USR-02)。"""

    def test_password_is_not_stored_or_logged_anywhere_on_ap_side(self, run, ap_db, env, caplog):
        """成功した作成の後、AP の DB(ユーザー・組織・所属・監査ログ)、ログ、戻り値の repr に一時パスワードが現れない(戻り値の属性を除く)。"""
        with caplog.at_level(logging.DEBUG):
            result = run(lambda s: s.create_user(**create_args()))
        check.equal(result.temporary_password, SENTINEL_PASSWORD)
        check.is_not_in(SENTINEL_PASSWORD, ap_db.dump(env.ctx))
        check.is_not_in(SENTINEL_PASSWORD, caplog.text)
        check.is_not_in(SENTINEL_PASSWORD, repr(result))
        check.is_in("temporary_password=***", repr(result))
        check.is_not_in(SENTINEL_PASSWORD, repr(result.user))

    def test_password_is_not_in_any_error(self, run, idp, ap_db, env, caplog):
        """失敗した作成でも、例外のメッセージ・属性・原因・ログに一時パスワードが現れない。"""
        idp.fail("PUT", r"/reset-password$", 400)
        with caplog.at_level(logging.DEBUG), pytest.raises(IdentityProviderOperationError) as caught:
            run(lambda s: s.create_user(**create_args()))
        text = f"{caught.value!s} {caught.value!r} {caught.value.__dict__} {caught.value.__cause__!s} {caught.value.__cause__!r}"
        check.is_not_in(SENTINEL_PASSWORD, text)
        check.is_not_in(SENTINEL_PASSWORD, caplog.text)
        check.is_not_in(SENTINEL_PASSWORD, ap_db.dump(env.ctx))

    def test_idp_receives_the_same_password_once_as_temporary(self, run, idp, env):
        """IdP に送るパスワードは戻り値と同じ 1 回だけで、temporary=True(初回ログインで変更を強制する)。"""
        result = run(lambda s: s.create_user(**create_args()), password_generator=lambda: "Another-Passw0rd-2!")
        check.equal([(p[2], p[3]) for p in idp.password_sets], [("Another-Passw0rd-2!", True)])
        check.equal(result.temporary_password, "Another-Passw0rd-2!")

    def test_generator_default_has_required_character_classes(self):
        """既定の生成関数は 20 文字で英大文字・英小文字・数字・記号を含み、呼ぶたびに異なる。長さ 4 未満は ValueError。"""
        passwords = {generate_temporary_password() for _ in range(50)}
        check.equal(len(passwords), 50)
        for password in passwords:
            check.equal(len(password), TEMPORARY_PASSWORD_LENGTH)
            check.is_true(any(c.islower() for c in password) and any(c.isupper() for c in password) and any(c.isdigit() for c in password) and any(not c.isalnum() for c in password))
        with pytest.raises(ValueError):
            generate_temporary_password(3)


class TestGetAndList:
    """参照。他テナントのユーザーは見えない。"""

    def test_get_user_returns_view(self, run, make_user):
        """ID でユーザーを取得できる(IdP の利用者 ID を含む切り離したビュー)。"""
        user = make_user()
        view = run(lambda s: s.get_user(user.id))
        check.equal((view.id, view.email, view.display_name, view.version, view.is_active, view.idp_subject), (user.id, "bob@example.com", "Bob Builder", 1, True, user.idp_subject))

    def test_get_unknown_user_is_not_found(self, run):
        """存在しない ID は UserNotFoundError。"""
        with pytest.raises(UserNotFoundError):
            run(lambda s: s.get_user(uuid.uuid4()))

    def test_other_tenant_user_is_not_found(self, run, ap_db, idp, make_user):
        """他テナントのユーザー ID は、存在しない ID と同じ UserNotFoundError(存在を明かさない)。IdP も呼ばない。"""
        other = ap_db.tenant()
        foreign = make_user(ctx=other, email="foreign@example.com")
        with pytest.raises(UserNotFoundError):
            run(lambda s: s.get_user(foreign.id))
        with pytest.raises(UserNotFoundError):
            run(lambda s: s.get_user_roles(foreign.id))
        check.equal(idp.factory_realms, [])

    def test_list_excludes_other_tenant_and_counts(self, run, ap_db, make_user, env):
        """一覧には自テナントのユーザーだけが含まれる(他テナントのユーザーは件数にも現れない)。"""
        other = ap_db.tenant()
        make_user(email="a@example.com")
        make_user(ctx=other, email="b@example.com")
        make_user(ctx=other, email="c@example.com")
        page = run(lambda s: s.list_users())
        check.equal(sorted(v.email for v in page.items), ["a@example.com", "admin@example.com"])
        other_page = run(lambda s: s.list_users(), ctx=other)
        check.equal(sorted(v.email for v in other_page.items), ["b@example.com", "c@example.com"])

    def test_list_filters_and_pagination(self, run, make_user):
        """is_active で絞り込め、limit / after で重複・欠落なくページングできる。無効化されたユーザーも既定で含む。"""
        for i in range(4):
            make_user(email=f"u{i}@example.com", first=f"U{i}", last="X", active=(i != 2))
        everyone = run(lambda s: s.list_users(limit=50, sort="display_name"))
        check.equal(len(everyone.items), 5)
        inactive = run(lambda s: s.list_users(is_active=False))
        check.equal([v.email for v in inactive.items], ["u2@example.com"])
        collected, after = [], None
        for _ in range(10):
            page = run(lambda s, after=after: s.list_users(limit=2, sort="display_name", after=after))
            collected.extend(v.id for v in page.items)
            after = page.next_after
            if after is None:
                break
        check.equal(len(collected), 5)
        check.equal(len(set(collected)), 5)
        desc = run(lambda s: s.list_users(sort="-display_name"))
        check.equal([v.display_name for v in desc.items], sorted((v.display_name for v in desc.items), reverse=True))

    def test_list_invalid_sort(self, run):
        """許可していない並び替えキーは UserValidationError(field=sort)。"""
        with pytest.raises(UserValidationError) as caught:
            run(lambda s: s.list_users(sort="email"))
        check.equal((caught.value.field, caught.value.reason), ("sort", "unsupported"))

    def test_get_user_roles_returns_tenant_roles_only(self, run, idp, make_user, env):
        """ロールは IdP の実効ロールのうち tenant_admin / member だけ(default-roles-* 等は含めない)。既定ロールの member は管理者にも含まれる。"""
        admin = make_user(email="adm@example.com", roles=("tenant_admin",))
        plain = make_user(email="mem@example.com", roles=("member",))
        check.equal(run(lambda s: s.get_user_roles(admin.id)), ["tenant_admin", "member"])
        check.equal(run(lambda s: s.get_user_roles(plain.id)), ["member"])

    def test_get_user_roles_idp_failure(self, run, idp, make_user):
        """IdP への問い合わせが失敗したら IdentityProviderOperationError(operation=get_user_roles)。"""
        user = make_user()
        idp.fail("GET", r"/role-mappings/realm/composite$", 500)
        with pytest.raises(IdentityProviderOperationError) as caught:
            run(lambda s: s.get_user_roles(user.id))
        check.equal(caught.value.operation, "get_user_roles")


class TestUpdateUser:
    """更新(楽観ロック・IdP との整合・監査ログ)。"""

    def test_update_names(self, run, ap_db, idp, make_user, env):
        """姓・名を更新すると、IdP の姓・名と AP の表示名("名 姓")が変わり、version +1、updated_by=操作者、監査ログ user.update に差分が残る。"""
        user = make_user()
        view = run(lambda s: s.update_user(user.id, expected_version=1, first_name=" Robert ", last_name="Builder-Smith"))
        check.equal((view.display_name, view.version), ("Robert Builder-Smith", 2))
        check.equal((idp.users(env.realm)[user.idp_subject]["firstName"], idp.users(env.realm)[user.idp_subject]["lastName"]), ("Robert", "Builder-Smith"))
        row = ap_db.user(env.ctx, user.id)
        check.equal((row["display_name"], row["version"], row["updated_by"]), ("Robert Builder-Smith", 2, env.actor.id))
        audit = ap_db.audits(env.ctx, "user.update")
        check.equal(len(audit), 1)
        check.equal(audit[0]["payload"]["changes"], {"display_name": {"before": "Bob Builder", "after": "Robert Builder-Smith"}})
        check.equal(audit[0]["payload"]["version"], {"before": 1, "after": 2})
        check.equal((audit[0]["actor_id"], audit[0]["target_id"]), (env.actor.id, str(user.id)))

    def test_username_and_email_are_preserved_in_idp(self, run, idp, make_user, env):
        """姓・名の更新で IdP のユーザー名・メールを消さない(必須項目を送り直す)。"""
        user = make_user()
        run(lambda s: s.update_user(user.id, expected_version=1, first_name="X", last_name="Y"))
        rep = idp.users(env.realm)[user.idp_subject]
        check.equal((rep["username"], rep["email"]), ("bob@example.com", "bob@example.com"))

    def test_stale_version_is_rejected_without_changes(self, run, ap_db, idp, make_user, env):
        """version が違えば UserVersionConflictError(期待値・現在値付き)。IdP にも AP にも書き込まない。"""
        user = make_user()
        with pytest.raises(UserVersionConflictError) as caught:
            run(lambda s: s.update_user(user.id, expected_version=7, first_name="X", last_name="Y"))
        check.equal((caught.value.expected_version, caught.value.actual_version, caught.value.resource_id), (7, 1, user.id))
        check.equal(idp.writes, [])
        check.equal(ap_db.user(env.ctx, user.id)["version"], 1)
        check.equal(ap_db.audits(env.ctx, "user.update"), [])

    def test_stale_version_is_rejected_even_for_noop_request(self, run, make_user):
        """何も変更しない更新でも、version が違えば UserVersionConflictError(先に版を確認する)。"""
        user = make_user()
        with pytest.raises(UserVersionConflictError):
            run(lambda s: s.update_user(user.id, expected_version=2))

    def test_noop_does_nothing(self, run, ap_db, idp, make_user, env):
        """送った値が現在と同じ(または何も送らない)なら IdP も AP も変えず、version も監査ログも増やさない。"""
        user = make_user()
        same = run(lambda s: s.update_user(user.id, expected_version=1, first_name="Bob", last_name="Builder", is_active=True))
        nothing = run(lambda s: s.update_user(user.id, expected_version=1))
        check.equal((same.version, nothing.version), (1, 1))
        check.equal(idp.writes, [])
        check.equal(ap_db.audits(env.ctx, "user.update"), [])
        check.equal(ap_db.user(env.ctx, user.id)["version"], 1)

    def test_second_update_requires_new_version(self, run, make_user):
        """更新後の version でなければ次の更新は 412 相当。連続して更新できる。"""
        user = make_user()
        run(lambda s: s.update_user(user.id, expected_version=1, first_name="A", last_name="B"))
        with pytest.raises(UserVersionConflictError):
            run(lambda s: s.update_user(user.id, expected_version=1, first_name="C", last_name="D"))
        view = run(lambda s: s.update_user(user.id, expected_version=2, first_name="C", last_name="D"))
        check.equal((view.display_name, view.version), ("C D", 3))

    @pytest.mark.parametrize(
        ("kwargs", "field", "reason"),
        [
            ({"first_name": "Only"}, "last_name", "required"),
            ({"last_name": "Only"}, "first_name", "required"),
            ({"first_name": " ", "last_name": "X"}, "first_name", "required"),
            ({"first_name": "X", "last_name": "y" * 101}, "last_name", "too_long"),
            ({"roles": []}, "roles", "required"),
            ({"roles": "member"}, "roles", "type"),
            ({"is_active": "no"}, "is_active", "type"),
            ({"is_active": 0}, "is_active", "type"),
        ],
    )
    def test_invalid_update_input(self, run, idp, ap_db, make_user, env, kwargs, field, reason):
        """姓・名は両方必須、ロールは 1 つ以上、is_active は真偽値。違反は UserValidationError で、何も書き込まない。"""
        user = make_user()
        with pytest.raises(UserValidationError) as caught:
            run(lambda s: s.update_user(user.id, expected_version=1, **kwargs))
        check.equal((caught.value.field, caught.value.reason), (field, reason))
        check.equal(idp.writes, [])
        check.equal(ap_db.user(env.ctx, user.id)["version"], 1)

    def test_roles_replace_direct_roles(self, run, ap_db, idp, make_user, env):
        """ロールを置き換える(member → tenant_admin)。IdP の直接付与が変わり、監査ログにロールの前後を残す。ロールだけの変更では表示名は変わらない。"""
        user = make_user()
        view = run(lambda s: s.update_user(user.id, expected_version=1, roles=["tenant_admin"]))
        check.equal(idp.direct_roles(env.realm, user.idp_subject), ["tenant_admin"])
        check.equal((view.version, view.display_name), (2, "Bob Builder"))
        check.equal(ap_db.audits(env.ctx, "user.update")[0]["payload"]["changes"], {"roles": {"before": ["member"], "after": ["tenant_admin"]}})
        check.equal(idp.logouts, [])

    def test_removing_tenant_admin_from_another_user_revokes_idp_sessions(self, run, idp, make_user, env):
        """他のユーザーの tenant_admin を外したら、権限の残るセッションを残さないよう IdP のセッションを失効させる。"""
        user = make_user(email="adm2@example.com", roles=("tenant_admin",))
        run(lambda s: s.update_user(user.id, expected_version=1, roles=["member"]))
        check.equal(idp.direct_roles(env.realm, user.idp_subject), ["member"])
        check.equal(idp.logouts, [(env.realm, user.idp_subject)])

    def test_roles_unchanged_is_noop(self, run, idp, make_user):
        """今と同じロールを指定しても変更なし(version も上げない)。"""
        user = make_user()
        view = run(lambda s: s.update_user(user.id, expected_version=1, roles=["member"]))
        check.equal(view.version, 1)
        check.equal(idp.writes, [])

    @pytest.mark.parametrize("roles", [["saas_admin"], ["tenant_admin", "view-users"], ["realm-management"]])
    def test_non_tenant_roles_are_rejected_on_update(self, run, idp, ap_db, make_user, env, roles):
        """更新でも tenant_admin / member 以外のロールは InvalidUserRoleError。IdP のロールは変わらない。"""
        user = make_user()
        with pytest.raises(InvalidUserRoleError):
            run(lambda s: s.update_user(user.id, expected_version=1, roles=roles))
        check.equal(idp.direct_roles(env.realm, user.idp_subject), ["member"])
        check.equal(ap_db.user(env.ctx, user.id)["version"], 1)

    def test_deactivate_disables_idp_user_revokes_sessions_and_audits(self, run, ap_db, idp, make_user, env):
        """無効化すると、IdP のユーザーを無効にしてセッションを失効させ、AP の is_active=false・version +1・監査ログ user.deactivate を残す。"""
        user = make_user()
        view = run(lambda s: s.update_user(user.id, expected_version=1, is_active=False))
        check.equal((view.is_active, view.version), (False, 2))
        check.is_false(idp.users(env.realm)[user.idp_subject]["enabled"])
        check.equal(idp.logouts, [(env.realm, user.idp_subject)])
        row = ap_db.user(env.ctx, user.id)
        check.equal((row["is_active"], row["version"], row["updated_by"]), (False, 2, env.actor.id))
        audit = ap_db.audits(env.ctx, "user.deactivate")
        check.equal(len(audit), 1)
        check.equal(audit[0]["payload"]["changes"], {"is_active": {"before": True, "after": False}})

    def test_reactivate_enables_idp_user_without_logout(self, run, ap_db, idp, make_user, env):
        """再有効化すると IdP のユーザーを有効に戻し、AP の is_active=true、監査ログ user.activate。セッション失効は行わない。"""
        user = make_user(active=False)
        view = run(lambda s: s.update_user(user.id, expected_version=1, is_active=True))
        check.equal((view.is_active, view.version), (True, 2))
        check.is_true(idp.users(env.realm)[user.idp_subject]["enabled"])
        check.equal(idp.logouts, [])
        check.equal(len(ap_db.audits(env.ctx, "user.activate")), 1)

    def test_combined_update_uses_deactivate_action(self, run, ap_db, make_user, env):
        """姓名・ロール・無効化を一度に変えると、version は +1 の 1 回で、監査ログは 1 件(is_active を含めば user.deactivate)に全差分を残す。"""
        user = make_user()
        view = run(lambda s: s.update_user(user.id, expected_version=1, first_name="N", last_name="M", roles=["tenant_admin"], is_active=False))
        check.equal(view.version, 2)
        audit = ap_db.audits(env.ctx)
        audit = [a for a in audit if a["action"].startswith("user.") and a["action"] != "user.create"]
        check.equal([a["action"] for a in audit], ["user.deactivate"])
        check.equal(set(audit[0]["payload"]["changes"]), {"display_name", "roles", "is_active"})

    def test_cannot_deactivate_self(self, run, ap_db, idp, env):
        """自分自身の無効化は UserSelfModificationError(deactivate)。IdP も AP も変えない。"""
        with pytest.raises(UserSelfModificationError) as caught:
            run(lambda s: s.update_user(env.actor.id, expected_version=1, is_active=False))
        check.equal((caught.value.operation, caught.value.code), ("deactivate", "user_self_modification_forbidden"))
        check.equal(idp.writes, [])
        check.is_true(ap_db.user(env.ctx, env.actor.id)["is_active"])

    @pytest.mark.parametrize("roles", [["member"], ["member", "member"]])
    def test_cannot_remove_own_tenant_admin(self, run, idp, ap_db, env, roles):
        """自分の tenant_admin を外す更新は UserSelfModificationError(remove_tenant_admin)。IdP のロールは変わらない。"""
        with pytest.raises(UserSelfModificationError) as caught:
            run(lambda s: s.update_user(env.actor.id, expected_version=1, roles=roles))
        check.equal(caught.value.operation, "remove_tenant_admin")
        check.equal(idp.direct_roles(env.realm, env.actor.idp_subject), ["tenant_admin"])
        check.equal(ap_db.user(env.ctx, env.actor.id)["version"], 1)

    def test_self_update_that_keeps_admin_is_allowed(self, run, idp, ap_db, env):
        """自分自身でも、名前の変更、tenant_admin を保つロール指定、有効のままにする指定は許可される。"""
        view = run(lambda s: s.update_user(env.actor.id, expected_version=1, first_name="Adaline", last_name="Admin", roles=["tenant_admin", "member"], is_active=True))
        check.equal((view.display_name, view.version, view.is_active), ("Adaline Admin", 2, True))
        check.equal(idp.direct_roles(env.realm, env.actor.idp_subject), ["member", "tenant_admin"])

    def test_other_admin_can_demote_and_deactivate_an_admin(self, run, make_user, env):
        """別の管理者は、他の管理者を無効化できる(自分自身の禁止だけが対象)。"""
        other = make_user(email="adm3@example.com", roles=("tenant_admin",))
        view = run(lambda s: s.update_user(other.id, expected_version=1, is_active=False))
        check.is_false(view.is_active)

    def test_idp_failure_leaves_ap_unchanged(self, run, idp, ap_db, make_user, env):
        """IdP の更新が失敗(500)したら IdentityProviderOperationError。AP の行(表示名・version)は変えず、監査ログも残さない。"""
        user = make_user()
        idp.fail("PUT", r"/users/[^/]+$", 500)
        with pytest.raises(IdentityProviderOperationError) as caught:
            run(lambda s: s.update_user(user.id, expected_version=1, first_name="X", last_name="Y"))
        check.equal(caught.value.error_summary, "operation=update_user_names; error=KeycloakAdminError; http_status=500")
        row = ap_db.user(env.ctx, user.id)
        check.equal((row["display_name"], row["version"]), ("Bob Builder", 1))
        check.equal(ap_db.audits(env.ctx, "user.update"), [])

    def test_partial_idp_failure_converges_on_retry(self, run, idp, ap_db, make_user, env):
        """姓名の更新の後に無効化の IdP 呼び出しが失敗しても AP は変えない。障害が直った後の同じ要求の再実行で、IdP・AP が同じ最終状態に収束する。"""
        user = make_user()
        idp.fail("POST", r"/logout$", 500)
        with pytest.raises(IdentityProviderOperationError) as caught:
            run(lambda s: s.update_user(user.id, expected_version=1, first_name="N", last_name="M", is_active=False))
        check.equal(caught.value.operation, "logout_user")
        check.equal(ap_db.user(env.ctx, user.id)["version"], 1)
        check.is_true(ap_db.user(env.ctx, user.id)["is_active"])
        idp.rules.clear()
        view = run(lambda s: s.update_user(user.id, expected_version=1, first_name="N", last_name="M", is_active=False))
        row = ap_db.user(env.ctx, user.id)
        check.equal((view.version, row["is_active"], row["display_name"]), (2, False, "N M"))
        check.is_false(idp.users(env.realm)[user.idp_subject]["enabled"])
        check.equal(idp.users(env.realm)[user.idp_subject]["firstName"], "N")

    def test_unknown_user_is_not_found(self, run, idp):
        """存在しない ID は UserNotFoundError(IdP を呼ばない)。"""
        with pytest.raises(UserNotFoundError):
            run(lambda s: s.update_user(uuid.uuid4(), expected_version=1, first_name="X", last_name="Y"))
        check.equal(idp.factory_realms, [])

    def test_concurrent_updates_with_same_version_only_one_wins(self, ap_db, idp, env, make_user):
        """同じ version を持つ 2 つの更新が同時に来ても、行ロックで直列化され、片方だけが成功し、もう片方は UserVersionConflictError(更新の消失なし)。"""
        user = make_user()
        barrier = threading.Barrier(2)

        def attempt(first_name):
            barrier.wait(timeout=10)
            with ap_db.session(env.ctx) as session:
                try:
                    UserService(session, idp.factory, actor_subject=env.actor.idp_subject).update_user(user.id, expected_version=1, first_name=first_name, last_name="Z")
                except UserVersionConflictError:
                    return "conflict"
                return "ok"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(attempt, ["One", "Two"]))
        check.equal(outcomes, ["conflict", "ok"])
        row = ap_db.user(env.ctx, user.id)
        check.equal(row["version"], 2)
        check.is_in(row["display_name"], ("One Z", "Two Z"))


class TestCrossTenant:
    """実際のサービスと DB で、他テナントのユーザーを読めない・書けない(tenant-isolation §5.1)。"""

    def test_cannot_update_other_tenant_user(self, run, ap_db, idp, make_user, env):
        """テナント A の管理者がテナント B のユーザー ID を更新しようとすると UserNotFoundError。B のユーザー(DB・IdP)は変わらず、B のレルムの IdP も呼ばない。"""
        other = ap_db.tenant()
        foreign = make_user(ctx=other, email="foreign@example.com")
        snapshot = idp.snapshot()
        for kwargs in ({"first_name": "Hacked", "last_name": "Name"}, {"is_active": False}, {"roles": ["tenant_admin"]}):
            with pytest.raises(UserNotFoundError):
                run(lambda s, kwargs=kwargs: s.update_user(foreign.id, expected_version=1, **kwargs))
        row = ap_db.user(other, foreign.id)
        check.equal((row["display_name"], row["is_active"], row["version"]), ("Bob Builder", True, 1))
        check.equal(idp.snapshot(), snapshot)
        check.equal(idp.writes, [])
        check.equal(ap_db.audits(other), [])

    def test_created_user_belongs_to_context_tenant_only(self, run, ap_db, idp, env):
        """作成したユーザーは、コンテキストのテナントのレルム・テナント ID にだけ作られ、他のレルムには作られない。"""
        other = ap_db.tenant()
        result = run(lambda s: s.create_user(**create_args()))
        check.equal(ap_db.user(env.ctx, result.user.id)["tenant_id"], env.ctx.tenant_id)
        check.equal(ap_db.users(other), [])
        check.equal(idp.factory_realms, [env.realm])
        check.equal(idp.users(tenant_realm_name(other.tenant_code)), {})

    def test_context_without_tenant_rows_sees_nothing(self, run, ap_db, make_user):
        """ユーザーのいないテナントのコンテキストでは、他テナントのユーザーは一覧にも取得にも現れない。"""
        make_user(email="visible@example.com")
        empty = ap_db.tenant()
        check.equal(run(lambda s: s.list_users(), ctx=empty).items, [])
