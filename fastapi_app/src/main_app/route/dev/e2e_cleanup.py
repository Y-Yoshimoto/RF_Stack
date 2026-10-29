#!/usr/bin/env python
# coding:utf-8
"""E2E データの後片付け API（開発専用。``POST /api/dev/e2e-cleanup``）。

Playwright の E2E が作る使い捨てデータ（テナント・ユーザー・組織・ToDo）を、ティアダウンから削除する。
処理の実体は :mod:`dev_tools.e2e_cleanup`（対象の判定はそちらの定数に固定。このルーターは引数で対象を受け取らない）。

**開発専用。** dev-login と同じ条件（``APP_ENV=development`` かつ ``AUTH_DEV_LOGIN_ENABLED=true``。
:meth:`~modules.auth.environment.KeyCloakEnvironmentVariables.is_dev_login_enabled`）のときだけ ``app.py`` から登録される。
無効時はルート自体が存在せず 404。OpenAPI にも載せない（``include_in_schema=False``）。

認可:
    - CP セッション（``rf_sid_cp``）の ``saas_admin`` が必要（未認証・AP のセッションは 401、``saas_viewer`` は 403）。
    - CSRF 対策（``X-Requested-With: rf-stack`` と ``Origin``）を適用する。ヘッダーが無ければ 403。

応答:
    - 200: :meth:`~dev_tools.e2e_cleanup.E2ECleanupResult.to_dict` の内容。**失敗したテナントがあっても 200** で、``ok`` が ``false``、
      内訳が ``failures`` に入る（他のテナントの処理は続けている）。呼び出し側は ``ok`` を見て判断する。
    - 409 ``e2e_cleanup_in_progress``: 別の後片付け（API・CLI）が実行中。

タイムアウト:
    同期処理であり、テナントごとに Keycloak を呼ぶため、対象が多いと数十秒〜数分かかりうる。ハンドラは同期関数（スレッドプールで実行）なので、
    実行中も他のリクエストは処理される。この API に処理時間の上限は設けない（Keycloak の各呼び出しにはそれぞれタイムアウトがある）。
    **呼び出し側は十分長いタイムアウト（目安 5 分以上）を指定すること。** 呼び出し側が先に切断しても、サーバー側の処理は最後まで続く。
    処理は冪等で、同時実行は 409 で拒否されるため、タイムアウト後は少し待ってから同じ呼び出しをやり直せば収束する
    （まず ``dry_run=true`` で件数だけ確認することもできる）。
"""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from dev_tools.e2e_cleanup import E2ECleanupInProgressError, E2ECleanupNotAllowedError, cleanup_e2e_data
from modules.auth.csrf import require_csrf_protection
from modules.auth.dependency import require_cp_roles
from modules.errors.catalog import text_for_code
from modules.errors.handlers import problem_from_text

# 認可は依存関数の宣言順に評価される（認証・ロール → CSRF）。CP の変更系と同じ順序。
router = APIRouter(dependencies=[Depends(require_cp_roles("saas_admin")), Depends(require_csrf_protection)])


@router.post("/e2e-cleanup", include_in_schema=False)
def e2e_cleanup(dry_run: Annotated[bool, Query(description="`true` なら何も変更せず、処理する予定の件数だけ返す")] = False) -> dict[str, Any]:
    """E2E が作る使い捨てデータを後片付けする（開発専用）。

    Args:
        dry_run: ``True`` なら何も変更せず、件数だけ返す。

    Returns:
        dict: ``E2ECleanupResult.to_dict()``（``dry_run`` / ``tenants`` / ``app_tenants`` / ``failures`` / ``ok``）。

    Raises:
        ProblemError(``modules.errors.problem``): 実行中なら 409（``e2e_cleanup_in_progress``）。開発環境でなければ 404（通常はルート自体が無い）。
    """
    try:
        return cleanup_e2e_data(dry_run=dry_run).to_dict()
    except E2ECleanupInProgressError as exc:
        raise problem_from_text(409, "e2e_cleanup_in_progress", text_for_code("e2e_cleanup_in_progress", 409)) from exc
    except E2ECleanupNotAllowedError as exc:
        raise problem_from_text(404, "not_found", text_for_code("not_found", 404)) from exc
