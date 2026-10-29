# -*- coding: utf-8 -*-
"""公開 API(/api/v1/public)のテスト: ヘルスチェック、テナント存在確認の 404 の同一性、レート制限。"""
import os
import time
import uuid

import pytest
import pytest_check as check
import redis as redis_lib
from fastapi.testclient import TestClient

from app import app
from main_app.route.public import rate_limit
from main_app.route.public.api_health import router as health_router
from main_app.route.public.redis_client import get_public_redis

from .fake_redis import DownRedis

PUBLIC = "/api/v1/public"
LOOKUP = f"{PUBLIC}/tenants"


class TestHealth:
    """live / ready。"""

    def test_live(self, client):
        """live は 200 {status: ok}。認証不要。"""
        response = client.get(f"{PUBLIC}/health/live")
        check.equal((response.status_code, response.json()), (200, {"status": "ok"}))

    def test_live_does_not_touch_dependencies(self, client, monkeypatch):
        """live は DB・Redis を確認しない(依存先が落ちていても 200)。"""
        monkeypatch.setattr(health_router, "get_public_redis", lambda: DownRedis())
        monkeypatch.setattr(health_router, "get_cp_runtime_engine", lambda: pytest.fail("DB に触れてはならない"))
        check.equal(client.get(f"{PUBLIC}/health/live").status_code, 200)

    def test_ready_all_ok(self, client):
        """ready は CP DB・AP DB・Redis に接続できれば 200 で、3 つとも ok。Keycloak は含まない。"""
        response = client.get(f"{PUBLIC}/health/ready")
        if response.status_code == 503 and response.json()["checks"].get("app_db") == "unavailable":
            pytest.skip("app_db に接続できない環境")
        check.equal((response.status_code, response.json()), (200, {"status": "ok", "checks": {"cp_db": "ok", "app_db": "ok", "redis": "ok"}}))

    @pytest.mark.parametrize("broken", ["redis", "cp_db", "app_db"])
    def test_ready_reports_unavailable_with_503(self, client, monkeypatch, broken):
        """依存先のどれかが失敗すると 503。失敗した確認だけが unavailable で、接続エラーの詳細は応答に含まれない。"""
        secret = "postgresql://user:SECRET-PASSWORD@db.invalid/x"

        def boom():
            raise RuntimeError(secret)

        if broken == "redis":
            monkeypatch.setattr(health_router, "_check_redis", boom)
        else:
            real = health_router._check_database
            target = {"cp_db": health_router.get_cp_runtime_engine, "app_db": health_router.get_app_runtime_engine}[broken]
            monkeypatch.setattr(health_router, "_check_database", lambda get_engine: boom() if get_engine is target else real(get_engine))
        response = client.get(f"{PUBLIC}/health/ready")
        body = response.json()
        check.equal((response.status_code, body["status"]), (503, "unavailable"))
        check.equal(body["checks"][broken], "unavailable")
        others = {name: value for name, value in body["checks"].items() if name != broken}
        check.is_true(all(value in ("ok", "unavailable") for value in others.values()))
        check.is_not_in("SECRET-PASSWORD", response.text)
        check.is_not_in("RuntimeError", response.text)

    def test_ready_when_redis_is_down(self, client, monkeypatch):
        """Redis に接続できなければ 503 で redis=unavailable。"""
        monkeypatch.setattr(health_router, "get_public_redis", lambda: DownRedis())
        response = client.get(f"{PUBLIC}/health/ready")
        check.equal((response.status_code, response.json()["checks"]["redis"]), (503, "unavailable"))

    def test_run_checks_times_out_slow_checks(self):
        """期限(timeout)を過ぎた確認は待たずに unavailable として返す。"""
        started = time.monotonic()
        result = health_router.run_checks({"slow": lambda: time.sleep(2), "fast": lambda: None}, timeout=0.2)
        check.equal(result, {"slow": "unavailable", "fast": "ok"})
        check.is_true(time.monotonic() - started < 1.5, "期限で打ち切って応答する")


