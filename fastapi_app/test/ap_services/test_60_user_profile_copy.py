# -*- coding: utf-8 -*-
"""t_user の写し(first_name / last_name / roles)のテスト: ログイン時の同期・apply_idp_profile・ログイン同期の入力の組み立て・roles の CHECK 制約。

仕様は docs/architecture/02 §4.7・§5.1、05-decisions #33。姓・名・ロールは Keycloak が正で、AP の DB には一覧表示用の写しを持つ。

- DB は開発 DB の ``app_db``(使い捨てのテナント。alpha / beta には触れない)。終了時に監査ログを含めて削除する(``ap_db``)。
- ``UserService`` による写しの更新は ``test_65_user_service_copy.py``。
"""
import uuid

import pytest
import pytest_check as check
from sqlalchemy.exc import IntegrityError

from main_app.models import TUser
from main_app.repositories import users as user_repo
from main_app.route.auth.login_sync import login_name_part, login_roles
from main_app.services.common import UNSET
from main_app.services.errors import UserDeactivatedError
from main_app.services.user_sync import apply_idp_profile, sync_user_on_login
from modules.tenancy import providers
from modules.tenancy.context import require_tenant_context

SUB = "sub-1"


def login(ap_db, ctx, sub=SUB, *, email="alice@example.com", name="Alice Liddell", **copies):
    """ログイン同期を 1 回行う(コミットされる)。``copies`` は first_name / last_name / roles。"""
    with ap_db.session(ctx) as session:
        return sync_user_on_login(session, tenant_id=ctx.tenant_id, idp_subject=sub, email=email, display_name=name, **copies)


def put_user(ap_db, ctx, *, sub=SUB, email="alice@example.com", name="Alice Liddell", first=None, last=None, roles=(), version=1, active=True) -> uuid.UUID:
    """写しの値を指定してユーザー行を直接作る(列の追加前からある行・ログイン済みの行の再現)。"""
    with ap_db.session(ctx) as session:
        user = TUser(tenant_id=ctx.tenant_id, idp_subject=sub, email=email, display_name=name, first_name=first, last_name=last, roles=list(roles), version=version, is_active=active)
        session.add(user)
        session.commit()
        return user.id


def row_of(ap_db, ctx, user_id) -> dict:
    return ap_db.user(ctx, user_id)


def copies_of(row) -> tuple:
    return (row["first_name"], row["last_name"], row["roles"])


class TestFirstLogin:
    """初回ログイン(ユーザー行の作成)での写し。"""

    def test_copies_are_stored_and_audited(self, ap_db):
        """姓・名・ロールを渡すと行に保存し、version は 1。監査ログ user.create の payload にも入る。"""
        ctx = ap_db.tenant()
        result = login(ap_db, ctx, first_name="Alice", last_name="Liddell", roles=["member"])
        row = row_of(ap_db, ctx, result.user_id)
        check.equal((copies_of(row), row["version"]), (("Alice", "Liddell", ["member"]), 1))
        check.is_true(result.created and not result.profile_updated)
        payload = ap_db.audits(ctx, "user.create")[0]["payload"]
        check.equal((payload["first_name"], payload["last_name"], payload["roles"]), ("Alice", "Liddell", ["member"]))

    def test_omitted_copies_are_left_unsynced(self, ap_db):
        """渡さなければ(None)姓・名は NULL、ロールは空配列のまま(未同期)。payload にも項目を入れない。"""
        ctx = ap_db.tenant()
        result = login(ap_db, ctx)
        check.equal(copies_of(row_of(ap_db, ctx, result.user_id)), (None, None, []))
        payload = ap_db.audits(ctx, "user.create")[0]["payload"]
        check.is_true({"first_name", "last_name", "roles"}.isdisjoint(payload))

    def test_empty_strings_become_null(self, ap_db):
        """空文字・空白だけの姓・名は「IdP で未設定」として NULL にする(payload は null)。空のロールは空配列。"""
        ctx = ap_db.tenant()
        result = login(ap_db, ctx, first_name="", last_name="   ", roles=[])
        check.equal(copies_of(row_of(ap_db, ctx, result.user_id)), (None, None, []))
        payload = ap_db.audits(ctx, "user.create")[0]["payload"]
        check.equal((payload["first_name"], payload["last_name"], payload["roles"]), (None, None, []))

    def test_names_are_trimmed(self, ap_db):
        """姓・名の前後の空白は除く。"""
        ctx = ap_db.tenant()
        result = login(ap_db, ctx, first_name="  Alice ", last_name=" Liddell  ")
        check.equal(copies_of(row_of(ap_db, ctx, result.user_id))[:2], ("Alice", "Liddell"))


