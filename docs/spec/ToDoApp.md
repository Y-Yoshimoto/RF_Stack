# マルチテナント ToDo SaaS（サンプル）要件定義書

> 参考: オライリー『マルチテナントSaaSアーキテクチャの構築』
> ステータス: ドラフト v0.6（コメント・チェックリスト・カンバン表示・ホームの要約と、使い勝手の要件（AP-UX）を追加）
> v0.5: 共通基盤を `docs/architecture/` に分離し、本書を ToDo 固有の要件に絞った。BFF 認証・プレーン毎の DB 分離・共通規約を反映

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
| AP | ToDo の作成・編集・削除・一覧、担当者の割り当て、閲覧範囲の設定、アクティビティ（変更履歴）、コメント、チェックリスト（1 階層のサブタスク）、カンバン表示、ホームの要約 |
| CP | ToDo に関するメトリクス（件数・ステータス別件数） |

テナント管理、ログイン、ユーザー・組織管理は共通基盤（01）の範囲。

### 2.2 対象外

共通基盤（01 §3.2）に加えて以下。

- 添付ファイル、通知（コメントへの通知を含む）、繰り返し ToDo、外部カレンダー連携
- コメントのメンション・リアクション・返信スレッド・書式（Markdown 等）
- チェックリストの入れ子、項目ごとの担当者・期限
- カンバンの列内の並べ替えの保存、ステータス以外の列（担当者別など）

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
| コメントの参照・投稿 | ○ | ○（閲覧可能な ToDo のもの） |
| 自分のコメントの編集・削除 | ○ | ○ |
| 他人のコメントの編集 | × | × |
| 他人のコメントの削除 | ○ | × |
| チェックリスト項目の追加・名前変更・削除・並べ替え | ○ | ○（自分が作成したもの） |
| チェックリスト項目の完了・未完了の切り替え | ○ | ○（自分が作成者または担当者のもの） |
| ホームの要約の参照 | ○ | ○（閲覧可能なものだけを数える） |

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
| AP-TODO-06 | ToDo 一覧をステータス・担当者・組織・期限・優先度で絞り込み、期限・優先度・作成日時・更新日時で並び替えできる（ページネーションは 03 §3。総件数は要求したときだけ返す） |
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
| AP-ACT-05 | チェックリスト項目の追加・名前変更・削除・完了・未完了もアクティビティとして記録する（並べ替えは記録しない）。コメントは記録しない（AP-CMT-08） |

### 4.5 コメント

| ID | 要件 |
| --- | --- |
| AP-CMT-01 | ToDo を閲覧できるユーザーは誰でもコメントを投稿できる。本文はプレーンテキストで 1〜4,000 文字 |
| AP-CMT-02 | コメントの一覧は古い順で、カーソル方式で取得する（03 §3） |
| AP-CMT-03 | 投稿者は自分のコメントを編集・削除できる。編集したコメントには「編集済み」と表示する |
| AP-CMT-04 | tenant_admin は他人のコメントを削除できる（編集はできない） |
| AP-CMT-05 | コメントの削除は論理削除とし、削除後は一覧に出さない |
| AP-CMT-06 | ToDo が削除された・閲覧範囲外になった場合、そのコメントも参照できない（404） |
| AP-CMT-07 | 投稿者が無効化されたり閲覧範囲から外れたりしてもコメントは残す（画面では「無効」と表示） |
| AP-CMT-08 | コメントはアクティビティに記録しない。監査ログには作成・編集・削除を記録する（本文は残さない） |

### 4.6 チェックリスト

| ID | 要件 |
| --- | --- |
| AP-CHK-01 | ToDo は順序付きのチェックリスト項目を持つ（1 階層。1 件の ToDo につき最大 100 項目） |
| AP-CHK-02 | 項目名は必須で 1〜200 文字 |
| AP-CHK-03 | 項目の追加・名前変更・削除・並べ替えは作成者と tenant_admin ができる |
| AP-CHK-04 | 項目の完了・未完了の切り替えは作成者・担当者・tenant_admin ができる。完了した日時と人を記録する |
| AP-CHK-05 | すべての項目を完了しても ToDo のステータスは自動では変えない |
| AP-CHK-06 | 一覧・カンバン・詳細に進捗（完了数／総数）を表示する |
| AP-CHK-07 | 同時編集を検知する。項目の変更・削除は項目の版、並べ替えはチェックリスト全体の版で判定する（03 §5.2） |
| AP-CHK-08 | チェックリストの変更は ToDo 本体の版・更新日時を変えない（本体の編集と衝突させない） |

### 4.7 カンバン表示

| ID | 要件 |
| --- | --- |
| AP-BRD-01 | ToDo 一覧の画面で、リスト表示とボード（カンバン）表示を切り替えられる。表示方法は URL に持つ |
| AP-BRD-02 | ボードの列はステータス（`open` / `in_progress` / `done`）の 3 列。表示範囲・絞り込み（ステータスを除く）・並び順は一覧と共通 |
| AP-BRD-03 | カードを別の列へ移すとステータスが変わる（権限は 3 章・AP-ASN-03）。ステータスを変更できないカードは移動できない |
| AP-BRD-04 | マウス・タッチ・キーボードのいずれでも移動でき、ドラッグ以外の手段（カードのメニュー）でも変更できる |
| AP-BRD-05 | 列ごとに総件数を表示し、続きを読み込める |
| AP-BRD-06 | 列内の並びは並び順の指定に従う。列内での手動の並べ替えは保存しない |

### 4.8 使い勝手