def comparable(response):
    """404 の応答から、リクエスト固有の値(instance=リクエストのパス、request_id、X-Request-ID、長さ、日時)を除いた比較用の値を作る。"""
    body = response.json()
    body.pop("instance")
    assert body.pop("request_id") == response.headers["X-Request-ID"]
    headers = {k.lower(): v for k, v in response.headers.items() if k.lower() not in ("x-request-id", "content-length", "date")}
    return response.status_code, headers, body


class TestTenantLookup:
    """テナント存在確認。"""

    def test_existing_tenant_returns_only_code_and_status(self, client, seeded):
        """存在するテナントは tenant_code と status だけを返す(名前・認証領域名・ID・クライアント ID は返さない)。認証不要。"""
        seeded("alpha")
        response = client.get(f"{LOOKUP}/alpha")
        check.equal((response.status_code, response.json()), (200, {"tenant_code": "alpha", "status": "ACTIVE"}))

    @pytest.mark.parametrize("status", ["PROVISIONING", "ACTIVE", "FAILED", "SUSPENDED", "PENDING_DELETION", "DEPROVISIONING"])
    def test_status_is_reported_for_non_deleted(self, client, cp_db, status):
        """削除済み以外のテナントは、状態をそのまま返す(ログインできるのは ACTIVE のみ)。"""
        tenant_id = cp_db.insert_tenant(status=status)
        code = cp_db.tenant(tenant_id)["tenant_code"]
        check.equal(client.get(f"{LOOKUP}/{code}").json(), {"tenant_code": code, "status": status})

    def not_found_cases(self, cp_db):
        deleted_id = cp_db.insert_tenant(status="DELETED")
        deleted = cp_db.tenant(deleted_id)["tenant_code"]
        return {
            "未登録": "no-such-tenant",
            "削除済み": deleted,
            "予約語 admin": "admin",
            "予約語 api": "api",
            "予約語 dev-login": "dev-login",
            "予約語 cp": "cp",
            "短すぎる": "ab",
            "大文字": "ALPHA",
            "連続ハイフン": "a--b",
            "先頭ハイフン": "-abc",
            "アンダースコア": "a_b",
            "ドット": "favicon.ico",
            "改行": "alpha%0A",
            "空白": "al%20pha",
            "日本語": "%E6%97%A5%E6%9C%AC%E8%AA%9E",
            "33文字": "a" * 33,
            "SQL": "a%27%3B%20DROP%20TABLE%20t_tenant%3B%20--",
        }

    def test_not_found_responses_are_identical(self, client, cp_db):
        """存在しない・削除済み・予約語・形式不正は、ステータス・ヘッダー・本文(instance と request_id 以外)が完全に同一の 404(tenant_not_found)。"""
        baseline = None
        for label, code in self.not_found_cases(cp_db).items():
            current = comparable(client.get(f"{LOOKUP}/{code}"))
            check.equal(current[0], 404, label)
            baseline = baseline or current
            check.equal(current, baseline, f"{label} が他と区別できる")
        check.equal(baseline[2]["code"], "tenant_not_found")
        check.is_in("application/problem+json", baseline[1]["content-type"])

    @pytest.mark.parametrize("code", ["a" * 65, "a" * 200])
    def test_overlong_code_is_also_the_same_404(self, client, code):
        """65 文字以上の形式不正も、他と同じ 404(tenant_not_found)になること。"""
        response = client.get(f"{LOOKUP}/{code}")
        check.equal((response.status_code, response.json()["code"]), (404, "tenant_not_found"))

    def test_not_found_does_not_reveal_anything(self, client):
        """404 の本文に、入力したコードや『存在しない』『削除済み』といった区別になる情報を含めない。"""
        response = client.get(f"{LOOKUP}/zz-unknown-code")
        body = response.json()
        body.pop("instance")  # リクエストのパスはそのまま入る(リクエスト自身の値)
        check.is_not_in("zz-unknown-code", str(body))
        check.equal(body["errors"], [])
        for word in ("削除", "存在しません", "deleted", "reserved", "予約"):
            check.is_not_in(word, body["detail"] + body["title"])

    def test_deleted_tenant_looks_like_unknown(self, client, cp_db):
        """削除済みのテナントの応答は、未登録のテナントと同じ(状態を明かさない)。"""
        code = cp_db.tenant(cp_db.insert_tenant(status="DELETED"))["tenant_code"]
        deleted = comparable(client.get(f"{LOOKUP}/{code}"))
        ghost = comparable(client.get(f"{LOOKUP}/no-such-one"))
        check.equal(deleted, ghost)

    def test_no_authentication_needed_and_cookies_are_irrelevant(self, client, admin, seeded):
        """Cookie があってもなくても同じ応答(認証に依存しない)。"""
        seeded("alpha")
        check.equal(client.get(f"{LOOKUP}/alpha", headers=admin).json(), client.get(f"{LOOKUP}/alpha").json())

    def test_post_is_not_allowed(self, client):
        """存在確認は GET のみ(POST は 405 の Problem Details)。"""
        response = client.post(f"{LOOKUP}/alpha")
        check.equal((response.status_code, response.json()["code"]), (405, "method_not_allowed"))


