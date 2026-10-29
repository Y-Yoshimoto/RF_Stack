---
name: tenant-isolation
description: マルチテナントのテナント分離の実装規則とテスト方法。app_db のテナントスコープのテーブル（tenant_id・複合外部キー・RLS）、テナントコンテキスト（modules/tenancy）の使い方、DB ロールの使い分け、クロステナントテストの観点とフィクスチャを扱う。「テナントスコープのテーブルを追加したい」「RLS を設定して」「他テナントのデータが見えないことをテストして」「テナントコンテキストの使い方」といった依頼や、AP のデータを扱う API・リポジトリを追加/変更したときに使用する。
---

# テナント分離の実装とテスト

仕様の正は `docs/architecture/01-platform-concepts.md`（§9）と `docs/architecture/02-platform-implementation.md`（§4, §5.3）。本スキルは実装・テスト時の手順と確認項目をまとめる。

## 1. 守ること（不変条件）

1. **テナントはセッション（認証結果）からのみ導出する。** リクエストボディ・クエリ・ヘッダーの `tenant_id` を信用しない。
2. **AP の DB アクセスは `app_runtime` ロール + テナントコンテキスト下で行う。** コンテキスト無しのクエリは RLS で 0 件になる（エラーにならないので気づきにくい）。
3. **RLS をバイパスするロールを作らない・使わない。** テナント横断の処理（CP の集計・物理削除）も、テナント毎にコンテキストを切り替えて行う。
4. **プレーン間の依存は 2 つだけ。** AP → CP は `v_tenant_registry` の参照（`cp_registry_reader`）、CP → AP は集計・物理削除（`app_cp_agent`）。それ以外の接続を作らない。
5. **閲覧範囲（テーマ固有の公開範囲）の判定はアプリ層で行う。** RLS はテナント境界の最終防衛線であり、閲覧範囲の代わりにしない。
6. **他テナントや閲覧範囲外のリソースは 404 を返す**（存在を明かさない）。

## 2. DB ロールの使い分け

| 処理 | DB | ロール |
| --- | --- | --- |
| マイグレーション（CP） | control_plane_db | `cp_owner` |
| CP API・定期ジョブ | control_plane_db | `cp_runtime` |
| AP からテナントレジストリ参照 | control_plane_db | `cp_registry_reader` |
| マイグレーション（AP） | app_db | `app_owner` |
| AP API | app_db | `app_runtime` |
| CP からの集計・物理削除 | app_db | `app_cp_agent` |

接続情報の環境変数は `.env.default` を参照する（`.env` は読まない）。

## 3. テナントスコープのテーブルを追加する

1. モデルは `modules/tenancy/models.py` のテナントスコープの基底を使い、AP 用の MetaData に載せる（CP 用に載せない）。置き場所は `src/main_app/models/`。
2. 主キーは `uuid`（UUIDv7）。参照される側に `UNIQUE (tenant_id, id)` を置き、外部キーは `(tenant_id, <fk>)` → `(tenant_id, id)` の複合キーにする。
3. リビジョンは `alembic/alembic_app.ini` で作る（`db-migration` スキル）。
4. **autogenerate は RLS を検出しない。** 生成されたリビジョンの `upgrade()` に `enable_tenant_rls("<table>")`、`downgrade()` に `disable_tenant_rls("<table>")` を手で追加する（`modules/tenancy/rls.py`）。
5. 一覧の性能のため、検索条件のインデックスは `tenant_id` を先頭にする。

レビュー時の確認:

- [ ] `tenant_id` が NOT NULL か
- [ ] `ENABLE` と `FORCE ROW LEVEL SECURITY` の両方が設定されるか
- [ ] 外部キーが複合キーか
- [ ] 一意制約に `tenant_id` が含まれるか（テナント内で一意）
- [ ] 論理削除を使う場合、一意制約が部分インデックスか

## 4. テナントコンテキストを使う

