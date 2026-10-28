# マルチテナント ToDo SaaS（サンプル）要件定義書

> 参考: オライリー『マルチテナントSaaSアーキテクチャの構築』
> ステータス: ドラフト v0.5（共通基盤を `docs/architecture/` に分離し、本書を ToDo 固有の要件に絞った。BFF 認証・プレーン毎の DB 分離・共通規約を反映）

---

## 0. 本書の位置づけ

本書は **ToDo 固有の要件**だけを定める。テナント管理・認証・データ分離・共通機能（ユーザー・組織管理）・共通規約は共通基盤で定義しており、本書はそれを前提とする。

| 文書 | 内容 |
| --- | --- |
| [01 共通基盤仕様](../architecture/01-platform-concepts.md) | プレーン分離、テナント識別・ライフサイクル、認証・認可、データ分離、ユーザー・組織管理 |
| [02 共通基盤の実装方針](../architecture/02-platform-implementation.md) | 本リポジトリの技術スタックでの実現方法 |
| [03 共通規約](../architecture/03-conventions.md) | エラー形式、ページネーション、ID、日時、論理削除、楽観ロック、ログ、監査 |
| [04 システム監視の観点](../architecture/04-observability.md) | 監視の観点（実装は対象外） |
| [05 決定事項](../architecture/05-decisions.md) | 共通基盤の決定事項 |

本書の 1〜8 章は技術非依存、9 章（付録）は本リポジトリでの実装への対応付けである。

### 0.1 テーマを ToDo にする理由

テーマ自体ではなく、今後ほかのテーマの SaaS を作るときの土台となるアーキテクチャと開発環境を固めることに重きを置く。ToDo は「共有」「割り当て」「閲覧範囲」というマルチテナント SaaS で頻出する要素を、ドメインの複雑さを抑えたまま扱えるため題材にしている。

---

## 1. 目的

共通基盤の上で、テナント内で共有・割り当て・閲覧範囲制御ができる ToDo サービスを提供し、共通基盤の各要素（テナント分離、テナントコンテキスト、認可、メトリクス）が実際に機能することを検証する。

---

## 2. スコープ

### 2.1 対象（ToDo 固有）

| 区分 | 内容 |
| --- | --- |
| AP | ToDo の作成・編集・削除・一覧、担当者の割り当て、閲覧範囲の設定、アクティビティ（変更履歴） |
| CP | ToDo に関するメトリクス（件数・ステータス別件数） |

テナント管理、ログイン、ユーザー・組織管理は共通基盤（01）の範囲。

### 2.2 対象外

共通基盤（01 §3.2）に加えて以下。

- ToDo のコメント、添付ファイル、通知、繰り返し ToDo、サブタスク
- 外部カレンダー連携

---

## 3. ロールと認可（ToDo 固有）

基盤のロール（01 §7.5）の上に、以下を追加する。

| 操作 | tenant_admin | member |
| --- | --- | --- |
| ToDo の作成 | ○ | ○ |
| 閲覧可能な ToDo の参照 | ○（全件） | ○（4 章のルールで閲覧可能なもの） |
| 自分が作成した ToDo の編集・削除 | ○ | ○ |
| 他人が作成した ToDo の編集・削除 | ○ | × |
| 担当している ToDo のステータス更新 | ○ | ○ |
| ToDo の担当者の変更 | ○ | ○（自分が作成者または担当者のもの） |
| ToDo の閲覧範囲の変更 | ○ | ○（自分が作成したもの） |
| アクティビティの参照 | ○ | ○（閲覧可能な ToDo のもの） |

- 権限が無い操作は 403。ただし**閲覧できない ToDo は存在自体を明かさず 404**とする（03 §2）

---

## 4. 機能要件

### 4.1 ToDo