class TestRolesNormalization:
    """roles は tenant_admin / member だけを、この順で保存する。"""

    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            (["member", "tenant_admin"], ["tenant_admin", "member"]),
            (["tenant_admin", "member"], ["tenant_admin", "member"]),
            (["member", "saas_admin", "default-roles-x", "offline_access", "uma_authorization"], ["member"]),
            (["saas_admin", "default-roles-x"], []),
            (["member", "member", "tenant_admin", "tenant_admin"], ["tenant_admin", "member"]),
            (("tenant_admin",), ["tenant_admin"]),
            ({"member"}, ["member"]),
            (["MEMBER", "Tenant_Admin"], []),
            ([], []),
        ],
        ids=["order", "already-ordered", "unrelated-ignored", "only-unrelated", "duplicates", "tuple", "set", "case-sensitive", "empty"],
    )
    def test_normalized_on_first_login(self, ap_db, given, expected):
        """順序の正規化・無関係なロール(realm のロール等)の無視・重複の除去・大文字小文字の区別(別物として無視)。"""
        ctx = ap_db.tenant()
        result = login(ap_db, ctx, roles=given)
        check.equal(row_of(ap_db, ctx, result.user_id)["roles"], expected)

    def test_string_roles_are_rejected(self, ap_db):
        """roles に文字列(コレクションでない)を渡すと ValueError で、何も作らない。"""
        ctx = ap_db.tenant()
        with pytest.raises(ValueError):
            login(ap_db, ctx, roles="member")
        check.equal(ap_db.users(ctx), [])

    def test_unrelated_role_difference_is_not_a_change(self, ap_db):
        """既存の行と、無関係なロールだけが違う場合は変更なし(version を上げず、監査ログも残さない)。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell", roles=["member"])
        result = login(ap_db, ctx, first_name="Alice", last_name="Liddell", roles=["member", "offline_access", "saas_admin"])
        check.equal((result.profile_updated, row_of(ap_db, ctx, user_id)["version"], ap_db.audits(ctx, "user.sync")), (False, 1, []))


class TestExistingUserCopies:
    """既存の行の写しの更新。"""

    def test_none_does_not_update(self, ap_db):
        """None(引数を渡さない)は写しを更新しない。既に入っている値が残り、version も変わらない。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell", roles=["tenant_admin", "member"])
        result = login(ap_db, ctx)
        row = row_of(ap_db, ctx, user_id)
        check.equal((copies_of(row), row["version"], result.profile_updated), (("Alice", "Liddell", ["tenant_admin", "member"]), 1, False))
        check.equal(ap_db.audits(ctx, "user.sync"), [])

    def test_empty_string_clears_the_name(self, ap_db):
        """空文字は「IdP で未設定になった」として写しを NULL にする。値が消えるので変更として version を +1 し、user.sync に残す。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell")
        result = login(ap_db, ctx, first_name="", last_name="Liddell")
        row = row_of(ap_db, ctx, user_id)
        check.equal((row["first_name"], row["last_name"], row["version"], result.profile_updated), (None, "Liddell", 2, True))
        sync = ap_db.audits(ctx, "user.sync")
        check.equal(len(sync), 1)
        check.equal(sync[0]["payload"]["changes"], {"first_name": {"before": "Alice", "after": None}})
        check.equal(sync[0]["payload"]["source"], "login")

    def test_empty_roles_clear_the_copy(self, ap_db):
        """空のコレクションは「テナントのロールなし」として写しを空にする(変更として version を +1)。None は更新しない。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell", roles=["member"])
        login(ap_db, ctx, first_name="Alice", last_name="Liddell", roles=None)
        check.equal((row_of(ap_db, ctx, user_id)["roles"], row_of(ap_db, ctx, user_id)["version"]), (["member"], 1))
        login(ap_db, ctx, first_name="Alice", last_name="Liddell", roles=[])
        row = row_of(ap_db, ctx, user_id)
        check.equal((row["roles"], row["version"]), ([], 2))
        check.equal(ap_db.audits(ctx, "user.sync")[0]["payload"]["changes"], {"roles": {"before": ["member"], "after": []}})

    def test_change_bumps_version_and_audits(self, ap_db):
        """姓・名・ロールが変わると version を +1 し、updated_by を NULL(システム処理)にして user.sync(変更前後つき)を 1 件残す。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell", roles=["member"])
        result = login(ap_db, ctx, name="Alicia Liddell", first_name="Alicia", last_name="Liddell", roles=["tenant_admin", "member"])
        row = row_of(ap_db, ctx, user_id)
        check.equal((copies_of(row), row["version"], row["updated_by"], row["display_name"]), (("Alicia", "Liddell", ["tenant_admin", "member"]), 2, None, "Alicia Liddell"))
        check.is_true(result.profile_updated)
        sync = ap_db.audits(ctx, "user.sync")
        check.equal(len(sync), 1)
        check.equal(sync[0]["actor_id"], None)
        check.equal(sync[0]["payload"]["changes"], {
            "display_name": {"before": "Alice Liddell", "after": "Alicia Liddell"},
            "first_name": {"before": "Alice", "after": "Alicia"},
            "roles": {"before": ["member"], "after": ["tenant_admin", "member"]},
        })
        check.equal(sync[0]["payload"]["version"], {"before": 1, "after": 2})

    def test_same_values_do_not_change_anything(self, ap_db):
        """同じ値で何度ログインしても、version は上がらず user.sync も残らない(last_login_at だけが進む)。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell", roles=["member"])
        for _ in range(3):
            result = login(ap_db, ctx, first_name="Alice", last_name="Liddell", roles=["member"])
            check.is_false(result.profile_updated)
        row = row_of(ap_db, ctx, user_id)
        check.equal((row["version"], ap_db.audits(ctx, "user.sync")), (1, []))
        check.is_not_none(row["last_login_at"])

    def test_deactivated_user_is_not_updated(self, ap_db):
        """無効化されたユーザーは UserDeactivatedError で、写しも書かない。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell", roles=["member"], active=False)
        with pytest.raises(UserDeactivatedError):
            login(ap_db, ctx, first_name="Zed", last_name="Zed", roles=["tenant_admin"])
        row = row_of(ap_db, ctx, user_id)
        check.equal((copies_of(row), row["version"]), (("Alice", "Liddell", ["member"]), 1))


class TestInitialEmbedding:
    """写しの初回の埋め込み(列の追加前からある行・未同期の行)では version を上げない。"""

    def test_embedding_does_not_bump_version(self, ap_db):
        """姓・名が NULL、ロールが空の行に初めて値を入れるだけなら、値は書くが version は上げず user.sync も残さない(profile_updated は False)。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx)
        result = login(ap_db, ctx, first_name="Alice", last_name="Liddell", roles=["tenant_admin", "member"])
        row = row_of(ap_db, ctx, user_id)
        check.equal((copies_of(row), row["version"], row["updated_by"]), (("Alice", "Liddell", ["tenant_admin", "member"]), 1, None))
        check.is_false(result.profile_updated)
        check.equal(ap_db.audits(ctx, "user.sync"), [])

    def test_embedding_with_a_visible_change_bumps_only_the_visible_part(self, ap_db):
        """埋め込みと同時に表示名などの変更がある場合は version を +1 するが、監査ログの差分には埋め込みの項目(NULL からの変化)を含めない。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, name="alice@example.com")
        result = login(ap_db, ctx, name="Alice Liddell", first_name="Alice", last_name="Liddell", roles=["member"])
        row = row_of(ap_db, ctx, user_id)
        check.equal((copies_of(row), row["version"], result.profile_updated), (("Alice", "Liddell", ["member"]), 2, True))
        check.equal(list(ap_db.audits(ctx, "user.sync")[0]["payload"]["changes"]), ["display_name"])

    def test_known_name_change_with_unknown_other_part(self, ap_db):
        """名だけ既知の行で名が変わり、姓の写しは NULL から埋まる場合: 名の変更だけが差分に残り、version は +1。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice")
        login(ap_db, ctx, first_name="Alicia", last_name="Liddell")
        row = row_of(ap_db, ctx, user_id)
        check.equal((copies_of(row)[:2], row["version"]), (("Alicia", "Liddell"), 2))
        check.equal(ap_db.audits(ctx, "user.sync")[0]["payload"]["changes"], {"first_name": {"before": "Alice", "after": "Alicia"}})

    def test_embedding_is_idempotent(self, ap_db):
        """埋め込み後に同じ値で再ログインしても version は 1 のまま。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx)
        for _ in range(2):
            login(ap_db, ctx, first_name="Alice", last_name="Liddell", roles=["member"])
        check.equal((row_of(ap_db, ctx, user_id)["version"], ap_db.audits(ctx, "user.sync")), (1, []))


class TestApplyIdpProfile:
    """apply_idp_profile: ログイン(source=login)と詳細の取得(source=idp)が共有する、コミットしない更新。"""

    def apply(self, ap_db, ctx, user_id, **kwargs):
        """ユーザー行をロックして apply_idp_profile を呼び、(結果, 呼び出し中の行の値)を返す。コミットはしない(ロールバックして閉じる)。"""
        with ap_db.session(ctx) as session:
            user = user_repo.get_user(session, user_id, for_update=True)
            kwargs.setdefault("source", "idp")
            kwargs.setdefault("email", None)
            outcome = apply_idp_profile(session, require_tenant_context(), user, **kwargs)
            snapshot = (user.first_name, user.last_name, list(user.roles), user.version, user.email, user.display_name)
            session.rollback()
        return outcome, snapshot

    def test_all_unset_is_a_noop(self, ap_db):
        """全て UNSET(email は None)なら何も変えず (False, False)。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell", roles=["member"])
        outcome, snapshot = self.apply(ap_db, ctx, user_id)
        check.equal((outcome, snapshot), ((False, False), ("Alice", "Liddell", ["member"], 1, "alice@example.com", "Alice Liddell")))

    def test_does_not_commit(self, ap_db):
        """呼び出し側がコミットしなければ、行も監査ログも保存されない(コミットは呼び出し側の責務)。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell")
        outcome, snapshot = self.apply(ap_db, ctx, user_id, first_name="Zed")
        check.equal((outcome, snapshot[3]), ((True, False), 2))
        check.equal((row_of(ap_db, ctx, user_id)["first_name"], row_of(ap_db, ctx, user_id)["version"], ap_db.audits(ctx, "user.sync")), ("Alice", 1, []))

    def test_source_is_recorded_in_the_audit_log(self, ap_db):
        """監査ログ user.sync の source は呼び出し側の指定(idp / login)。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell")
        with ap_db.session(ctx) as session:
            user = user_repo.get_user(session, user_id, for_update=True)
            apply_idp_profile(session, require_tenant_context(), user, source="idp", email=None, first_name="Zed")
            session.commit()
        check.equal(ap_db.audits(ctx, "user.sync")[0]["payload"]["source"], "idp")

    def test_none_email_keeps_stored_email(self, ap_db):
        """email が None でも保存済みのメールアドレスは消さない(消すと同じアドレスを別のユーザーが取れてしまうため)。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx)
        _, snapshot = self.apply(ap_db, ctx, user_id, email=None, display_name="Alice L")
        check.equal((snapshot[4], snapshot[5], snapshot[3]), ("alice@example.com", "Alice L", 2))

    def test_email_conflict_is_reported_without_blocking_other_fields(self, ap_db):
        """メールアドレスが別のユーザー行で使われていれば同期せず email_conflict=True。他の項目の変更は行い、その分だけ version を上げる。"""
        ctx = ap_db.tenant()
        put_user(ap_db, ctx, sub="other", email="taken@example.com", name="Other")
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell")
        outcome, snapshot = self.apply(ap_db, ctx, user_id, email="taken@example.com", first_name="Alicia")
        check.equal((outcome, snapshot[0], snapshot[4], snapshot[3]), ((True, True), "Alicia", "alice@example.com", 2))

    def test_email_conflict_alone_does_not_bump_version(self, ap_db):
        """メールの重複だけなら変更なし(version を上げない)で、email_conflict だけが True。"""
        ctx = ap_db.tenant()
        put_user(ap_db, ctx, sub="other", email="taken@example.com", name="Other")
        user_id = put_user(ap_db, ctx)
        outcome, snapshot = self.apply(ap_db, ctx, user_id, email="taken@example.com")
        check.equal((outcome, snapshot[3]), ((False, True), 1))

    def test_explicit_none_names_clear_known_copies(self, ap_db):
        """None の姓・名は「IdP で未設定」として写しを NULL にする(UNSET とは別)。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, first="Alice", last="Liddell")
        outcome, snapshot = self.apply(ap_db, ctx, user_id, first_name=None, last_name=None)
        check.equal((outcome, snapshot[:2], snapshot[3]), ((True, False), (None, None), 2))
        _, unchanged = self.apply(ap_db, ctx, user_id, first_name=UNSET, last_name=UNSET)
        check.equal(unchanged[:2], ("Alice", "Liddell"))


