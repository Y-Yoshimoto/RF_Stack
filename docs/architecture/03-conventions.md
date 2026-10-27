# 03. 共通規約

> ステータス: ドラフト v0.5（方針を決定。詳細は実装時に確認する）
>
> テーマに依存しない API・データ・ログの規約。各項目の「実装」欄は [02](02-platform-implementation.md) の技術スタックでの実現方法を示す。
> コードの書き方（命名・行長等）は `docs/coding-standards/` を正とし、本書では扱わない。

---

## 1. API の基本

| 項目 | 規約 |
| --- | --- |
| 形式 | JSON。`Content-Type: application/json; charset=utf-8` |
| フィールド名 | `snake_case`（TypeScript のデータも `snake_case` とするコーディング規約と一致させる） |
| URL | 複数形の名詞、`kebab-case`（例: `/api/v1/todos/{id}/assignees`） |
| 列挙値 | 小文字 `snake_case` の文字列（例: `in_progress`）。CP のテナント状態のみ既存の大文字（`ACTIVE` 等） |
| バージョン | URL の `/api/v1`。破壊的変更は `/api/v2` を並行提供する。フィールド追加は非破壊として扱い、クライアントは未知のフィールドを無視する |
| 部分更新 | `PATCH` は送ったフィールドだけを更新する。`null` は「値を消す」意味とする |
| 一覧の置き換え | 担当者・組織メンバー等の集合は `PUT .../{collection}` で全置換する |
| CSRF ヘッダー | 変更系メソッドは `X-Requested-With: rf-stack` を必須とする |
| リクエスト ID | `X-Request-ID` を受け取り（無ければ生成）、レスポンスヘッダーとログに出す |

---

## 2. エラーレスポンス

**RFC 9457（Problem Details for HTTP APIs）** に統一する。`Content-Type: application/problem+json`。

```json
{
  "type": "https://errors.rf-stack.example/todo-not-found",
  "title": "ToDo が見つかりません",
  "status": 404,
  "detail": "指定された ToDo は存在しないか、閲覧権限がありません",
  "instance": "/api/v1/todos/0192f0c3-...",
  "code": "todo_not_found",
  "request_id": "6f1c...",
  "errors": []
}
```

| フィールド | 規約 |
| --- | --- |
| `type` | エラー種別の URI。当面は `code` から機械的に作る（解決できる URL でなくてよい） |
| `code` | 機械判定用の `snake_case` 文字列。フロントはこれで分岐する |
| `title` / `detail` | 利用者向けの日本語。内部情報（SQL、スタックトレース、テナントの存在有無）を含めない |
| `errors` | 入力検証エラーの詳細。`[{ "field": "title", "code": "too_long", "message": "..." }]` |
| `request_id` | ログとの突き合わせ用 |

| 状況 | ステータス | 補足 |
| --- | --- | --- |
| 未認証・セッション切れ | 401 | |
| 認可されていない・テナント停止中 | 403 | |
| 存在しない・**他テナントのリソース**・閲覧権限が無いリソース | 404 | 他テナントや閲覧範囲外のリソースは存在を明かさないため 404 に揃える |
| 入力検証エラー | 422 | |
| 一意制約違反・状態遷移の不正 | 409 | |
| 楽観ロックの不一致 | 412 | 5 章 |
| 楽観ロックのヘッダー無し | 428 | 5 章 |
| 外部依存（IdP 等）の失敗 | 502 / 504 | 払い出し失敗は 502 |

**実装**: `modules/errors` に例外クラスと FastAPI の例外ハンドラを置き、`HTTPException` と `RequestValidationError` も Problem Details に変換する。

---

## 3. ページネーション・並び替え・絞り込み

| 項目 | 規約 |
| --- | --- |
| 方式 | **カーソル方式**を標準とする（件数が増えても性能が落ちず、追加・削除でずれない） |
| リクエスト | `limit`（既定 50、最大 200）、`cursor`（前回レスポンスの `next_cursor`） |
| レスポンス | `{ "items": [...], "next_cursor": "..." \| null }`。総件数は必要な画面だけ `include_total=true` で返す |
| カーソル | 並び替えキーと `id` を含む不透明な文字列（base64url）。クライアントは中身を解釈しない |
| 並び替え | `sort=due_date,-priority`（`-` は降順）。許可するキーはエンドポイント毎に定義し、最後に必ず `id` を付けて順序を安定させる |
| 絞り込み | フィールド名のクエリパラメータ（`status=open`）。複数値はカンマ区切り（`status=open,in_progress`） |

CP の管理画面など件数が少なく総件数が必要な一覧も、同じ形式で `include_total=true` を使う。

---

## 4. ID・日時・データ型

