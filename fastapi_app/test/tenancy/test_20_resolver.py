# -*- coding: utf-8 -*-
"""modules.tenancy.resolver のユニットテスト(インメモリのレジストリで判定ロジックを検証)。"""
import uuid

import pytest
import pytest_check as check

from modules.tenancy.registry import TenantRecord, TenantStatus
from modules.tenancy.resolver import RegistryTenantResolver, TenantErrorCode, TenantResolutionError


class MapRegistry:
    """realm → TenantRecord の辞書で引くレジストリ。問い合わせた realm を記録する。"""

    def __init__(self, *records: TenantRecord) -> None:
        self.by_realm = {r.realm_name: r for r in records}
        self.realm_queries: list[str] = []

    def get_by_realm(self, realm_name: str) -> TenantRecord | None:
        self.realm_queries.append(realm_name)
        return self.by_realm.get(realm_name)

    def get_by_code(self, tenant_code: str) -> TenantRecord | None:
        return next((r for r in self.by_realm.values() if r.tenant_code == tenant_code), None)

    def get_by_id(self, tenant_id: uuid.UUID) -> TenantRecord | None:
        return next((r for r in self.by_realm.values() if r.tenant_id == tenant_id), None)


def _record(code: str = "alpha", status: str = "ACTIVE") -> TenantRecord:
    return TenantRecord(tenant_id=uuid.uuid4(), tenant_code=code, realm_name=f"tenant-{code}", status=status)


def _user(record: TenantRecord, **overrides) -> dict:
    """レコードに一致する正しいユーザー情報(セッションの user)を作る。"""
    user = {"sub": str(uuid.uuid4()), "realm": record.realm_name, "tenant_id": str(record.tenant_id), "preferred_username": "alice"}
    user.update(overrides)
    return user


def _code_of(exc_info) -> TenantErrorCode:
    return exc_info.value.code


class TestSuccess:
    """正常系。"""

    def test_resolves_context(self):
        """レジストリと一致し ACTIVE ならテナントコンテキストを返す(plane は app、user_id は sub)。"""
        record = _record()
        user = _user(record)
        ctx = RegistryTenantResolver(MapRegistry(record))(user)
        check.equal(ctx.tenant_id, record.tenant_id)
        check.equal(ctx.tenant_code, "alpha")
        check.equal(ctx.user_id, uuid.UUID(user["sub"]))
        check.equal(ctx.plane, "app")

    def test_tenant_id_claim_may_be_uuid_object(self):
        """tenant_id クレームが UUID オブジェクトでも受け付ける。"""
        record = _record()
        ctx = RegistryTenantResolver(MapRegistry(record))(_user(record, tenant_id=record.tenant_id))
        check.equal(ctx.tenant_id, record.tenant_id)

    def test_tenant_id_claim_case_insensitive(self):
        """tenant_id クレームの大文字表記も同じ UUID として一致する。"""
        record = _record()
        ctx = RegistryTenantResolver(MapRegistry(record))(_user(record, tenant_id=str(record.tenant_id).upper()))
        check.equal(ctx.tenant_id, record.tenant_id)

    def test_tenant_comes_from_registry_not_from_extra_fields(self):
        """コンテキストの tenant_code はレジストリ由来で、ユーザー情報の他の値には影響されない。"""
        record = _record("alpha")
        ctx = RegistryTenantResolver(MapRegistry(record))(_user(record, tenant_code="evil", preferred_username="evil"))
        check.equal(ctx.tenant_code, "alpha")

    @pytest.mark.parametrize("sub", ["not-a-uuid", "", None, 123, "12345"])
    def test_user_id_is_none_when_sub_is_not_uuid(self, sub):
        """sub が UUID として解釈できない(または無い)ときは user_id が None(拒否はしない)。"""
        record = _record()
        user = _user(record, sub=sub)
        ctx = RegistryTenantResolver(MapRegistry(record))(user)
        check.is_none(ctx.user_id)

    def test_user_id_is_none_when_sub_missing(self):
        """sub キー自体が無いときも user_id は None。"""
        record = _record()
        user = _user(record)
        del user["sub"]
        check.is_none(RegistryTenantResolver(MapRegistry(record))(user).user_id)

    def test_sub_may_be_uuid_object(self):
        """sub が UUID オブジェクトでもそのまま user_id になる。"""
        record = _record()
        sub = uuid.uuid4()
        check.equal(RegistryTenantResolver(MapRegistry(record))(_user(record, sub=sub)).user_id, sub)

    def test_custom_keys(self):
        """realm_key / tenant_id_key / user_id_key を差し替えられる。"""
        record = _record()
        sub = uuid.uuid4()
        resolver = RegistryTenantResolver(MapRegistry(record), realm_key="r", tenant_id_key="t", user_id_key="uid")
        ctx = resolver({"r": record.realm_name, "t": str(record.tenant_id), "uid": str(sub)})
        check.equal((ctx.tenant_id, ctx.user_id), (record.tenant_id, sub))

    def test_selects_the_matching_tenant_among_many(self):
        """複数テナントが登録されていても、ユーザーの realm に対応するテナントになる。"""
        alpha, beta = _record("alpha"), _record("beta")
        resolver = RegistryTenantResolver(MapRegistry(alpha, beta))
        check.equal(resolver(_user(alpha)).tenant_code, "alpha")
        check.equal(resolver(_user(beta)).tenant_code, "beta")