| 場面 | 使うもの |
| --- | --- |
| AP のルーター | `modules/tenancy/app_dependency.py` の `get_app_tenant_context`（型エイリアス `AppTenantContextDep`）をルーター単位で適用する: `APIRouter(dependencies=[Depends(get_app_tenant_context)])`。拒否時は 403（`detail` は `tenant_not_found` 等のコード） |
| AP の DB セッション | `app_dependency.py` の `AppSessionDep`（`get_app_db_session`）。テナント判定に依存するため、判定前にセッションは開始されない。`app_runtime` 用の sessionmaker にだけ GUC リスナーが登録済み（自分で `install_tenant_guc_listener()` を呼ばない） |
| AP からテナントレジストリを引く（ログイン時の解決など） | `modules/tenancy/providers.py` の `get_tenant_registry()`（`TenantRegistryDep`）。プロセス内シングルトン、TTL 30 秒 |
| CP の DB セッション | `providers.py` の `CpSessionDep`（`get_cp_db_session`、`cp_runtime`） |
| サービス層・ロガー | `get_tenant_context()` / `require_tenant_context()` |
| CP からの集計・削除 | `providers.get_app_cp_agent_engine()` のセッションで `tenant_guc_scope(bind, tenant_id)` または `run_per_tenant(bind, tenant_ids, func)` |
| バッチ・CLI | `tenant_scope(TenantContext(...))` で明示的に設定し、その中で `providers.open_app_session()` を使う（コンテキスト無しでは `TenantContextMissingError`） |
| 独自のリゾルバ・ユーザー依存関数で組み立てる | `modules/tenancy/dependency.py` の `create_registry_tenant_context_dependency(registry_dependency, user_dependency)` / `create_tenant_context_dependency(resolver, user_dependency)` |

- ロール毎のエンジン（`get_cp_registry_reader_engine` / `get_cp_runtime_engine` / `get_app_runtime_engine` / `get_app_cp_agent_engine`）は `providers.py` が環境変数から遅延生成する（import 時に接続しない）。`create_engine` や `DBConnector` を各所で作らない。終了時・テストの後始末は `dispose_providers()`。
- テストでの差し替えは `app.dependency_overrides` に `get_current_app_user`（ユーザー）・`get_tenant_registry`（レジストリ）を渡す。`get_app_tenant_context` ごと差し替える場合は、差し替え先でも `tenant_scope()` でコンテキストを設定する。
- FastAPI の依存関数は async の yield 依存にする（同期の yield 依存では contextvar がエンドポイントに伝わらない）。
- サービス層の関数の引数に `tenant_id` を取らない。コンテキストから得る。

### 4.1 AP のユーザー・組織のサービスを使う

`main_app/services/`（FastAPI 非依存。仕様は 02 §5.1）。いずれも **テナントコンテキスト下の AP セッション**で呼び、コミットはサービスが行う。

| 場面 | 使うもの |
| --- | --- |
| ログイン完了時（コールバック・開発用ログイン） | `user_sync.sync_user_on_login(session, *, tenant_id, idp_subject, email, display_name)`。`tenant_scope(TenantContext(...))` + `open_app_session()` の中で呼ぶ。`tenant_id` はレジストリで検証済みの値（コンテキストと違えば `TenantContextMismatchError`）。`UserDeactivatedError` ならセッションを作らない。デフォルト組織もここで作られる（CP からは作らない。05 #31） |
| AP の各リクエスト（無効化ユーザーの拒否。PF-USR-03） | `user_sync.require_active_session_user(session, idp_subject=user["sub"])`。`UserDeactivatedError` / `UserNotSyncedError` ならセッションを破棄して 401 |
| `/api/v1/users` | `UserService(session)`。Keycloak は既定で `create_tenant_user_admin_client`（各テナントレルムの `tenant-user-admin`。テナントコードからレルム名を導出）。テストでは `kc_admin_factory` に `KeycloakAdminClient(..., http_client=httpx.Client(transport=MockTransport(...)))` を返す関数を渡す |
| `/api/v1/organizations` | `OrganizationService(session)` |
| 例外 → HTTP | `main_app/services/errors.py` の docstring の表。他テナント・存在しない・論理削除済みは同じ 404 |

- 他テナントのリソースは RLS で見えないため「存在しない」と同じ 404 になる。メンバー等の関連付けは事前チェック（テナント内に存在するか）で 422、DB の複合外部キーでも拒否される
- 操作者（監査ログの `actor_id`）はコンテキストの `user_id`（セッションの `sub`）から `t_user.id` を解決する。別の主体として動かす場合は `actor_subject=` を渡す
- 書き込みでは `tenant_id` に必ずコンテキストの値を入れる（RLS の WITH CHECK で他テナントの値は拒否される）
- 実機で確認する場合は使い捨てのユーザー・組織を作り、Keycloak のユーザー（`tenant_users.delete_user_if_exists`）と AP の行を削除する。`t_ap_audit_log` は `app_runtime` から削除できないため、`app_cp_agent` + `tenant_guc_scope` で削除する。デフォルト組織の判定は論理削除済みの行も数えるため、片付けは物理削除で行う

## 5. クロステナントテスト

### 5.1 観点（API・リポジトリを追加/変更したら必ず確認する）

| 観点 | 期待 |
| --- | --- |
| テナント A のユーザーがテナント B のリソースを ID 指定で取得 | 404 |
| テナント A のユーザーがテナント B のリソースを更新・削除 | 404。B のデータが変わっていない |
| 一覧・検索・集計 | B のデータが含まれない（件数も） |
| A のリソースに B のユーザー・組織を関連付け | 422 または 404。DB の複合外部キーでも拒否される |
| リクエストボディ・クエリに B の `tenant_id` を混ぜる | 無視される（A として処理される） |
| コンテキスト無しで `app_runtime` からクエリ | 0 件 |
| 停止中（SUSPENDED）・削除要求中のテナントのセッション | 403 |