| ID | 要件 |
| --- | --- |
| AP-TODO-01 | ユーザーは ToDo を作成できる（タイトル、説明、期限、優先度、ステータス、閲覧範囲、担当者） |
| AP-TODO-02 | ステータスは `open` / `in_progress` / `done`。既定は `open` |
| AP-TODO-03 | 優先度は `low` / `medium` / `high`。既定は `medium` |
| AP-TODO-04 | タイトルは必須で 1〜200 文字、説明は任意で最大 10,000 文字、期限は任意で日付（時刻を持たない） |
| AP-TODO-05 | 作成者は ToDo を編集・削除できる。削除は論理削除とし、削除後は誰も参照できない |
| AP-TODO-06 | ToDo 一覧をステータス・担当者・組織・期限・優先度で絞り込み、期限・優先度・作成日時・更新日時で並び替えできる（ページネーションは 03 §3） |
| AP-TODO-07 | 一覧の表示範囲を切り替えられる: `mine`（自分が作成）、`assigned`（自分が担当）、`shared`（閲覧できるが作成者でも担当者でもない）、`all`（閲覧できるすべて） |
| AP-TODO-08 | 同時編集を検知する。更新時に版が一致しなければ失敗させ、最新を再取得させる（03 §5.2） |

### 4.2 閲覧範囲

| ID | 要件 |
| --- | --- |
| AP-VIS-01 | ToDo は閲覧範囲（visibility）を持つ: `private` / `organization` / `tenant`。既定は `private` |
| AP-VIS-02 | `private`: 作成者と担当者のみ閲覧可能 |
| AP-VIS-03 | `organization`: 指定した 1 つ以上の組織の所属メンバー + 作成者 + 担当者が閲覧可能 |
| AP-VIS-04 | `tenant`: テナント内の全メンバーが閲覧可能 |
| AP-VIS-05 | tenant_admin は閲覧範囲に関わらずテナント内の全 ToDo を閲覧できる |
| AP-VIS-06 | いかなる設定でも**他テナントの ToDo は参照不可**（共通基盤の行レベル分離が最終防衛線） |
| AP-VIS-07 | `organization` を選ぶときは 1 つ以上の組織の指定を必須とする |
| AP-VIS-08 | 指定されていた組織が削除された場合、残りの組織で判定する。指定組織がすべて削除された場合は `private` と同じ扱い（作成者と担当者のみ）とし、編集画面で組織の再指定を促す |
| AP-VIS-09 | 閲覧範囲の判定は、一覧・詳細・アクティビティ・担当者変更のすべての API で同じ判定処理を使う |

### 4.3 割り当て

| ID | 要件 |
| --- | --- |
| AP-ASN-01 | ToDo に同一テナント内のユーザーを担当者として割り当てられる（複数可、最大 20 人） |
| AP-ASN-02 | 他テナントのユーザー、無効化されたユーザーは新たに割り当てられない |
| AP-ASN-03 | 担当者はステータスを更新できる（ステータス以外の項目は編集できない） |
| AP-ASN-04 | 担当者が無効化されても割り当ては残し、画面では「無効」と表示する。作成者・tenant_admin は外せる |
| AP-ASN-05 | 割り当ては担当者の集合を全置換する操作とする（03 §1） |

### 4.4 アクティビティ（変更履歴）

| ID | 要件 |
| --- | --- |
| AP-ACT-01 | 作成、項目の変更、ステータス変更、担当者の変更、閲覧範囲の変更、削除をアクティビティとして記録する |
| AP-ACT-02 | アクティビティは利用者に見せる履歴であり、ToDo を閲覧できる人が参照できる |
| AP-ACT-03 | アクティビティは ToDo の変更と同じトランザクションで記録する |
| AP-ACT-04 | 共通基盤の AP 監査ログ（03 §7）とは別に持つ。監査ログには ToDo の作成・更新・削除・割り当て・閲覧範囲変更を記録する |

---

## 5. データ要件（ToDo 固有）

AP DB に以下を追加する。すべて共通基盤のテナントスコープのテーブル規則（01 §9.3: `tenant_id`、複合外部キー、行レベル分離）に従う。

| テーブル | 主な列 |
| --- | --- |
| ToDo | id, tenant_id, created_by, updated_by, title, description, status, priority, due_date, visibility, version, created_at, updated_at, deleted_at |
| ToDo の公開先組織 | tenant_id, todo_id, organization_id（visibility = `organization` の対象） |
| ToDo の担当者 | tenant_id, todo_id, user_id, assigned_at, assigned_by |
| ToDo アクティビティ | id, tenant_id, todo_id, actor_id, action, payload（変更前後の差分）, created_at |

- 一覧の性能要件（01 §12.2: 1 万件で 500ms）を満たすため、`(tenant_id, status)`、`(tenant_id, due_date)`、`(tenant_id, created_by)`、担当者の `(tenant_id, user_id)` にインデックスを置く
- 論理削除済みの ToDo は既定のクエリから除外する（03 §5.1）