| 項目 | 規約 | 実装 |
| --- | --- | --- |
| ID | UUIDv7（時刻順にソート可能、インデックス効率が良い）。API では文字列 | PostgreSQL `uuid`、Python `uuid.uuid7()` |
| 人が使う識別子 | ID とは別の列（例: `tenant_code`）。変更不可にするかは項目毎に決める | |
| 日時 | UTC で保存し、API は ISO 8601（`2026-10-27T03:00:00Z`） | `timestamptz` |
| 日付 | タイムゾーンを持たない日付（期限日など）は日付型 | `date`、API は `2026-10-27` |
| 表示 | フロントで利用者のタイムゾーン（既定 `Asia/Tokyo`）に変換する | |
| 共通列 | 全テーブルに `created_at`, `updated_at`。利用者の操作で作られる行は `created_by`, `updated_by`（ユーザー ID） | `updated_at` はアプリ側で更新 |
| 金額・数量 | 浮動小数点を使わない | `numeric` / 整数 |

---

## 5. 論理削除と楽観ロック

### 5.1 論理削除

- 利用者が削除できるデータは `deleted_at`（`timestamptz`、NULL = 有効）で論理削除する
- 既定のクエリは `deleted_at IS NULL` を条件にする（リポジトリ層の共通処理で付与する）
- 一意制約は部分インデックスにする（`... WHERE deleted_at IS NULL`）
- 物理削除は保持期間を過ぎたデータの定期ジョブと、テナントの物理削除でのみ行う
- 論理削除したデータを返す API は作らない（復元は将来拡張）

### 5.2 楽観ロック

複数人で同じデータを編集しうるため、更新系に楽観ロックを適用する。

- 対象テーブルは `version`（整数、作成時 1、更新毎に +1）を持つ
- `GET` は `ETag: "<version>"` を返す
- `PATCH` / `PUT` / `DELETE` は `If-Match: "<version>"` を必須とし、不一致は 412、ヘッダー無しは 428
- 一覧の各要素にも `version` を含め、一覧から直接更新できるようにする

---

## 6. ログ

### 6.1 構造化ログ

- 1 行 1 JSON で標準出力に出す。収集・保管は外部基盤の責務とする
- 必須フィールド:

| フィールド | 内容 |
| --- | --- |
| `timestamp` | UTC の ISO 8601（ミリ秒まで） |
| `level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `logger` | ロガー名 |
| `message` | 人が読む文 |
| `event` | 機械集計用のイベント名（`snake_case`、例: `tenant_provisioned`） |
| `plane` | `app` / `cp` / `system`（定期ジョブ等） |
| `tenant_id` | テナントコンテキストがあれば |
| `user_id` | 認証済みなら |
| `request_id` | リクエスト中なら |
| `trace_id` | 分散トレース導入後（[04](04-observability.md)） |

- レベルの使い分け: `ERROR` は人の対応が必要なもの、`WARNING` は自動回復したが頻発すれば調査が必要なもの、利用者の入力ミス（4xx）は `INFO`

### 6.2 出してはいけないもの

パスワード（一時パスワード含む）、トークン、クライアントシークレット、セッション ID、Cookie、`Authorization` ヘッダー。メールアドレス等の個人情報は原則出さず、必要なら `user_id` で代替する。
**実装**: ロガーのフィルタでキー名による伏せ字化を行い、二重の防御とする。

### 6.3 利用記録（アクセスログ）

AP API のリクエスト毎に 1 行出力する（`event: "api_request"`）。

| フィールド | 内容 |
| --- | --- |
| `method` | HTTP メソッド |
| `route` | テンプレート形式のパス（例: `/api/v1/todos/{id}`）。ID を含めない |
| `status` | ステータスコード |
| `duration_ms` | 処理時間 |
| `tenant_id`, `user_id`, `request_id` | 6.1 と同じ |

アクティブユーザー数（日次・月次）の集計元とする（集計は将来）。

---

## 7. 監査ログ

| 項目 | 規約 |
| --- | --- |
| 対象 | CP の全変更操作、AP の共通機能（ユーザー・組織）の変更、テーマが定める操作 |
| 保存先 | CP は CP DB の CP 監査ログ、AP は AP DB の AP 監査ログ（テナントスコープ・RLS 適用） |
| 列 | `actor`（ユーザー ID / システム）, `action`（`resource.verb`、例: `tenant.suspend`）, `target_type`, `target_id`, `payload`（変更前後の差分）, `request_id`, `created_at` |
| 書き込み | 業務データの変更と**同じトランザクション**で書く |
| 秘匿値 | 6.2 と同じく、パスワード等を `payload` に含めない |
| 変更 | 追記のみ。更新・削除しない（テナント物理削除時を除く） |
| ドメインの履歴との関係 | 利用者に見せる履歴（例: ToDo のアクティビティ）とは別に持つ。履歴は表示用、監査ログは運用・調査用 |

---

## 8. API 契約

- FastAPI が生成する OpenAPI を契約の正とする
- フロントの型は OpenAPI から生成する（ツールは実装時に決める）。`api-contract-sync` が差分を検証する
- エンドポイントには `summary`、`tags`（`app` / `cp` / `public` / `auth`）、エラーレスポンスの例を付ける