| ID | 要件 |
| --- | --- |
| AP-UX-01 | ホームに ToDo の要約を表示する: 自分が担当の未完了・期限切れ・期限間近（7 日以内）の件数、自分が作成した未完了の件数、期限の近い担当 ToDo（上位 5 件）。各件数から絞り込み済みの一覧へ移れる |
| AP-UX-02 | 一覧は無限スクロールで読み込み、総件数を表示する（「さらに読み込む」の操作も残す） |
| AP-UX-03 | 一覧に作成者・更新日時・チェックリストの進捗・コメント数を表示する |
| AP-UX-04 | 狭い画面ではカード形式で表示する |
| AP-UX-05 | 絞り込みは折りたためるようにし、適用中の条件を一覧の上に表示して個別に外せる |
| AP-UX-06 | 一覧が空のときは、表示範囲に応じた案内と作成への導線を表示する |
| AP-UX-07 | 詳細の編集中に同時編集を検知したら、最新の内容を自動で再表示する。未保存の入力は残し、他の人の変更と重なる項目を知らせる |
| AP-UX-08 | 詳細の 1 つのフォームを保存しても、他のフォームの未保存の入力は失わない |
| AP-UX-09 | 詳細に作成者・作成日時・最終更新者・更新日時を表示する |

---

## 5. データ要件（ToDo 固有）

AP DB に以下を追加する。すべて共通基盤のテナントスコープのテーブル規則（01 §9.3: `tenant_id`、複合外部キー、行レベル分離）に従う。

| テーブル | 主な列 |
| --- | --- |
| ToDo | id, tenant_id, created_by, updated_by, title, description, status, priority, due_date, visibility, version, checklist_version, created_at, updated_at, deleted_at |
| ToDo の公開先組織 | tenant_id, todo_id, organization_id（visibility = `organization` の対象） |
| ToDo の担当者 | tenant_id, todo_id, user_id, assigned_at, assigned_by |
| ToDo アクティビティ | id, tenant_id, todo_id, actor_id, action, payload（変更前後の差分）, created_at |
| ToDo のコメント | id, tenant_id, todo_id, author_id, body, version, edited_at, created_at, updated_at, deleted_at |
| ToDo のチェックリスト項目 | id, tenant_id, todo_id, title, position, is_done, done_at, done_by, created_by, updated_by, version, created_at, updated_at |

- `checklist_version` はチェックリスト全体の版（項目の追加・削除・並べ替えで上がる。AP-CHK-07）。ToDo 本体の `version` とは別に持つ（AP-CHK-08）
- コメントは論理削除（AP-CMT-05）、チェックリスト項目は物理削除（履歴はアクティビティに残る）
- コメントの一覧用に `(tenant_id, todo_id, created_at, id)`（削除済みを除く）、チェックリストに `(tenant_id, todo_id, position)` の一意制約を置く
- 一覧の性能要件（01 §12.2: 1 万件で 500ms）を満たすため、`(tenant_id, status)`、`(tenant_id, due_date)`、`(tenant_id, created_by)`、担当者の `(tenant_id, user_id)` にインデックスを置く
- 論理削除済みの ToDo は既定のクエリから除外する（03 §5.1）

---

## 6. API 要件（ToDo 固有）

共通基盤の API 原則（01 §10、03）に従う。

```
GET    /api/v1/todos?scope=mine|assigned|shared|all&status=&assignee_id=&organization_id=&due_before=&due_after=&priority=&q=&sort=&limit=&cursor=&include_total=
GET    /api/v1/todos/summary?today=&due_soon_days=        ホームの要約（件数）
POST   /api/v1/todos
GET    /api/v1/todos/{id}                 → ETag
PATCH  /api/v1/todos/{id}                 If-Match 必須。visibility と organization_ids もここで変更する
DELETE /api/v1/todos/{id}                 If-Match 必須
PUT    /api/v1/todos/{id}/assignees       If-Match 必須。担当者の全置換
GET    /api/v1/todos/{id}/activities
GET    /api/v1/todos/{id}/comments?limit=&cursor=
POST   /api/v1/todos/{id}/comments
PATCH  /api/v1/todos/{id}/comments/{comment_id}        If-Match 必須（コメントの版）
DELETE /api/v1/todos/{id}/comments/{comment_id}        If-Match 必須（コメントの版）
GET    /api/v1/todos/{id}/checklist                    → ETag（チェックリストの版）
POST   /api/v1/todos/{id}/checklist/items
PATCH  /api/v1/todos/{id}/checklist/items/{item_id}    If-Match 必須（項目の版）
DELETE /api/v1/todos/{id}/checklist/items/{item_id}    If-Match 必須（項目の版）
PUT    /api/v1/todos/{id}/checklist/order              If-Match 必須（チェックリストの版）。項目 ID の並びの全置換
```

- v0.4 の `PUT /todos/{id}/visibility` は `PATCH /todos/{id}` と役割が重なるため廃止した
- 担当者がステータスだけを変更する場合も `PATCH /todos/{id}`（`status` のみ）を使い、サーバーが 3 章の認可で項目を制限する。カンバンの移動も同じ API を使う
- コメント・チェックリストの変更は ToDo 本体の `ETag` を変えない（AP-CHK-08。#16）
- ホームの要約の「今日」はクライアントのローカル日付を `today` で受け取る（#21）

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
| 9 | 物理削除の対象 | コメント → チェックリスト項目 → アクティビティ → 担当者 → 公開先組織 → ToDo の順に削除し、その後に基盤のテーブルを削除する |

- メトリクス（#5）にコメント数・チェックリストの件数は加えない（必要になれば `TODO_METRICS` に指標を足す）

