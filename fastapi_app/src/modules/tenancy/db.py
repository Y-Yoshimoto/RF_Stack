#!/usr/bin/env python
# coding:utf-8
"""RLS 用 GUC ``app.current_tenant`` を DB トランザクションに適用するモジュール。

SQLAlchemy に依存し、FastAPI には依存しない。

``app_db`` の RLS ポリシーは
``NULLIF(current_setting('app.current_tenant', true), '')::uuid`` を参照する。
本モジュールはこの GUC を設定する唯一の経路とする。

トランザクションスコープについて:
    GUC は ``set_config('app.current_tenant', <tenant_id>, true)`` で設定する。
    第 3 引数 ``true`` (is_local) により ``SET LOCAL`` と同じくトランザクション終了
    （COMMIT / ROLLBACK）で自動的に破棄される。SAVEPOINT をロールバックした場合も、
    その中で行った設定は巻き戻る。このため **コネクションプールに返却された接続に
    テナントの値が残ることはない**。セッションスコープの ``SET`` は使わないこと。

    GUC が未設定（または空文字）のトランザクションでは、RLS により全テーブルが 0 件に
    見える。設定漏れは「他テナントが見える」ではなく「何も見えない」側に倒れる。

提供する機能:
    - :func:`apply_tenant_guc` — 接続またはセッションの現在のトランザクションに GUC を設定する。
    - :func:`install_tenant_guc_listener` — Session の ``after_begin`` で
      :mod:`modules.tenancy.context` のテナントを自動適用する。
    - :func:`tenant_guc_scope` — 1 トランザクション内でテナントを一時的に切り替える
      （コントロールプレーンの集計・削除用）。
    - :func:`run_per_tenant` — 複数テナントに対して順に同じ処理を実行する。
"""
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from .context import get_tenant_context

# RLS ポリシーが参照する GUC 名。ポリシー定義（postgres-schema 担当）と一致させること。
TENANT_GUC_NAME = "app.current_tenant"

# set_config の第 3 引数 true でトランザクションスコープ（SET LOCAL 相当）にする。
# 値は必ずバインドパラメータで渡し、SQL 文字列に埋め込まない。
_SET_TENANT_GUC_SQL = text(f"SELECT set_config('{TENANT_GUC_NAME}', :tenant_id, true)")
_GET_TENANT_GUC_SQL = text(f"SELECT current_setting('{TENANT_GUC_NAME}', true)")

# リスナーを登録できる対象。
type ListenerTarget = Session | sessionmaker | type[Session]


def _as_connection(bind: Session | Connection) -> Connection:
    """セッションまたは接続から、SQL を実行する ``Connection`` を取り出す。

    SQLModel の ``Session.execute`` は非推奨警告を出すため、``Session`` の場合は
    ``Session.connection()`` 経由で実行する。トランザクション未開始なら開始される。

    Args:
        bind: SQLAlchemy / SQLModel のセッション、または接続。

    Returns:
        Connection: 現在のトランザクションに紐づく接続。
    """
    if isinstance(bind, Session):
        return bind.connection()
    return bind


def apply_tenant_guc(bind: Session | Connection, tenant_id: uuid.UUID | None) -> None:
    """現在のトランザクションに ``app.current_tenant`` を設定する。

    トランザクションスコープ（``SET LOCAL`` 相当）のため、COMMIT / ROLLBACK で破棄され、
    コネクションプールに値は残らない。

    Args:
        bind: GUC を設定するセッションまたは接続。トランザクション未開始なら開始される。
        tenant_id: 設定するテナント ID。``None`` の場合は空文字を設定し、
            RLS により 0 件となる状態（テナントなし）に戻す。

    Raises:
        TypeError: ``tenant_id`` が ``uuid.UUID`` でも ``None`` でもない場合。
    """
    if tenant_id is not None and not isinstance(tenant_id, uuid.UUID):
        raise TypeError("tenant_id must be uuid.UUID or None")
    value = "" if tenant_id is None else str(tenant_id)
    _as_connection(bind).execute(_SET_TENANT_GUC_SQL, {"tenant_id": value})


def get_tenant_guc(bind: Session | Connection) -> uuid.UUID | None:
    """現在のトランザクションに設定されている ``app.current_tenant`` を取得する。

    Args:
        bind: 対象のセッションまたは接続。

    Returns:
        uuid.UUID | None: 設定中のテナント ID。未設定・空文字の場合は ``None``。
    """
    value = _as_connection(bind).execute(_GET_TENANT_GUC_SQL).scalar()
    if not value:
        return None
    return uuid.UUID(str(value))


def _apply_context_tenant_on_begin(session: Session, transaction: SessionTransaction, connection: Connection) -> None:
    """Session の ``after_begin`` イベントで、現在のテナントコンテキストを GUC に適用する。

    テナントコンテキストが無ければ何もしない（RLS により 0 件となる）。

    Args:
        session: トランザクションを開始したセッション。
        transaction: 開始されたセッショントランザクション。
        connection: トランザクションに紐づく接続。
    """
    ctx = get_tenant_context()
    if ctx is None:
        return
    connection.execute(_SET_TENANT_GUC_SQL, {"tenant_id": str(ctx.tenant_id)})