class TestRateLimit:
    """存在確認の IP 単位レート制限(Redis の固定ウィンドウ)。"""

    @pytest.fixture(autouse=True)
    def _small_limit(self, monkeypatch):
        monkeypatch.setenv("PUBLIC_TENANT_LOOKUP_RATE_LIMIT", "3")
        monkeypatch.setenv("PUBLIC_TENANT_LOOKUP_RATE_WINDOW_SECONDS", "60")

    def test_over_limit_is_429_with_retry_after(self, client):
        """上限(3 回)までは通り、4 回目が 429(too_many_requests)。Retry-After は 1〜60 秒。"""
        statuses = [client.get(f"{LOOKUP}/no-such").status_code for _ in range(3)]
        check.equal(statuses, [404, 404, 404])
        response = client.get(f"{LOOKUP}/no-such")
        check.equal((response.status_code, response.json()["code"]), (429, "too_many_requests"))
        check.is_in("application/problem+json", response.headers["content-type"])
        check.is_true(1 <= int(response.headers["Retry-After"]) <= 60)
        check.is_true(all(client.get(f"{LOOKUP}/no-such").status_code == 429 for _ in range(3)), "ウィンドウ内は拒否され続ける")

    def test_existing_and_unknown_codes_share_the_same_budget(self, client, seeded):
        """存在するコードも存在しないコードも同じ枠を消費する(応答の違いから存在を推測させない)。"""
        seeded("alpha")
        for code in ("alpha", "no-such", "alpha"):
            client.get(f"{LOOKUP}/{code}")
        for code in ("alpha", "no-such"):
            check.equal(client.get(f"{LOOKUP}/{code}").status_code, 429, code)

    def test_other_clients_have_their_own_budget(self):
        """クライアントの IP ごとに枠が別。"""
        first = TestClient(app, client=("198.51.100.10", 1000), raise_server_exceptions=False)
        second = TestClient(app, client=("198.51.100.11", 1000), raise_server_exceptions=False)
        for _ in range(4):
            first.get(f"{LOOKUP}/no-such")
        check.equal(first.get(f"{LOOKUP}/no-such").status_code, 429)
        check.equal(second.get(f"{LOOKUP}/no-such").status_code, 404)

    def test_window_resets(self, client, fake_redis):
        """ウィンドウが過ぎれば再び通る(固定ウィンドウ)。"""
        now = [1000.0]
        fake_redis.clock = lambda: now[0]
        for _ in range(4):
            client.get(f"{LOOKUP}/no-such")
        check.equal(client.get(f"{LOOKUP}/no-such").status_code, 429)
        now[0] += 61
        check.equal(client.get(f"{LOOKUP}/no-such").status_code, 404)

    def test_counter_key_always_has_an_expiry(self, client, fake_redis):
        """カウンタのキーには必ず有効期限が付く(期限の無いキーが残らない)。"""
        client.get(f"{LOOKUP}/no-such")
        keys = fake_redis.keys_with_prefix("rate_limit:public_tenant_lookup:")
        check.equal(len(keys), 1)
        check.is_true(0 < fake_redis.ttl(keys[0]) <= 60)

    def test_other_public_endpoints_are_not_limited(self, client):
        """health は制限されない。"""
        for _ in range(10):
            client.get(f"{LOOKUP}/no-such")
        check.equal(client.get(f"{PUBLIC}/health/live").status_code, 200)

    def test_zero_disables_the_limit(self, client, monkeypatch):
        """上限 0 は無効(制限しない)。"""
        monkeypatch.setenv("PUBLIC_TENANT_LOOKUP_RATE_LIMIT", "0")
        check.is_true(all(client.get(f"{LOOKUP}/no-such").status_code == 404 for _ in range(10)))

    @pytest.mark.parametrize("raw", ["abc", "-5", ""])
    def test_invalid_limit_falls_back_to_default(self, monkeypatch, raw):
        """不正な設定値は既定値(60)にフォールバックする。"""
        monkeypatch.setenv("PUBLIC_TENANT_LOOKUP_RATE_LIMIT", raw)
        check.equal(rate_limit.get_limit(), 60)

    def test_fail_open_when_redis_is_down(self, client, caplog):
        """Redis に接続できないときは制限せずに通す(fail-open)。警告をログに残す。"""
        app.dependency_overrides[get_public_redis] = lambda: DownRedis()
        with caplog.at_level("WARNING"):
            statuses = [client.get(f"{LOOKUP}/no-such").status_code for _ in range(6)]
        check.equal(statuses, [404] * 6)
        check.is_in("fail-open", caplog.text)