- 実装の注記（#5）: 指標の定義は `fastapi_app/src/main_app/repositories/todos/metrics.py` の `TODO_METRICS`（`t_todo` を `deleted_at IS NULL` で絞り、`status` 別に 1 回のクエリで数える）。`modules/tenant_metrics/registry.py` の `THEME_METRIC_SOURCES` に登録し、CP の日次ジョブ `metrics_snapshot` が `t_tenant_daily_metric` に保存する（[02](../architecture/02-platform-implementation.md) §5.5）。主要指標 `todo_count` は `primary_keys` で宣言し、CP のテナント一覧 API（`GET /api/v1/cp/tenants`）の `primary_metrics` に直近の日次メトリクスの値を載せる

---

## 8. 画面（ToDo 固有）

| 画面 | 内容 |
| --- | --- |
| ホーム（AP 共通画面の一部） | ToDo の要約（AP-UX-01） |
| ToDo 一覧 | 表示範囲（mine / assigned / shared / all）の切り替え、リスト／ボードの切り替え（AP-BRD）、折りたたみ式の絞り込みと適用中の条件の表示、並び替え、無限スクロール（カーソル方式）と総件数、狭い画面ではカード表示、空の状態の案内 |
| ToDo 詳細・編集 | 作成者・日時の表示、項目の編集、チェックリスト、担当者の設定、閲覧範囲・公開先組織の設定、コメント、アクティビティの表示。同時編集の検知時は最新を再表示し、未保存の入力は残す |
| ToDo 作成 | 作成フォーム（閲覧範囲の既定は `private`） |

- AP のナビゲーションでは ToDo をホームの次に置く

CP のテナント一覧・詳細には、7 章 #5 のメトリクスを表示する。

---

## 9. 付録: 実装への対応付け（技術依存）

[02 共通基盤の実装方針](../architecture/02-platform-implementation.md) に従う。ToDo 固有の対応は以下。

### 9.1 テーブル

| 論理名 | テーブル | 主キー | 実装上の注記 |
| --- | --- | --- | --- |
| ToDo | `t_todo` | `id`（UUIDv7） | `title` は 1〜200 文字、`description` は最大 10,000 文字を CHECK で強制。既定値は `status = 'open'`、`priority = 'medium'`、`visibility = 'private'`、`version = 1`、`checklist_version = 1`（チェックリスト全体の楽観ロック用の版。`>= 1` の CHECK。ToDo 本体の `version` とは別。AP-CHK-07 / 08）。`created_by` / `updated_by` は NOT NULL（作成時は `updated_by` = 作成者）。5 章のインデックスは `deleted_at IS NULL` の部分インデックス |
| ToDo の公開先組織 | `t_todo_organization` | `(tenant_id, todo_id, organization_id)` | 組織が論理削除されても行は残し、判定時に除外する（AP-VIS-08）。逆引き用に `(tenant_id, organization_id)` |
| ToDo の担当者 | `t_todo_assignee` | `(tenant_id, todo_id, user_id)` | `assigned_at` / `assigned_by`（NOT NULL）に加えて共通列 `created_at` / `updated_at` を持つ。全置換では残る担当者の行を維持する（`assigned_at` / `assigned_by` を保つ。9.3） |
| ToDo アクティビティ | `t_todo_activity` | `id`（UUIDv7） | `actor_id` は NOT NULL。`payload` は `jsonb`（NOT NULL、既定 `{}`）。追記のみのため `updated_at` を持たない。一覧用に `(tenant_id, todo_id, created_at)` |
| ToDo のコメント | `t_todo_comment` | `id`（UUIDv7） | 本文 `body` は 1〜4,000 文字の CHECK。論理削除（`deleted_at`）・楽観ロック（`version`）。`edited_at`（NULL 可）は編集時に設定し「編集済み」の表示に使う。`author_id` は NOT NULL。一覧用に `(tenant_id, todo_id, created_at, id)` の部分インデックス（`deleted_at IS NULL`）。リビジョン `0004` |
| ToDo のチェックリスト項目 | `t_todo_checklist_item` | `id`（UUIDv7） | `title` は 1〜200 文字、`position` は 0 以上の CHECK。`UNIQUE (tenant_id, todo_id, position)` は `DEFERRABLE INITIALLY DEFERRED`（1 トランザクションで入れ替え・詰め直しができる）。`is_done`（NOT NULL、既定 false）・`done_at` / `done_by`（NULL 可）は完了の整合性の CHECK（`is_done` なら `done_at` / `done_by` が NOT NULL、そうでなければ両方 NULL）。`created_by` / `updated_by` は NOT NULL。楽観ロックの `version`。物理削除（`deleted_at` なし）。リビジョン `0004` |