class TestLoginSyncInputs:
    """ログイン同期に渡す姓・名・ロールの取り出し(セッションのユーザー情報から)。"""

    @pytest.mark.parametrize(
        ("user", "expected"),
        [
            ({}, None),
            ({"sub": "x"}, None),
            ({"given_name": "Alice"}, "Alice"),
            ({"given_name": ""}, ""),
            ({"given_name": None}, ""),
            ({"given_name": 123}, ""),
            ({"given_name": ["Alice"]}, ""),
        ],
        ids=["empty", "no-key", "value", "empty-string", "null", "int", "list"],
    )
    def test_login_name_part(self, user, expected):
        """キーが無ければ None(写しを更新しない)。キーがあれば、値が無い・文字列でない場合は空文字(写しを NULL にする)。"""
        check.equal(login_name_part(user, "given_name"), expected)

    def test_login_name_part_reads_the_requested_key_only(self):
        """指定したキー(given_name / family_name)だけを読む。"""
        user = {"given_name": "Alice", "family_name": "Liddell"}
        check.equal((login_name_part(user, "given_name"), login_name_part(user, "family_name")), ("Alice", "Liddell"))
        check.is_none(login_name_part({"given_name": "Alice"}, "family_name"))

    @pytest.mark.parametrize(
        ("user", "expected"),
        [
            ({}, None),
            ({"roles": None}, None),
            ({"roles": "member"}, None),
            ({"roles": ("member",)}, None),
            ({"roles": []}, []),
            ({"roles": ["member", "tenant_admin"]}, ["member", "tenant_admin"]),
            ({"roles": ["member", 3, None, "x"]}, ["member", "x"]),
        ],
        ids=["no-key", "null", "string", "tuple", "empty-list", "list", "non-string-items"],
    )
    def test_login_roles(self, user, expected):
        """リストでなければ None(写しを更新しない)。リストなら文字列の要素だけ(正規化は同期側)。空リストは空のまま。"""
        check.equal(login_roles(user), expected)

    def test_sync_app_user_on_login_passes_copies_through(self, ap_db):
        """実 DB で、セッションの given_name / family_name / roles が写しとして保存される(取り出しから保存まで通す)。"""
        from main_app.route.auth.login_sync import sync_app_user_on_login

        ctx = ap_db.tenant()
        sub = str(uuid.uuid4())
        data = {"plane": "app", "realm": "tenant-x", "tenant_code": ctx.tenant_code, "user": {
            "sub": sub, "email": "taro@example.com", "name": "Taro Yamada", "given_name": "Taro", "family_name": "Yamada", "roles": ["member", "saas_admin", "tenant_admin"]}}
        try:
            result = sync_app_user_on_login(data, tenant_id=ctx.tenant_id, tenant_code=ctx.tenant_code)
        finally:
            providers.dispose_providers()
        check.equal(copies_of(row_of(ap_db, ctx, result.user_id)), ("Taro", "Yamada", ["tenant_admin", "member"]))

    def test_sync_app_user_on_login_without_claims_keeps_copies(self, ap_db):
        """given_name / family_name / roles のキーが無いセッション(古いセッション)では、既存の写しを更新しない。"""
        from main_app.route.auth.login_sync import sync_app_user_on_login

        ctx = ap_db.tenant()
        sub = str(uuid.uuid4())
        user_id = put_user(ap_db, ctx, sub=sub, first="Taro", last="Yamada", roles=["member"], name="Taro Yamada", email="taro@example.com")
        data = {"plane": "app", "realm": "tenant-x", "tenant_code": ctx.tenant_code, "user": {"sub": sub, "email": "taro@example.com", "name": "Taro Yamada"}}
        try:
            sync_app_user_on_login(data, tenant_id=ctx.tenant_id, tenant_code=ctx.tenant_code)
        finally:
            providers.dispose_providers()
        row = row_of(ap_db, ctx, user_id)
        check.equal((copies_of(row), row["version"]), (("Taro", "Yamada", ["member"]), 1))

    def test_sync_app_user_on_login_clears_missing_claims(self, ap_db):
        """キーはあるが値が無い(IdP で姓・名が未設定になった)セッションでは、写しを NULL にする。roles が空リストなら空にする。"""
        from main_app.route.auth.login_sync import sync_app_user_on_login

        ctx = ap_db.tenant()
        sub = str(uuid.uuid4())
        user_id = put_user(ap_db, ctx, sub=sub, first="Taro", last="Yamada", roles=["member"], name="Taro Yamada", email="taro@example.com")
        data = {"plane": "app", "realm": "tenant-x", "tenant_code": ctx.tenant_code, "user": {"sub": sub, "email": "taro@example.com", "name": "Taro Yamada", "given_name": None, "family_name": "", "roles": []}}
        try:
            sync_app_user_on_login(data, tenant_id=ctx.tenant_id, tenant_code=ctx.tenant_code)
        finally:
            providers.dispose_providers()
        check.equal(copies_of(row_of(ap_db, ctx, user_id)), (None, None, []))


