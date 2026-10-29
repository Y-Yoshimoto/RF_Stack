# -*- coding: utf-8 -*-
"""modules.auth.session(プレーン別の Cookie 署名・Redis キー空間・Cookie 属性・OIDC state)のテスト。Redis はインメモリの代替。"""
import pytest
import pytest_check as check
from itsdangerous import URLSafeSerializer
from starlette.responses import Response

from modules.auth import session
from modules.auth.plane import SESSION_COOKIE_NAMES, Plane

from .conftest import SESSION_SECRET


class TestSignedSessionId:
    """署名済みセッション ID(Cookie 値)。"""

    @pytest.mark.parametrize("plane", list(Plane))
    def test_roundtrip(self, plane):
        """署名したセッション ID は、同じプレーンで検証すると元の値に戻る。"""
        signed = session.sign_session_id(plane, "sid-123")
        check.not_equal(signed, "sid-123")
        check.equal(session.unsign_session_id(plane, signed), "sid-123")

    @pytest.mark.parametrize(("issued_for", "presented_to"), [(Plane.APP, Plane.CP), (Plane.CP, Plane.APP)])
    def test_other_plane_value_is_rejected(self, issued_for, presented_to):
        """あるプレーン向けに署名した Cookie 値は、同じセッション ID・同じ秘密鍵でも別プレーンでは無効(salt がプレーンごと)。"""
        signed = session.sign_session_id(issued_for, "same-sid")
        check.is_none(session.unsign_session_id(presented_to, signed))
        check.equal(session.unsign_session_id(issued_for, signed), "same-sid")

    def test_salt_differs_per_plane(self):
        """署名の salt はプレーンごとに異なる。"""
        check.not_equal(session._serializer(Plane.APP).salt, session._serializer(Plane.CP).salt)

    def test_same_salt_but_wrong_plane_in_payload_is_rejected(self):
        """salt が合っていても、署名対象の plane が違う値は拒否する(二重の防御)。"""
        forged = URLSafeSerializer(SESSION_SECRET, salt=f"{session.SESSION_SIGNING_SALT}:app").dumps({"sid": "sid-1", "plane": "cp"})
        check.is_none(session.unsign_session_id(Plane.APP, forged))

    @pytest.mark.parametrize("payload", [["sid-1"], "sid-1", 5, {"plane": "app"}, {"sid": "", "plane": "app"}, {"sid": 123, "plane": "app"}, {"sid": None, "plane": "app"}])
    def test_malformed_payload_is_rejected(self, payload):
        """署名は正しくても、中身が {sid: 非空の文字列, plane: 自プレーン} でなければ拒否する。"""
        forged = URLSafeSerializer(SESSION_SECRET, salt=f"{session.SESSION_SIGNING_SALT}:app").dumps(payload)
        check.is_none(session.unsign_session_id(Plane.APP, forged))

    @pytest.mark.parametrize("value", ["", "garbage", "a.b.c", "....", "日本語"])
    def test_garbage_is_rejected(self, value):
        """空・でたらめな文字列は例外にせず None を返す。"""
        check.is_none(session.unsign_session_id(Plane.APP, value))

    def test_tampered_value_is_rejected(self):
        """署名の一部を書き換えた値は拒否する。"""
        signed = session.sign_session_id(Plane.APP, "sid-123")
        tampered = signed[:-1] + ("A" if signed[-1] != "A" else "B")
        check.is_none(session.unsign_session_id(Plane.APP, tampered))

    def test_other_secret_key_invalidates_cookies(self, monkeypatch):
        """SESSION_SECRET_KEY を変えると、それまでに発行した Cookie 値はすべて無効になる。"""
        signed = session.sign_session_id(Plane.CP, "sid-123")
        monkeypatch.setenv("SESSION_SECRET_KEY", "another-secret")
        check.is_none(session.unsign_session_id(Plane.CP, signed))


class TestRedisKeySpace:
    """Redis のキー空間はプレーンごと(session:{plane}:{sid})。"""

    def test_create_session_uses_plane_key(self, fake_redis):
        """create_session はプレーンのキー空間に保存し、ttl を設定する。"""
        sid = session.create_session(Plane.APP, {"plane": "app"}, ttl_seconds=120)
        check.equal(fake_redis.keys(), [f"session:app:{sid}"])
        check.equal(fake_redis.ttls[f"session:app:{sid}"], 120)

    def test_session_is_invisible_from_the_other_plane(self, fake_redis):
        """AP のセッション ID を CP として引いても見つからず、CP 側からの削除は AP のセッションに影響しない。"""
        sid = session.create_session(Plane.APP, {"plane": "app", "marker": 1})
        check.is_none(session.get_session(Plane.CP, sid))
        session.delete_session(Plane.CP, sid)
        check.equal(session.get_session(Plane.APP, sid), {"plane": "app", "marker": 1})
        check.is_false(session.update_session(Plane.CP, sid, {"x": 1}), "別プレーンのセッションは更新できない")
        check.equal(session.get_session(Plane.APP, sid), {"plane": "app", "marker": 1})

    def test_same_sid_in_both_planes_are_independent(self, fake_redis):
        """同じセッション ID が両プレーンに存在しても、互いに独立している(同一ブラウザで AP と CP に同時ログイン)。"""
        fake_redis.setex("session:app:shared", 60, '{"plane": "app"}')
        fake_redis.setex("session:cp:shared", 60, '{"plane": "cp"}')
        check.equal(session.get_session(Plane.APP, "shared"), {"plane": "app"})
        check.equal(session.get_session(Plane.CP, "shared"), {"plane": "cp"})
        session.delete_session(Plane.APP, "shared")
        check.is_none(session.get_session(Plane.APP, "shared"))
        check.equal(session.get_session(Plane.CP, "shared"), {"plane": "cp"})

    def test_session_ids_are_unique_and_long(self):
        """セッション ID は十分長く、呼び出しごとに異なる。"""
        ids = {session.create_session(Plane.APP, {}) for _ in range(20)}
        check.equal(len(ids), 20)
        check.is_true(all(len(sid) >= 40 for sid in ids))

    def test_update_session_keeps_remaining_ttl(self, fake_redis):
        """update_session は残り TTL を維持したまま内容を書き換える(アクセスのたびに延命しない)。"""
        sid = session.create_session(Plane.CP, {"v": 1}, ttl_seconds=100)
        fake_redis.ttls[f"session:cp:{sid}"] = 42
        check.is_true(session.update_session(Plane.CP, sid, {"v": 2}))
        check.equal(session.get_session(Plane.CP, sid), {"v": 2})
        check.equal(fake_redis.ttls[f"session:cp:{sid}"], 42)

    def test_update_session_of_missing_session(self):
        """存在しないセッションの更新は False(新規作成しない)。"""
        check.is_false(session.update_session(Plane.APP, "nope", {"v": 1}))
        check.is_none(session.get_session(Plane.APP, "nope"))