- `app_db` に作成し、マイグレーションは `alembic/alembic_app.ini`（リビジョン `0002_create_todo_tables`）。モデルは `fastapi_app/src/main_app/models/todo.py`
- 各テーブルのリビジョンで `enable_tenant_rls()` を呼ぶ（`db-migration` スキル）
- 列挙値（`status` / `priority` / `visibility`）は PostgreSQL の enum 型ではなく `text` + CHECK 制約とする（値の追加をマイグレーションで扱いやすくするため）。値の正はモデルの `TodoStatus` / `TodoPriority` / `TodoVisibility`
- アクティビティの `action`（AP-ACT-01）も `text` + CHECK とし、値は `created` / `updated`（項目の変更）/ `status_changed` / `assignees_changed` / `visibility_changed`（閲覧範囲・公開先組織の変更）/ `deleted` / `checklist_changed`（チェックリスト項目の変更。リビジョン `0004` で追加）（`TodoActivityAction`）。1 回の更新で複数に当たる場合は種別毎に記録する
- 外部キーはすべて `(tenant_id, <列>) → (tenant_id, id)` の複合キー（`created_by` / `updated_by` / `assigned_by` / `user_id` / `actor_id` → `t_user`、`organization_id` → `t_organization`、`todo_id` → `t_todo`）。`ON DELETE` は指定しない
- コメント・チェックリストのリビジョンは `0004_add_todo_comments_and_checklist`。コメント本文の長さ・項目名の長さ・項目数の上限（100。AP-CHK-01）の定数は `todo.py`（`TODO_COMMENT_BODY_MAX_LENGTH` / `TODO_CHECKLIST_ITEM_TITLE_MAX_LENGTH` / `TODO_CHECKLIST_ITEMS_MAX`）。項目数の上限と `position` が 0 からの連番であることはアプリ層で保つ（DB では強制しない）
- 担当者の上限（20 人。AP-ASN-01）、無効化ユーザーの新規割り当て禁止（AP-ASN-02）、`organization` の組織 1 つ以上（AP-VIS-07）はアプリ層で検証する（DB では強制しない）
- 物理削除（7 章 #9）は `control_plane_app/repositories/app_tenant_data.py` の `TENANT_DATA_PURGE_TABLES` に登録済み（`t_todo_comment` → `t_todo_checklist_item` → `t_todo_activity` → …）。E2E の後片付け（`dev_tools/e2e_cleanup.py`）も同じ順で対象の ToDo のコメント・項目を消す

### 9.2 コード配置

| 層 | 配置 | 担当エージェント |
| --- | --- | --- |
| モデル | `fastapi_app/src/main_app/models/` | `postgres-schema` |
| ルーター・スキーマ | `fastapi_app/src/main_app/route/v1/api_todos/`（`router.py`、`schemas.py`。9.5） | `fastapi-api-schema` |
| サービス（閲覧範囲の判定を含む） | `fastapi_app/src/main_app/services/todo_service.py`、`todo_comment_service.py`、`todo_checklist_service.py`、`todo_access.py`、`todo_policy.py`、`todo_views.py`（9.3） | `fastapi-domain` |
| DB アクセス | `fastapi_app/src/main_app/repositories/todos/`（`todos.py`、`activities.py`、`comments.py`、`checklist.py`、`metrics.py`） | `fastapi-domain` |
| 開発用シード | `fastapi_app/src/dev_tools/seed_todos.py`（9.4） | `fastapi-domain` |
| メトリクス集計（CP） | `fastapi_app/src/control_plane_app/repositories/` | `fastapi-domain` |
| 画面 | `react_app/src/main_app/pages/`（`TodoList`、`TodoCreate`、`TodoDetail`、共通部品 `TodoCommon`） | `react-ui` |
| フック・API クライアント | `react_app/src/main_app/api/`（`todo_contract.ts`、`todos.ts`）、`react_app/src/main_app/todos/` | `react-domain` |
| テスト | pytest（クロステナント・閲覧範囲）、Vitest、Playwright（`alpha-member` / `beta-member` での分離確認） | `fastapi-pytest` / `react-unit-test` / `react-e2e-test` |

### 9.3 サービス層

FastAPI 非依存。テナントコンテキスト下の AP セッション（`AppSessionDep` / `open_app_session()`）で呼び、コミットはサービスが行う（共通基盤の `UserService` / `OrganizationService` と同じ作り。[02](../architecture/02-platform-implementation.md) §5.1）。

| モジュール | 内容 |
| --- | --- |
| `main_app/services/todo_service.py` | `TodoService(session, *, actor_user_id, actor_roles)`。`actor_user_id` は `t_user.id`（IdP の `sub` ではない）、`actor_roles` はセッションのロール。`list_todos`（`include_total=False`。戻り値は `TodoListPage` = `Page[TodoView]` + `total`。総件数は表示範囲・絞り込みを適用し、カーソルに依存しない SQL 1 本）/ `summarize(*, today=None, due_soon_days=7)`（ホームの要約 `TodoSummaryView`。下記）/ `get_todo` / `create_todo` / `update_todo`（PATCH。`UNSET` で未指定。閲覧範囲・公開先組織の変更を含む）/ `delete_todo`（論理削除）/ `set_assignees`（全置換）/ `list_activities`（戻り値は `TodoActivityPage`。下記「アクティビティと監査ログ」） |
| `main_app/services/todo_comment_service.py` | `TodoCommentService(session, *, actor_user_id, actor_roles)`。`list_comments(todo_id, *, limit=50, after=None)`（`Page[TodoCommentView]`。古い順、削除済みを除く。投稿者は結合して 1 クエリ）/ `create_comment(todo_id, *, body)` / `update_comment(todo_id, comment_id, *, expected_version, body)`（同じ本文なら何もせず版も変えない。変えたら `edited_at`）/ `delete_comment(todo_id, comment_id, *, expected_version)`（論理削除）。本文は前後の空白を除いて 1〜4,000 文字 |
| `main_app/services/todo_checklist_service.py` | `TodoChecklistService(session, *, actor_user_id, actor_roles)`。`get_checklist(todo_id)` / `add_item(todo_id, *, title, position=None)` / `update_item(todo_id, item_id, *, expected_version, title=UNSET, is_done=UNSET)` / `delete_item(todo_id, item_id, *, expected_version)` / `reorder_items(todo_id, *, expected_version, item_ids)`。戻り値はすべてチェックリスト全体の `TodoChecklistView`（`version` = `checklist_version`）。変更系は `t_todo` を `FOR UPDATE` で直列化する |
| `main_app/services/todo_access.py` | 3 つのサービスで共有する部品。`actor_of(user_id, roles) -> TodoActor`（テナントはコンテキスト）、`require_visible_todo(session, actor, todo_id, *, for_update=False) -> TTodo`（閲覧範囲外は `TodoNotFoundError`）、アクティビティ・監査ログの記録、入力の補助 |
| `main_app/services/todo_policy.py` | 閲覧範囲（AP-VIS）の SQL 条件 `visible_condition`、表示範囲 `scope_condition`、操作の権限 `todo_permissions`（3 章）とコメントごとの権限 `comment_permissions(actor, *, author_id)`。**判定はここだけ**で、一覧のクエリと単体の取得（詳細・更新・削除・担当者の変更・アクティビティ・コメント・チェックリスト）が同じ条件を `WHERE` に付ける（AP-VIS-09） |
| `main_app/services/todo_views.py` | `TodoView`（一覧。説明を除く。`creator` / `updater`（`UserNameView`）、`checklist`（`TodoChecklistProgressView`: `done_count` / `total_count`）、`comment_count` を含む）/ `TodoListPage` / `TodoDetailView`（詳細。説明と操作者の権限 `permissions`）/ `TodoActivityView` / `TodoActivityPage`（`Page[TodoActivityView]` + `users`）/ `TodoCommentView`（`author`、`edited_at`、コメントごとの `permissions`: `can_edit` / `can_delete`）/ `TodoChecklistItemView`（`done_by` は `UserNameView`）/ `TodoChecklistView`（`permissions`: `can_edit` / `can_check`）/ `TodoSummaryView` |
| `main_app/services/errors.py` | 例外と `code`・HTTP の対応（下表） |
| `main_app/repositories/todos/todos.py` / `activities.py` / `comments.py` / `checklist.py` | DB アクセス。一覧の担当者・公開先組織・件数（`load_todo_counters`: チェックリストの進捗とコメント数）・作成者と更新者の表示名は ToDo の ID でまとめて取得する（1 ページあたり 5 クエリ。`include_total` で総件数 `count_todos` の 1 クエリが加わる。N+1 にしない）。要約は `summary_counts`（`count(*) FILTER` の SQL 1 本） |

