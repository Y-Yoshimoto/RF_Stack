#!/usr/bin/env python
# coding:utf-8
"""CP から AP DB（``app_db``）のテナントデータを物理削除するリポジトリ（01 CP-OPS-08、02 §4.5）。

接続は ``app_cp_agent``（SELECT / DELETE のみ、RLS 適用）。テナントは
:func:`modules.tenancy.db.run_per_tenant` で GUC ``app.current_tenant`` を切り替えて処理するため、
RLS を迂回しない（01 §9.2）。

拡張点（01 §13 #9 物理削除の対象）:
    テーマは :data:`TENANT_DATA_PURGE_TABLES` に、テナントスコープのテーブル名を **削除する順**
    （複合外部キーで参照する子テーブルを先）に追加する。``control_plane_app`` は ``main_app`` を
    import しない（02 §5.1）ため、モデルではなくテーブル名で指定する。
    行の削除以外の処理が必要な場合は :class:`TenantDataPurgeStep` を作り、
    :class:`AppTenantDataRepository` の ``steps`` に渡す。

    現在の対象は AP 共通テーブル（ユーザー・組織・組織メンバー・AP 監査ログ）と ToDo のテーブル。
    CP から AP への書き込み（INSERT / UPDATE）は行わない。払い出し時の AP の初期データは AP がログイン完了時に作る（05 #31）。
"""
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import Engine, text
from sqlmodel import Session

from modules.tenancy.db import run_per_tenant

# テナント物理削除の対象テーブル（削除する順。子テーブルを先に並べる）。01 §13 #9 の拡張点。
# テーマ(ToDo)のテーブルを先に、基盤の共通テーブルを後に削除する(ToDoApp.md §7 #9)。t_user は全テーブルから参照されるため最後。
TENANT_DATA_PURGE_TABLES: tuple[str, ...] = (
    # ToDo(main_app.models.todo)
    "t_todo_activity",
    "t_todo_assignee",
    "t_todo_organization",
    "t_todo",
    # AP 共通(main_app.models.ap_common)
    "t_organization_member",
    "t_organization",
    "t_ap_audit_log",
    "t_user",
)

# テーブル名として許可する形式（"table" または "schema.table"。英小文字・数字・アンダースコア）。
_TABLE_NAME_PATTERN = re.compile(r"[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?")


@dataclass(frozen=True, kw_only=True)
class TenantDataPurgeStep:
    """テナントデータの物理削除の 1 ステップ。

    Attributes:
        name: ステップ名（結果のキー・ログに使う）。
        purge: ``(session, tenant_id) -> 削除件数``。GUC は設定済みのセッションで呼ばれる。
            同じテナントで再実行されても成功すること（冪等）。
    """

    name: str
    purge: Callable[[Session, uuid.UUID], int]


def _quote_table_name(table_name: str) -> str:
    """テーブル名を検証し、識別子としてクォートする。

    Args:
        table_name: テーブル名。

    Returns:
        str: クォート済みのテーブル名。

    Raises:
        ValueError: 許可されない形式の場合。
    """
    if not _TABLE_NAME_PATTERN.fullmatch(table_name):
        raise ValueError(f"invalid table name: {table_name!r}")
    return ".".join(f'"{part}"' for part in table_name.split("."))


def table_purge_step(table_name: str) -> TenantDataPurgeStep:
    """テーブルのテナントの行をすべて削除するステップを作る。

    RLS により GUC のテナントの行しか見えないが、多重防御として ``tenant_id`` の条件も付ける。
    既に行が無ければ 0 件で成功する（冪等）。

    Args:
        table_name: テナントスコープのテーブル名（``tenant_id`` 列を持つこと）。

    Returns:
        TenantDataPurgeStep: 削除ステップ。

    Raises:
        ValueError: テーブル名が不正な場合。
    """
    statement = text(f"DELETE FROM {_quote_table_name(table_name)} WHERE tenant_id = :tenant_id")

    def purge(session: Session, tenant_id: uuid.UUID) -> int:
        """テナントの行を削除し、件数を返す。"""
        result = session.connection().execute(statement, {"tenant_id": tenant_id})
        return int(result.rowcount or 0)

    return TenantDataPurgeStep(name=table_name, purge=purge)


def default_purge_steps() -> list[TenantDataPurgeStep]:
    """:data:`TENANT_DATA_PURGE_TABLES` から削除ステップを作る。

    Returns:
        list[TenantDataPurgeStep]: 削除ステップ（登録順）。
    """
    return [table_purge_step(table_name) for table_name in TENANT_DATA_PURGE_TABLES]


def _default_engine_factory() -> Engine:
    """``app_cp_agent`` のエンジンを返す（providers は FastAPI を import するため遅延 import する）。"""
    from modules.tenancy.providers import get_app_cp_agent_engine

    return get_app_cp_agent_engine()


class AppTenantDataRepository:
    """AP DB のテナントデータの物理削除。

    Args:
        engine_factory: ``app_cp_agent`` のエンジンを返す関数（最初の削除まで呼ばない）。
            省略時は :func:`modules.tenancy.providers.get_app_cp_agent_engine`。
        steps: 削除ステップ。省略時は :func:`default_purge_steps`。
    """

    def __init__(self, engine_factory: Callable[[], Engine] | None = None, steps: Sequence[TenantDataPurgeStep] | None = None) -> None:
        """エンジンの取得方法と削除ステップを保持する。"""
        self._engine_factory = engine_factory or _default_engine_factory
        self._steps = list(steps) if steps is not None else default_purge_steps()

    @property
    def step_names(self) -> list[str]:
        """削除ステップ名の一覧を返す。"""
        return [step.name for step in self._steps]

    def purge_tenant_data(self, tenant_id: uuid.UUID) -> dict[str, int]:
        """テナントのデータを 1 トランザクションで物理削除する。

        すべてのステップが成功した場合だけコミットする（途中で失敗したら全体をロールバックし、
        次回の実行で最初からやり直す）。ステップが無ければ DB に接続しない。

        Args:
            tenant_id: テナント ID。

        Returns:
            dict[str, int]: ステップ名ごとの削除件数。

        Raises:
            sqlalchemy.exc.SQLAlchemyError: DB の操作に失敗した場合。
        """
        if not self._steps:
            return {}
        with Session(self._engine_factory()) as session, session.begin():
            results = run_per_tenant(session, [tenant_id], lambda tid: {step.name: step.purge(session, tid) for step in self._steps})
        return results[tenant_id]