def install_tenant_guc_listener(target: ListenerTarget) -> None:
    """Session のトランザクション開始時に、テナントコンテキストを GUC に自動適用する。

    ``after_begin`` イベントにリスナーを登録する。セッションがトランザクションを開始する
    たびに（COMMIT 後の次のトランザクションも含む）、その時点の
    :func:`~modules.tenancy.context.get_tenant_context` の値を ``SET LOCAL`` 相当で設定する。
    コンテキストが無ければ何もしない（RLS により 0 件）。同じ対象への重複登録は無視する。

    Note:
        - 値を読むのは **トランザクション開始時点** である。トランザクションの途中で
          テナントコンテキストを切り替えても GUC には反映されない。途中で切り替える場合は
          :func:`tenant_guc_scope` を使う。
        - ``Session`` クラス自体に登録すると、そのクラスを使う全 DB（コントロールプレーン DB
          を含む）に効く。``app_db`` 用のセッション / ``sessionmaker`` / インスタンスに
          限定して登録することを推奨する。

    Args:
        target: リスナーを登録するセッションインスタンス、``sessionmaker``、
            または ``Session`` のサブクラス。
    """
    if not event.contains(target, "after_begin", _apply_context_tenant_on_begin):
        event.listen(target, "after_begin", _apply_context_tenant_on_begin)


def uninstall_tenant_guc_listener(target: ListenerTarget) -> None:
    """:func:`install_tenant_guc_listener` で登録したリスナーを解除する。

    登録されていない場合は何もしない。主にテストの後始末で使う。

    Args:
        target: :func:`install_tenant_guc_listener` に渡した対象。
    """
    if event.contains(target, "after_begin", _apply_context_tenant_on_begin):
        event.remove(target, "after_begin", _apply_context_tenant_on_begin)


def _flush_if_session(bind: Session | Connection) -> None:
    """セッションの場合は未送信の変更を現在の GUC のうちに DB へ送る。

    autoflush により、テナント A で追加したオブジェクトがテナント B に切り替えた後に
    flush されると、RLS の WITH CHECK で拒否される（ポリシーによっては誤ったテナントで
    書き込まれる）。切り替え前に必ず flush しておく。

    Args:
        bind: 対象のセッションまたは接続。
    """
    if isinstance(bind, Session):
        bind.flush()


@contextmanager
def tenant_guc_scope(bind: Session | Connection, tenant_id: uuid.UUID) -> Iterator[None]:
    """1 トランザクション内で、ブロックの間だけ GUC を指定テナントに切り替える。

    コントロールプレーンが ``app_db`` に専用ロールで接続し、RLS をバイパスせずに
    テナント毎の集計・削除を行うための部品。

    動作:
        1. ``bind`` がセッションなら flush し、切り替え前の変更を元の GUC のうちに確定させる。
        2. 現在の GUC 値を退避し、``tenant_id`` を設定する。
        3. ブロックが **正常終了** したら flush してから退避した値に戻す（入れ子にできる）。
        4. ブロック内で例外が発生した場合は戻さずに再送出する。トランザクションが
           エラー状態だと SQL を実行できず元の例外を隠してしまうため。
           GUC はトランザクションスコープなので、呼び出し側がロールバック（SAVEPOINT の
           ロールバックを含む）すれば設定も巻き戻る。

    Note:
        ORM のアイデンティティマップには切り替え前のテナントで読み込んだオブジェクトが
        残る。テナントを跨いでオブジェクトを使い回さないこと。

    Args:
        bind: 対象のセッションまたは接続。トランザクション未開始なら開始される。
        tenant_id: ブロック内で有効にするテナント ID。

    Yields:
        None

    Raises:
        TypeError: ``tenant_id`` が ``uuid.UUID`` でない場合。
    """
    if not isinstance(tenant_id, uuid.UUID):
        raise TypeError("tenant_id must be uuid.UUID")
    _flush_if_session(bind)
    previous = get_tenant_guc(bind)
    apply_tenant_guc(bind, tenant_id)
    yield
    _flush_if_session(bind)
    apply_tenant_guc(bind, previous)


def run_per_tenant[T](bind: Session | Connection, tenant_ids: Iterable[uuid.UUID], func: Callable[[uuid.UUID], T]) -> dict[uuid.UUID, T]:
    """複数テナントに対し、GUC を切り替えながら同じ処理を順に実行する。

    各テナントの処理は :func:`tenant_guc_scope` の中で実行される。すべて同一トランザクション
    内で行われるため、途中で例外が発生した場合は以降のテナントは処理せずに再送出する
    （コミット / ロールバックの判断は呼び出し側に委ねる）。

    使用例::

        with Session(cp_app_db_engine) as session, session.begin():
            counts = run_per_tenant(session, tenant_ids, lambda _tid: session.exec(select(func.count()).select_from(Todo)).one())

    Args:
        bind: 対象のセッションまたは接続。
        tenant_ids: 処理対象のテナント ID 群。重複は後勝ちで結果が上書きされる。
        func: テナント ID を受け取り結果を返す処理。``bind`` はクロージャで参照する。

    Returns:
        dict[uuid.UUID, T]: テナント ID ごとの処理結果。
    """
    results: dict[uuid.UUID, T] = {}
    for tenant_id in tenant_ids:
        with tenant_guc_scope(bind, tenant_id):
            results[tenant_id] = func(tenant_id)
    return results