**閲覧範囲**（`visible_condition`。論理削除済みは誰も閲覧できない）: `tenant_admin`、または 作成者 / 担当者 / `visibility = 'tenant'` / `visibility = 'organization'` かつ公開先の**有効な**組織に所属。削除された組織は判定から除外するため、すべて削除されると `private` と同じになる（AP-VIS-08）。副問い合わせは相関させず `id IN (...)` にし、`tenant_id` と `deleted_at IS NULL` を明示して 5 章のインデックス（部分インデックス）を使える形にする。他テナントの行は RLS で見えない。

**操作の権限**（`todo_permissions`。閲覧できる ToDo に対して判定）:

| 操作 | `tenant_admin` | 作成者 | 担当者 |
| --- | --- | --- | --- |
| 項目（タイトル・説明・期限・優先度）の変更 / 削除 / 閲覧範囲・公開先組織の変更 | ○ | ○ | × |
| ステータスの変更 / 担当者の変更 | ○ | ○ | ○ |
| コメントの参照・投稿（`can_comment`。閲覧できれば誰でも） | ○ | ○ | ○ |
| チェックリスト項目の追加・名前変更・削除・並べ替え（`can_edit_checklist`） | ○ | ○ | × |
| チェックリスト項目の完了・未完了の切り替え（`can_check_checklist`） | ○ | ○ | ○ |

コメントごとの権限（`comment_permissions`）: 編集（`can_edit`）は投稿者のみ（`tenant_admin` も他人のコメントは編集できない）、削除（`can_delete`）は投稿者と `tenant_admin`。

**変更系の判定の順序**（コメント・チェックリスト。#8 と同じ考え方）: 入力の形式（422）→ ToDo の閲覧範囲（404 `todo_not_found`）→ コメント・項目（404。別の ToDo のもの・削除済み・他テナントを区別しない）→ 版（412）→ 権限（403）→ 現在の状態に依存する検証（422。項目数の上限 `items` / `too_many`、並べ替えの集合の不一致 `item_ids` / `mismatch`）。チェックリスト項目の更新は**実際に変わる項目**で権限を判定する（#18）。コメントの編集は、同じ本文でも投稿者以外は 403（権限を先に確認する）。チェックリストの追加の `position` は省略・末尾より後なら末尾。

**ホームの要約**（`summarize`。#21）: 閲覧できる ToDo のうち論理削除・完了（`done`）を除いて数える。`assigned`（自分が担当）の `open` / `in_progress` / `overdue`（`due_date < today`）/ `due_soon`（`today <= due_date <= today + due_soon_days`）、`created`（自分が作成）の `open` / `in_progress` / `overdue`。`today` は日付（省略時は UTC の日付。`datetime` は 422）、`due_soon_days` は 1〜30（範囲外は `due_soon_days` / `out_of_range`）。

**一覧**: `scope`（`mine` / `assigned` / `shared` / `all`。いずれも閲覧できるものに限る）、絞り込み `status` / `priority`（複数可）/ `assignee_id` / `organization_id` / `due_before` / `due_after` / `q`（タイトルの部分一致）、`sort`（`due_date` / `priority` / `created_at` / `updated_at`、先頭 `-` で降順。既定 `-created_at`）。キーセット方式で、`next_after` は `(並び替えキーの値, id)`（`due_date` は `date | None`、`priority` は値の文字列、日時は `datetime`）。カーソル文字列への変換は API 層。

**例外**（`main_app/services/errors.py`）:

| 例外 | `code` | HTTP |
| --- | --- | --- |
| `TodoValidationError` | `invalid_todo_input` | 422（`field` / `reason`） |
| `InvalidTodoAssigneesError` | `invalid_todo_assignees` | 422（`user_ids`、`reason` は `not_found` / `inactive`） |
| `InvalidTodoOrganizationsError` | `invalid_todo_organizations` | 422（`organization_ids`） |
| `TodoNotFoundError` | `todo_not_found` | 404（他テナント・存在しない・論理削除済み・閲覧範囲外を区別しない） |
| `TodoCommentNotFoundError` | `todo_comment_not_found` | 404（別の ToDo のコメント・論理削除済み・他テナントを区別しない。ToDo が閲覧できなければ先に `todo_not_found`） |
| `TodoChecklistItemNotFoundError` | `todo_checklist_item_not_found` | 404（別の ToDo の項目・削除済み・他テナントを区別しない。ToDo が閲覧できなければ先に `todo_not_found`） |
| `TodoPermissionDeniedError` | `todo_operation_forbidden` | 403（`operation`: `edit_fields` / `change_status` / `change_visibility` / `change_assignees` / `delete` / `edit_checklist` / `check_checklist_item` / `edit_comment` / `delete_comment`） |
| `TodoVersionConflictError` | `todo_version_conflict` | 412 |
| `TodoCommentVersionConflictError` | `todo_comment_version_conflict` | 412（コメントの版） |
| `TodoChecklistVersionConflictError` | `todo_checklist_version_conflict` | 412（`target`: `item` = 項目の版 / `checklist` = `checklist_version`） |

**アクティビティと監査ログ**（AP-ACT）: 変更と同じトランザクションで、アクティビティは種別ごとに 1 行（例: 1 回の PATCH で項目・ステータス・閲覧範囲を変えると `updated` / `status_changed` / `visibility_changed` の 3 行）。値が変わらない更新は何も記録せず `version` も変えない。監査ログの `action` は `todo.create` / `todo.update`（項目・ステータス）/ `todo.change_visibility` / `todo.set_assignees` / `todo.delete`（`target_type = 'todo'`。説明の本文は残さず変更の有無だけ）。`payload` の形は `TodoActivityView` の docstring。

- **チェックリスト**（AP-ACT-05、#20）: アクティビティ `checklist_changed` を操作ごとに 1 行（`payload` は `op`（`added` / `renamed` / `removed` / `checked` / `unchecked`）・`item_id`・`title`、`renamed` は `before` / `after`。名前と完了を 1 回で変えれば 2 行）。並べ替えは記録しない。監査ログは `todo.checklist_change`（`payload` は `ops`（並べ替えは `reordered`）・`item_id`・版の前後）
- **コメント**（AP-CMT-08）: アクティビティには記録しない。監査ログ `todo.comment_create` / `todo.comment_update` / `todo.comment_delete`（`target_type = 'todo'`、`target_id` は ToDo ID。`payload` はコメント ID・本文の長さ・版。**本文は残さない**）
- コメント・チェックリストの変更は ToDo 本体の `version` / `updated_at` / `updated_by` を変えない（#16。`checklist_version` の更新でも `updated_at` の自動更新を打ち消す）

**アクティビティの参照先ユーザー**（AP-ACT-02）: `list_activities` は `Page` の `items` / `next_after` に加えて `users: Mapping[UUID, UserNameView]`（`id` / `display_name` / `is_active`）を返す。対象はページ内の操作者（`actor_id`）と `payload` が参照するユーザー（`created` の `values.assignee_ids`、`assignees_changed` の `added` / `removed`）で、1 回のクエリで取得する。担当者から外れたユーザー・無効化されたユーザーも含み、テナント内に存在しない ID（他テナントの ID を含む）は含めない（RLS に加えて `tenant_id` を明示）。`TodoActivityView.actor_display_name` も同じ対応から埋める。

### 9.4 開発用データ

- シードテナント `alpha` / `beta` に、閲覧範囲・担当者の組み合わせを網羅した ToDo を投入する（v0.6 で実装。`python -m dev_tools.seed_todos`。テナントとユーザーのシード `python -m control_plane_app.seed` の後に実行する）
  - CP は AP に書き込まないため（05 #31）、両プレーンを参照できる `src/dev_tools/` に置く。ToDo・チェックリスト・コメントはサービス経由で作り、アクティビティと監査ログも正しく残す
  - 網羅する組み合わせ: 閲覧範囲（`private` / `organization`（有効な組織）/ `organization`（公開先がすべて削除済み）/ `tenant`）× 作成者（admin / member / member2）× 担当者（なし・1 人・2 人）、ステータス 3 種、期限（期限切れ・今日・数日後・期限なし）、チェックリスト（なし・一部完了・全完了）、コメントの有無
  - タイトルは `[Seed] ` で始め、同じタイトルがあれば作らない（冪等）。E2E の後片付け（`E2E ToDo ` で始まるもの）の対象にならない
  - 実装の注記: `APP_ENV=development` が明示されていなければ何もしない（`control_plane_app.seed.require_explicit_development`）。台帳で `ACTIVE` なテナントだけを対象にし、Keycloak から `DEV_TENANT_USERS` の `sub`・姓・名・実効ロールを引いて `sync_user_on_login` で `t_user` とデフォルト組織を確保する（`last_login_at` も更新される）。組織は `[Seed] 企画部`（member が所属）と `[Seed] 旧プロジェクト`（member2 が所属。ToDo を作った後に論理削除）で、名前（論理削除済みを含む）で冪等。件数は alpha 20 件・beta 6 件（定義は `SEED_TODOS`）