class TestRejections:
    """5 種のエラーコード。"""

    def test_claim_missing_variants(self):
        """realm / tenant_id が無い・空・型違いは tenant_claim_missing で、レジストリは引かない。"""
        record = _record()
        registry = MapRegistry(record)
        resolver = RegistryTenantResolver(registry)
        base = _user(record)
        broken = [
            {},
            {k: v for k, v in base.items() if k != "realm"},
            {k: v for k, v in base.items() if k != "tenant_id"},
            {**base, "realm": ""},
            {**base, "realm": None},
            {**base, "realm": 123},
            {**base, "tenant_id": None},
            {**base, "tenant_id": ""},
        ]
        for user in broken:
            with pytest.raises(TenantResolutionError) as exc_info:
                resolver(user)
            check.equal(_code_of(exc_info), TenantErrorCode.CLAIM_MISSING, f"user={user}")
        check.equal(registry.realm_queries, [], "判定前に弾くのでレジストリは引かない")

    @pytest.mark.parametrize("claim", ["not-a-uuid", "12345", " ", 123, 1.5, ["x"], b"bytes", "8d2f2d54-0000-7000-8000-00000000000"])
    def test_claim_invalid(self, claim):
        """tenant_id が UUID として解釈できなければ tenant_claim_invalid。"""
        record = _record()
        with pytest.raises(TenantResolutionError) as exc_info:
            RegistryTenantResolver(MapRegistry(record))(_user(record, tenant_id=claim))
        check.equal(_code_of(exc_info), TenantErrorCode.CLAIM_INVALID)

    def test_not_found(self):
        """レルムがレジストリに無ければ tenant_not_found。"""
        record = _record()
        with pytest.raises(TenantResolutionError) as exc_info:
            RegistryTenantResolver(MapRegistry())(_user(record))
        check.equal(_code_of(exc_info), TenantErrorCode.NOT_FOUND)

    def test_mismatch(self):
        """レルムは存在するが tenant_id クレームが別テナントのものなら tenant_mismatch。"""
        alpha, beta = _record("alpha"), _record("beta")
        with pytest.raises(TenantResolutionError) as exc_info:
            RegistryTenantResolver(MapRegistry(alpha, beta))(_user(alpha, tenant_id=str(beta.tenant_id)))
        check.equal(_code_of(exc_info), TenantErrorCode.MISMATCH)

    def test_mismatch_takes_precedence_over_inactive(self):
        """不一致のときは停止中でも tenant_mismatch(他テナントのセッションに状態を漏らさない)。"""
        suspended = _record("alpha", status="SUSPENDED")
        with pytest.raises(TenantResolutionError) as exc_info:
            RegistryTenantResolver(MapRegistry(suspended))(_user(suspended, tenant_id=str(uuid.uuid4())))
        check.equal(_code_of(exc_info), TenantErrorCode.MISMATCH)

    @pytest.mark.parametrize("status", [s.value for s in TenantStatus if s is not TenantStatus.ACTIVE] + ["UNKNOWN"])
    def test_inactive(self, status):
        """ACTIVE 以外(停止中・削除要求中・未知の状態を含む)は tenant_inactive。"""
        record = _record(status=status)
        with pytest.raises(TenantResolutionError) as exc_info:
            RegistryTenantResolver(MapRegistry(record))(_user(record))
        check.equal(_code_of(exc_info), TenantErrorCode.INACTIVE)

    def test_error_code_values_are_stable(self):
        """HTTP の detail に使うコード文字列は固定(API 契約)。"""
        check.equal(
            {c.name: c.value for c in TenantErrorCode},
            {
                "CLAIM_MISSING": "tenant_claim_missing",
                "CLAIM_INVALID": "tenant_claim_invalid",
                "NOT_FOUND": "tenant_not_found",
                "MISMATCH": "tenant_mismatch",
                "INACTIVE": "tenant_inactive",
            },
        )

    def test_error_carries_code_and_message(self):
        """TenantResolutionError は code を保持し、メッセージはコード文字列。"""
        error = TenantResolutionError(TenantErrorCode.INACTIVE)
        check.equal(error.code, TenantErrorCode.INACTIVE)
        check.equal(str(error), "tenant_inactive")