### 5.2 テストの層

| 層 | 確認すること | DB |
| --- | --- | --- |
| ユニット | コンテキストの設定・復元、リゾルバの判定、レジストリのキャッシュ | 不要 |
| RLS 結合 | `app_runtime` でテナントを切り替えたときの可視性、WITH CHECK による書き込み拒否、GUC がプールに残らない | 必要（`app_db`） |
| API | 5.1 の観点を 2 テナント分のデータで確認 | 必要 |
| E2E | 開発用ログイン（`alpha-member` / `beta-member`）で画面上の分離を確認 | 必要 |

### 5.3 フィクスチャと実行

フィクスチャとテストの雛形は `fastapi_app/test/tenancy/`（`conftest.py`、RLS 結合テストの例は `test_50_rls_integration.py`）にある。新しいテストはこれを使う。

| フィクスチャ | 内容 |
| --- | --- |
| `tenant_a` / `tenant_b` | 2 テナント分の `TenantContext`（`user_id` 付き） |
| `app_owner_engine` / `app_runtime_engine` / `app_cp_agent_engine` | セッションスコープのエンジン。接続できない・ロールが無い場合は skip（理由にパスワードは出さない） |
| `single_connection_runtime_engine` | `pool_size=1` の `app_runtime`。接続の再利用で GUC が残らないことの検証用 |
| `rls_table_factory(extra_ddl="", apply_rls=True)` | `app_owner` で一時テーブル（UUIDv7 の PK + `tenant_id` + `title`）を作り RLS を適用。終了時に `DROP ... CASCADE` |
| `rls_table` / `seeded_rls_table` | RLS 適用済みの空テーブル / A に 2 行・B に 1 行を投入済み |

- `RlsTable` の補助: `.qualified`（クォート済みの名前）、`.insert(engine, tenant, title)`（GUC を設定してコミット）、`.titles(engine, tenant or None)`
- 新しいテナントスコープのテーブルは `rls_table_factory(extra_ddl="...")` で同等のテーブルを作って検証する（複合外部キーの例: `TestCompositeForeignKey`）
- Session への自動適用は、`sessionmaker(bind=app_runtime_engine)` に `install_tenant_guc_listener` を登録し、`tenant_scope(ctx)` の中でセッションを開始して確認する（後始末は `uninstall_tenant_guc_listener`）
- 全テストに autouse の `_tenant_context_is_clean` が付き、コンテキストの漏れを検知する
- 接続情報: `DB_HOST`, `DB_PORT`, `APP_DB_NAME`, `APP_DB_{OWNER,RUNTIME,CP_AGENT}_{USER,PASSWORD}`

**実行**（コマンド全般は `run-checks` スキル）:

```bash
make d-run SERVICE=fastapi_app CMD="uv run pytest test/tenancy"
```

開発用の `postgres_c` が旧構成の initdb のまま（新ロールが無い）だと結合テストは skip される。DB を初期化せずに結合テストを流す場合は、使い捨てコンテナを使う:

```bash
docker build -t rf_stack_pg_test ./postgres_c
docker run -d --rm --name rf_stack_pg_rlstest --network rf_stack_default \
  -e POSTGRES_PASSWORD=postgres -e APP_DB_NAME=app_db -e CONTROL_PLANE_DB_NAME=control_plane_db \
  -e CP_DB_OWNER_USER=cp_owner -e CP_DB_OWNER_PASSWORD=cp_owner_password \
  -e CP_DB_RUNTIME_USER=cp_runtime -e CP_DB_RUNTIME_PASSWORD=cp_runtime_password \
  -e CP_DB_REGISTRY_READER_USER=cp_registry_reader -e CP_DB_REGISTRY_READER_PASSWORD=cp_registry_reader_password \
  -e APP_DB_OWNER_USER=app_owner -e APP_DB_OWNER_PASSWORD=app_owner_password \
  -e APP_DB_RUNTIME_USER=app_runtime -e APP_DB_RUNTIME_PASSWORD=app_runtime_password \
  -e APP_DB_CP_AGENT_USER=app_cp_agent -e APP_DB_CP_AGENT_PASSWORD=app_cp_agent_password \
  rf_stack_pg_test
# ログに "PostgreSQL init process complete" が出て pg_isready が通るまで待つ
docker compose exec -T -e DB_HOST=rf_stack_pg_rlstest fastapi_app uv run pytest test/tenancy
docker stop rf_stack_pg_rlstest
```