class TestRolesCheckConstraint:
    """t_user.roles の CHECK 制約(tenant_admin / member 以外を許可しない。NOT NULL)。"""

    @pytest.mark.parametrize("roles", [["saas_admin"], ["member", "admin"], ["MEMBER"], ["default-roles-x"], [""], ["tenant_admin", "realm-management"]])
    def test_other_roles_are_rejected_by_the_database(self, ap_db, roles):
        """tenant_admin / member 以外の要素を含む行は DB が拒否する(アプリの正規化をすり抜けても守る)。"""
        ctx = ap_db.tenant()
        with pytest.raises(IntegrityError) as caught:
            put_user(ap_db, ctx, roles=roles)
        check.is_in("t_user_roles_check", str(caught.value))
        check.equal(ap_db.users(ctx), [])

    @pytest.mark.parametrize("roles", [[], ["member"], ["tenant_admin"], ["tenant_admin", "member"], ["member", "tenant_admin"]])
    def test_allowed_roles_are_accepted(self, ap_db, roles):
        """許可するロールの組み合わせ(空・単独・両方。順序は問わない)は保存できる。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, roles=roles)
        check.equal(row_of(ap_db, ctx, user_id)["roles"], roles)

    def test_update_to_invalid_role_is_rejected(self, ap_db):
        """既存の行を許可外のロールに更新するのも拒否する(行は変わらない)。"""
        ctx = ap_db.tenant()
        user_id = put_user(ap_db, ctx, roles=["member"])
        with ap_db.session(ctx) as session:
            with pytest.raises(IntegrityError):
                session.connection().exec_driver_sql("UPDATE t_user SET roles = ARRAY['saas_admin'] WHERE id = %s", (user_id,))
            session.rollback()
        check.equal(row_of(ap_db, ctx, user_id)["roles"], ["member"])

    def test_roles_cannot_be_null_and_default_is_empty(self, ap_db):
        """roles は NOT NULL(NULL は拒否)。列を指定せずに INSERT した行は空配列、姓・名は NULL(同期前の行)。"""
        ctx = ap_db.tenant()
        with ap_db.session(ctx) as session:
            connection = session.connection()
            connection.exec_driver_sql(
                "INSERT INTO t_user (id, tenant_id, idp_subject, display_name) VALUES (%s, %s, %s, %s)", (uuid.uuid4(), ctx.tenant_id, "raw-sub", "Raw User"))
            with pytest.raises(IntegrityError):
                connection.exec_driver_sql("UPDATE t_user SET roles = NULL")
            session.rollback()
        with ap_db.session(ctx) as session:
            connection = session.connection()
            connection.exec_driver_sql(
                "INSERT INTO t_user (id, tenant_id, idp_subject, display_name) VALUES (%s, %s, %s, %s)", (uuid.uuid4(), ctx.tenant_id, "raw-sub", "Raw User"))
            session.commit()
        row = ap_db.users(ctx)[0]
        check.equal(copies_of(row), (None, None, []))