class TestTtl:
    """セッション TTL の環境変数。"""

    @pytest.mark.parametrize(("raw", "expected"), [("3600", 3600), ("120", 120), ("10", 60), ("0", 60), ("-5", 60), ("abc", 3600), ("", 3600)])
    def test_ttl_from_environment(self, monkeypatch, raw, expected):
        """数値以外は 3600 にフォールバックし、60 秒未満は 60 秒に切り上げる。"""
        monkeypatch.setenv("SESSION_TTL_SECONDS", raw)
        check.equal(session.get_session_ttl_seconds(), expected)

    def test_unset_defaults_to_one_hour(self, monkeypatch):
        """未設定は 3600 秒。"""
        monkeypatch.delenv("SESSION_TTL_SECONDS", raising=False)
        check.equal(session.get_session_ttl_seconds(), 3600)


class TestCookies:
    """セッション Cookie の設定・削除。"""

    @pytest.mark.parametrize("plane", list(Plane))
    def test_set_cookie_attributes(self, plane):
        """Cookie 名はプレーンごと。HttpOnly・SameSite=Lax・Path=/ で、値は署名済み。"""
        response = Response()
        session.set_session_cookie(response, plane, "sid-1", secure=False)
        header = response.headers["set-cookie"]
        check.is_true(header.startswith(f"{SESSION_COOKIE_NAMES[plane]}="))
        check.is_in("HttpOnly", header)
        check.is_in("SameSite=lax", header)
        check.is_in("Path=/", header)
        check.is_not_in("Secure", header)
        value = header.split("=", 1)[1].split(";", 1)[0]
        check.equal(session.unsign_session_id(plane, value), "sid-1")
        other = Plane.CP if plane == Plane.APP else Plane.APP
        check.is_none(session.unsign_session_id(other, value))
        check.is_not_in("sid-1;", header, "セッション ID を平文で載せない")

    def test_secure_flag(self):
        """secure=True なら Secure 属性が付く。"""
        response = Response()
        session.set_session_cookie(response, Plane.APP, "sid-1", secure=True)
        check.is_in("Secure", response.headers["set-cookie"])

    @pytest.mark.parametrize("plane", list(Plane))
    def test_clear_cookie_only_touches_own_cookie(self, plane):
        """Cookie の削除は自プレーンの Cookie 名だけを対象にする(もう一方のプレーンのセッションを残す)。"""
        response = Response()
        session.clear_session_cookie(response, plane, secure=False)
        headers = response.headers.getlist("set-cookie")
        check.equal(len(headers), 1)
        check.is_true(headers[0].startswith(f'{SESSION_COOKIE_NAMES[plane]}="";') or headers[0].startswith(f"{SESSION_COOKIE_NAMES[plane]}=;"))
        other = Plane.CP if plane == Plane.APP else Plane.APP
        check.is_not_in(SESSION_COOKIE_NAMES[other], headers[0])
        check.is_in("Max-Age=0", headers[0])


class TestAuthState:
    """OIDC の state(1 回限り)。"""

    def test_state_is_consumed_once(self, fake_redis):
        """pop_auth_state は取り出すと同時に削除し、2 回目は None(リプレイ対策)。"""
        session.save_auth_state("state-1", {"plane": "app", "realm": "tenant-alpha", "code_verifier": "v", "nonce": "n"})
        check.equal(session.pop_auth_state("state-1")["realm"], "tenant-alpha")
        check.is_none(session.pop_auth_state("state-1"))
        check.equal(fake_redis.keys(), [])

    def test_unknown_state(self):
        """存在しない state は None。"""
        check.is_none(session.pop_auth_state("unknown"))

    def test_state_has_short_ttl(self, fake_redis):
        """state の既定の有効期限は 300 秒。"""
        session.save_auth_state("state-2", {"plane": "cp"})
        check.equal(fake_redis.ttls["auth_state:state-2"], 300)

    def test_state_is_not_in_the_session_key_space(self, fake_redis):
        """state はセッションのキー空間(session:...)とは別のキーに保存される。"""
        session.save_auth_state("abc", {"plane": "app"})
        check.is_true(all(not key.startswith("session:") for key in fake_redis.keys()))
        check.is_none(session.get_session(Plane.APP, "abc"))
