#!/bin/bash -x
UVINSTALLLOCK=.uv_install.lock
echo "Start Setup."
touch ${UVINSTALLLOCK}
date +"%Y/%m/%d %H:%M:%S" >> ${UVINSTALLLOCK} && id | tee -a ${UVINSTALLLOCK}
# uv パッケージのインストール
echo "Installing dependencies. ---------------------" | tee -a ${UVINSTALLLOCK}
# 出力をロックファイルに残しつつ、パイプの左側(uv)の終了コードを返す
run_uv_sync() {
    "$@" 2>&1 | tee -a ${UVINSTALLLOCK}
    return "${PIPESTATUS[0]}"
}
if ! run_uv_sync uv sync --locked; then
    echo "WARN: 'uv sync --locked' failed. Retrying with 'uv sync'. ---------------------" | tee -a ${UVINSTALLLOCK}
    if ! run_uv_sync uv sync; then
        # 失敗したまま CMD を exec すると uvicorn が見つからず exit 127 になり原因が分かりにくいため、ここで止める
        # ロックファイルが残ると他の処理が待ち続けるため削除する(ログはコンテナのログに出力済み)
        rm -f ${UVINSTALLLOCK}
        {
            echo "ERROR: Failed to install Python dependencies ('uv sync --locked' and 'uv sync' both failed)."
            echo "  Check the uv output above. Common causes:"
            echo "  - Network error / timeout while downloading packages"
            echo "    (UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT:-default}, UV_CONCURRENT_DOWNLOADS=${UV_CONCURRENT_DOWNLOADS:-default}). Raise the timeout or retry."
            echo "  - pyproject.toml / uv.lock is invalid or inconsistent"
            echo "  - The virtual environment volume (${UV_PROJECT_ENVIRONMENT}) is broken or stale."
            echo "    Recreate it: docker compose down && docker volume rm <project>_fastapi_uv_venv (see the dev-environment skill)"
        } >&2
        exit 1
    fi
fi
# playwright用のブラウザのインストール
# echo "Installing Playwright browsers. ---------------------" | tee -a ${UVINSTALLLOCK}
# uv run playwright install chromium | tee -a ${UVINSTALLLOCK}
# echo "Installation completed." | tee -a ${UVINSTALLLOCK}
# uv 仮想環境の有効化(source .venv/bin/activate)
# . .venv/bin/activate 2>&1 | tee -a ${UVINSTALLLOCK}
source $UV_PROJECT_ENVIRONMENT/bin/activate 2>&1 | tee -a ${UVINSTALLLOCK}
rm ${UVINSTALLLOCK}
echo "End Setup."
exec "$@"