---

## 6. API 要件（ToDo 固有）

共通基盤の API 原則（01 §10、03）に従う。

```
GET    /api/v1/todos?scope=mine|assigned|shared|all&status=&assignee=&organization=&due_before=&due_after=&priority=&sort=&limit=&cursor=
POST   /api/v1/todos
GET    /api/v1/todos/{id}                 → ETag
PATCH  /api/v1/todos/{id}                 If-Match 必須。visibility と organization_ids もここで変更する
DELETE /api/v1/todos/{id}                 If-Match 必須
PUT    /api/v1/todos/{id}/assignees       If-Match 必須。担当者の全置換
GET    /api/v1/todos/{id}/activities
```

- v0.4 の `PUT /todos/{id}/visibility` は `PATCH /todos/{id}` と役割が重なるため廃止した
- 担当者がステータスだけを変更する場合も `PATCH /todos/{id}`（`status` のみ）を使い、サーバーが 3 章の認可で項目を制限する

---

## 7. 共通基盤の拡張点への定義

01 §13 の拡張点に対する ToDo の定義。

| # | 拡張点 | ToDo での定義 |
| --- | --- | --- |
| 1 | ドメインの機能要件 | 4 章 |
| 2 | 閲覧範囲・認可 | 3 章、4.2 |
| 3 | AP DB のテーブル | 5 章 |
| 4 | 払い出し時の初期データ | なし（デフォルト組織は基盤が作成する） |
| 5 | テーマ固有メトリクス | `todo_count`（論理削除を除く総数）、`todo_open_count`、`todo_in_progress_count`、`todo_done_count`。テナント一覧の主要指標は `todo_count` |
| 6 | 監査対象の操作 | 4.4 AP-ACT-04 |
| 7 | 画面 | 8 章 |
| 8 | API | 6 章 |
| 9 | 物理削除の対象 | アクティビティ → 担当者 → 公開先組織 → ToDo の順に削除し、その後に基盤のテーブルを削除する |

- 実装の注記（#5）: 指標の定義は `fastapi_app/src/main_app/repositories/todos/metrics.py` の `TODO_METRICS`（`t_todo` を `deleted_at IS NULL` で絞り、`status` 別に 1 回のクエリで数える）。`modules/tenant_metrics/registry.py` の `THEME_METRIC_SOURCES` に登録し、CP の日次ジョブ `metrics_snapshot` が `t_tenant_daily_metric` に保存する（[02](../architecture/02-platform-implementation.md) §5.5）。主要指標 `todo_count` は `primary_keys` で宣言し、CP のテナント一覧 API（`GET /api/v1/cp/tenants`）の `primary_metrics` に直近の日次メトリクスの値を載せる

---

## 8. 画面（ToDo 固有）

| 画面 | 内容 |
| --- | --- |
| ToDo 一覧 | 表示範囲（mine / assigned / shared / all）の切り替え、絞り込み、並び替え、無限スクロール（カーソル方式） |
| ToDo 詳細・編集 | 項目の編集、担当者の設定、閲覧範囲・公開先組織の設定、アクティビティの表示。同時編集の検知時は最新を再表示する |
| ToDo 作成 | 作成フォーム（閲覧範囲の既定は `private`） |

CP のテナント一覧・詳細には、7 章 #5 のメトリクスを表示する。

---

## 9. 付録: 実装への対応付け（技術依存）

[02 共通基盤の実装方針](../architecture/02-platform-implementation.md) に従う。ToDo 固有の対応は以下。

### 9.1 テーブル

| 論理名 | テーブル | 主キー | 実装上の注記 |
| --- | --- | --- | --- |
| ToDo | `t_todo` | `id`（UUIDv7） | `title` は 1〜200 文字、`description` は最大 10,000 文字を CHECK で強制。既定値は `status = 'open'`、`priority = 'medium'`、`visibility = 'private'`、`version = 1`。`created_by` / `updated_by` は NOT NULL（作成時は `updated_by` = 作成者）。5 章のインデックスは `deleted_at IS NULL` の部分インデックス |
| ToDo の公開先組織 | `t_todo_organization` | `(tenant_id, todo_id, organization_id)` | 組織が論理削除されても行は残し、判定時に除外する（AP-VIS-08）。逆引き用に `(tenant_id, organization_id)` |
| ToDo の担当者 | `t_todo_assignee` | `(tenant_id, todo_id, user_id)` | `assigned_at` / `assigned_by`（NOT NULL）に加えて共通列 `created_at` / `updated_at` を持つ。全置換では残る担当者の行を維持する想定（`assigned_at` を保つ） |
| ToDo アクティビティ | `t_todo_activity` | `id`（UUIDv7） | `actor_id` は NOT NULL。`payload` は `jsonb`（NOT NULL、既定 `{}`）。追記のみのため `updated_at` を持たない。一覧用に `(tenant_id, todo_id, created_at)` |