@pytest.fixture
def real_redis_db15():
    """実 Redis の DB 15 を使うクライアント(接続できなければ skip)。このテストが使うキーだけを後始末する。"""
    base = os.environ.get("REDIS_URL", "redis://redis_c:6379/0").rsplit("/", 1)[0]
    client = redis_lib.Redis.from_url(f"{base}/15", decode_responses=True, socket_timeout=1, socket_connect_timeout=1)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError:
        pytest.skip("Redis に接続できないためスキップ")
    created: list[str] = []
    yield client, created
    for key in created:
        client.delete(key)
    client.close()


class TestRateLimitWithRealRedis:
    """実 Redis(DB 15)での固定ウィンドウ(MULTI の SET NX EX + INCR + TTL)。"""

    def test_limit_and_expiry_against_real_redis(self, real_redis_db15, monkeypatch):
        """実 Redis で、上限超過の 429、キーの有効期限、ウィンドウ経過後の再開が機能する。"""
        redis_client, created = real_redis_db15
        host = f"203.0.113.{uuid.uuid4().int % 200 + 1}"
        key = f"rate_limit:public_tenant_lookup:{host}"
        created.append(key)
        monkeypatch.setenv("PUBLIC_TENANT_LOOKUP_RATE_LIMIT", "2")
        monkeypatch.setenv("PUBLIC_TENANT_LOOKUP_RATE_WINDOW_SECONDS", "1")
        app.dependency_overrides[get_public_redis] = lambda: redis_client
        client = TestClient(app, client=(host, 4000), raise_server_exceptions=False)
        check.equal([client.get(f"{LOOKUP}/no-such").status_code for _ in range(3)], [404, 404, 429])
        check.is_true(0 < redis_client.ttl(key) <= 1, "有効期限が付いている")
        time.sleep(1.2)
        check.equal(client.get(f"{LOOKUP}/no-such").status_code, 404)