- E2E は開発用ログイン（`/api/auth/dev-login?as=alpha-member` 等）で各ロールの見え方を確認する

### 9.5 API（ルーター・スキーマ）

`main_app/route/v1/api_todos/`（`router.py`、`schemas.py`、コメントは `comments.py` / `comment_schemas.py`、チェックリストは `checklist.py` / `checklist_schemas.py`。`router.py` が include する）。`main_app/route/v1/apiapp.py` が `/todos` で束ね、既存の `/api/v1` の依存（テナントコンテキスト → CSRF → `require_active_app_user`）が掛かる。ロールは `tenant_admin` / `member` のどちらも可で、ToDo ごとの閲覧範囲（404）と操作の権限（403）は `TodoService` が判定する。ルーターは `deps.py` の `TodoServiceDep` / `TodoCommentServiceDep` / `TodoChecklistServiceDep`（`<サービス>(session, actor_user_id=ActiveAppUser.id, actor_roles=セッションの roles)`）を呼ぶだけで、ロジックを持たない。

| メソッド | パス | 成功 | サービス | 主なエラー |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/todos` | 200 `TodoPage`（説明なし。要素に `creator` / `updater` / `checklist` / `comment_count`。`total` は `include_total=true` のときだけ総件数、省略時は `null`） | `list_todos` | 422 |
| GET | `/api/v1/todos/summary` | 200 `TodoSummaryRead`（`today` / `due_soon_until` / `assigned` / `created`）。`today` は `YYYY-MM-DD`（省略時は UTC の日付）、`due_soon_days` は 1〜30（既定 7） | `summarize` | 422 |
| POST | `/api/v1/todos` | 201 `TodoDetail`、`Location`、`ETag` | `create_todo` | 422 |
| GET | `/api/v1/todos/{id}` | 200 `TodoDetail`（説明・`permissions`）、`ETag` | `get_todo` | 404 |
| PATCH | `/api/v1/todos/{id}` | 200 `TodoDetail`、新しい `ETag` | `update_todo` | 403 / 404 / 412 / 422 / 428 |
| DELETE | `/api/v1/todos/{id}` | 204（論理削除。本文なし） | `delete_todo` | 403 / 404 / 412 / 428 |
| PUT | `/api/v1/todos/{id}/assignees` | 200 `TodoDetail`、新しい `ETag` | `set_assignees` | 403 / 404 / 412 / 422 / 428 |
| GET | `/api/v1/todos/{id}/activities` | 200 `TodoActivityPage`（新しい順）。`{items, next_cursor, users}`。`users` は `{<user_id>: {display_name, is_active}}`（ユーザー ID をキーにしたオブジェクト。操作者と `payload` が参照するユーザー。キーが無い ID は「不明なユーザー」と表示する） | `list_activities` | 404 / 422 |
| GET | `/api/v1/todos/{id}/comments` | 200 `TodoCommentPage`（古い順。カーソル方式。各要素に `permissions` = `can_edit` / `can_delete`） | `TodoCommentService.list_comments` | 404 / 422 |
| POST | `/api/v1/todos/{id}/comments` | 201 `TodoCommentRead`、`Location`、`ETag`（コメントの版） | `create_comment` | 404 / 422 |
| PATCH | `/api/v1/todos/{id}/comments/{cid}` | 200 `TodoCommentRead`、新しい `ETag`。`If-Match` はコメントの版 | `update_comment` | 403 / 404 / 412 / 422 / 428 |
| DELETE | `/api/v1/todos/{id}/comments/{cid}` | 204（論理削除。本文なし）。`If-Match` はコメントの版 | `delete_comment` | 403 / 404 / 412 / 428 |
| GET | `/api/v1/todos/{id}/checklist` | 200 `TodoChecklistRead`、`ETag`（チェックリスト全体の版） | `TodoChecklistService.get_checklist` | 404 |
| POST | `/api/v1/todos/{id}/checklist/items` | 201 `TodoChecklistRead`（全体）、新しい `ETag`。`If-Match` 不要 | `add_item` | 403 / 404 / 422 |
| PATCH | `/api/v1/todos/{id}/checklist/items/{iid}` | 200 `TodoChecklistRead`（全体）、`ETag`（チェックリストの版）。`If-Match` は項目の版 | `update_item` | 403 / 404 / 412 / 422 / 428 |
| DELETE | `/api/v1/todos/{id}/checklist/items/{iid}` | 200 `TodoChecklistRead`（全体）、新しい `ETag`。`If-Match` は項目の版 | `delete_item` | 403 / 404 / 412 / 428 |
| PUT | `/api/v1/todos/{id}/checklist/order` | 200 `TodoChecklistRead`（全体）、新しい `ETag`。`If-Match` はチェックリスト全体の版 | `reorder_items` | 403 / 404 / 412 / 422 / 428 |

- **クエリ**: 6 章のとおり。絞り込みの名前はサービスの引数に合わせ `assignee_id` / `organization_id`。`status` / `priority` の複数値は 03 §3 のカンマ区切り（`status=open,in_progress`）。`sort` は**キー 1 つ**（`due_date` / `priority` / `created_at` / `updated_at`、先頭 `-` で降順。既定 `-created_at`）で、複数キー（`due_date,-priority`）は未対応（#11）のため 422。OpenAPI の `sort` の説明にも書く
- **カーソル**: `route/v1/paging.py`（`(キー, id)` を base64url の JSON にする。`due_date` は `YYYY-MM-DD` または `null`、`priority` は文字列、`created_at` / `updated_at` は ISO 8601）。`sort` の違うカーソルや壊れたカーソルは 422（`validation_error` の `errors[].code = invalid_cursor`）。アクティビティは `-created_at` 固定
- **コメント・チェックリストの変更系**: ToDo 本体の `ETag` は変えない（#16）。チェックリストの変更系はすべて全体（`TodoChecklistRead`）を返し、`ETag` はチェックリスト全体の版（項目の版は各項目の `version`）。`POST /comments` の `Location` は `/api/v1/todos/{id}/comments/{cid}`（単体取得の API は無い）
- **PATCH**: 送った項目だけ更新する（`model_fields_set` → `UNSET`）。`description` / `due_date` の `null` は値を消し、`title` / `priority` / `status` / `visibility` / `organization_ids` の `null` は 422
- **エラーの変換**（`main_app/problems.py`）: `invalid_todo_input` 422（`errors` に `{field, code, message}`）/ `invalid_todo_assignees` 422（拡張メンバー `user_ids`。`errors[].code` は `not_found` / `inactive`）/ `invalid_todo_organizations` 422（拡張メンバー `organization_ids`）/ `todo_not_found` 404 / `todo_operation_forbidden` 403（拡張メンバー `operation`）/ `todo_version_conflict` 412 / `todo_comment_not_found` 404 / `todo_checklist_item_not_found` 404 / `todo_comment_version_conflict` 412 / `todo_checklist_version_conflict` 412（拡張メンバー `target` = `item` | `checklist`）。`todo_operation_forbidden` の `operation` にはコメント・チェックリストの `edit_comment` / `delete_comment` / `edit_checklist` / `check_checklist_item` も入る。`invalid_todo_input` の `errors[].code` にはサービスの `reason`（`required` / `too_long` / `too_many` / `mismatch` / `out_of_range` 等）が入る。`If-Match` が無ければ 428、形式不正は 400
- 入力の形式（型・長さ・enum・UUID）の誤りは FastAPI の検証による 422（`validation_error`）で、サービスの検証（`invalid_todo_input`）より先に返る

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
| 7 | 更新の権限の判定対象 | PATCH は**実際に値が変わる項目**で判定する（同じ値を送った項目は変更とみなさない）。編集画面が全項目を送っても、担当者のステータス変更は通る |
| 8 | 変更系の判定の順序 | 入力の形式（422）→ 閲覧範囲（404）→ 版（412）→ 権限（403）→ 現在の状態に依存する検証（422。組織・担当者の存在と有効性、`organization` の組織 1 つ以上） |
| 9 | 無効化された担当者を外せる人（AP-ASN-04） | 3 章の表を優先し、担当者の変更の権限を持つ人（`tenant_admin`・作成者・担当者）は外せる。新たな割り当てだけを拒否する（AP-ASN-02） |
| 10 | 公開先組織の扱い（AP-VIS-07 / 08） | `organization` 以外に変えると公開先の行を削除する。閲覧範囲・公開先を変える更新では有効な組織が 1 つ以上必要（既に公開先にある削除済みの組織は指定に残してよいが、新たには指定できない）。変えない更新は、公開先がすべて削除済みでもそのまま通す。詳細の `effective_visibility` が `private` になったら再指定を促す |
| 11 | 一覧の並び替え | 単一キー + `id`（03 §3 の複数キー `sort=due_date,-priority` は未対応）。既定は `-created_at`。`due_date` の期限なしは昇順で末尾・降順で先頭。`priority` は `low < medium < high` |
| 12 | 期限の絞り込み | `due_before` / `due_after` は指定日を含む。期限なしの ToDo は除外 |
| 13 | 一覧の項目 | 説明（最大 10,000 文字）は一覧に含めず、詳細でだけ返す |
| 14 | 公開先組織の上限 | 100（仕様に上限は無いが入力の大きさを抑えるため。担当者は AP-ASN-01 の 20 人） |
| 15 | アクティビティの並び順 | 新しい順（同じ操作で記録した行は記録順の逆） |
| 16 | コメント・チェックリストと ToDo の版 | ToDo 本体の `version` / `updated_at` / `ETag` は変えない（本体の編集と 412 で衝突させない。AP-CHK-08）。そのため「更新日時」順の並びにはコメント・チェックの操作は反映されない |
| 17 | チェックリストの楽観ロックの単位 | 項目の名前変更・完了の切り替え・削除は項目の `version`。項目の追加・削除・並べ替えで `checklist_version` を上げ、並べ替えはそれを `If-Match` に取る。追加は `If-Match` 不要 |
| 18 | チェックリスト項目の更新の権限 | #7 と同じく**実際に変わる項目**で判定する。名前を変えずに完了だけを切り替えるなら担当者も通る |
| 19 | コメントの並び順 | 古い順で固定 |
| 20 | アクティビティへの記録 | チェックリストは `checklist_changed`（`payload.op` は `added` / `renamed` / `removed` / `checked` / `unchecked`）を記録し、並べ替えは記録しない。コメントは記録せず監査ログにだけ残す |
| 21 | ホームの要約の「今日」 | クライアントのローカル日付を `today` で受け取る（省略時は UTC の日付）。期限切れは `due_date < today`、期限間近は `today <= due_date <= today + due_soon_days`（既定 7、1〜30）。いずれも完了（`done`）を除く |
| 22 | カンバンの列内の順序 | 並び順の指定に従い、手動の並べ替えは保存しない |
| 23 | チェックリスト項目の削除 | 物理削除（履歴はアクティビティに残る）。削除後は `position` を 0 から詰め直す。変更系の API はチェックリスト全体を返す（DELETE も 200） |
| 24 | コメントの削除の応答 | ToDo の削除と同じく 204 |

## 11. 未決事項

現時点で未決事項はない。