- `app_db` に作成し、マイグレーションは `alembic/alembic_app.ini`（リビジョン `0002_create_todo_tables`）。モデルは `fastapi_app/src/main_app/models/todo.py`
- 各テーブルのリビジョンで `enable_tenant_rls()` を呼ぶ（`db-migration` スキル）
- 列挙値（`status` / `priority` / `visibility`）は PostgreSQL の enum 型ではなく `text` + CHECK 制約とする（値の追加をマイグレーションで扱いやすくするため）。値の正はモデルの `TodoStatus` / `TodoPriority` / `TodoVisibility`
- アクティビティの `action`（AP-ACT-01）も `text` + CHECK とし、値は `created` / `updated`（項目の変更）/ `status_changed` / `assignees_changed` / `visibility_changed`（閲覧範囲・公開先組織の変更）/ `deleted`（`TodoActivityAction`）。1 回の更新で複数に当たる場合は種別毎に記録する
- 外部キーはすべて `(tenant_id, <列>) → (tenant_id, id)` の複合キー（`created_by` / `updated_by` / `assigned_by` / `user_id` / `actor_id` → `t_user`、`organization_id` → `t_organization`、`todo_id` → `t_todo`）。`ON DELETE` は指定しない
- 担当者の上限（20 人。AP-ASN-01）、無効化ユーザーの新規割り当て禁止（AP-ASN-02）、`organization` の組織 1 つ以上（AP-VIS-07）はアプリ層で検証する（DB では強制しない）
- 物理削除（7 章 #9）は `control_plane_app/repositories/app_tenant_data.py` の `TENANT_DATA_PURGE_TABLES` に登録済み

### 9.2 コード配置

| 層 | 配置 | 担当エージェント |
| --- | --- | --- |
| モデル | `fastapi_app/src/main_app/models/` | `postgres-schema` |
| ルーター・スキーマ | `fastapi_app/src/main_app/route/todos/` | `fastapi-api-schema` |
| サービス（閲覧範囲の判定を含む） | `fastapi_app/src/main_app/services/todos/` | `fastapi-domain` |
| メトリクス集計（CP） | `fastapi_app/src/control_plane_app/repositories/` | `fastapi-domain` |
| 画面 | `react_app/src/main_app/pages/todos/` | `react-ui` |
| フック・API クライアント | `react_app/src/main_app/api/`、`react_app/src/main_app/hooks/` | `react-domain` |
| テスト | pytest（クロステナント・閲覧範囲）、Vitest、Playwright（`alpha-member` / `beta-member` での分離確認） | `fastapi-pytest` / `react-unit-test` / `react-e2e-test` |

### 9.3 開発用データ

- シードテナント `alpha` / `beta` に、閲覧範囲・担当者の組み合わせを網羅した ToDo を投入する
- E2E は開発用ログイン（`/api/auth/dev-login?as=alpha-member` 等）で各ロールの見え方を確認する

---

## 10. 決定事項（ToDo 固有）

共通基盤の決定事項は [05](../architecture/05-decisions.md) を参照。

| # | 論点 | 決定内容 |
| --- | --- | --- |
| 1 | 優先度の値 | `low` / `medium` / `high` |
| 2 | 閲覧範囲の変更 API | `PATCH /todos/{id}` に統合（`PUT /visibility` は廃止） |
| 3 | 組織削除時の閲覧範囲 | 残りの組織で判定し、すべて削除されたら `private` 相当（AP-VIS-08） |
| 4 | 無効化ユーザーの割り当て | 残す。新規割り当ては不可（AP-ASN-02 / 04） |
| 5 | アクティビティと監査ログ | 別に持つ（AP-ACT-04） |
| 6 | 閲覧できない ToDo への応答 | 404 |

## 11. 未決事項

現時点で未決事項はない。
