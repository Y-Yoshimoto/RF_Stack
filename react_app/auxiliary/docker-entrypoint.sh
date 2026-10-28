#!/bin/bash -x
NPMINSTALLLOCK=/work/react_app/.npm_install.lock
echo "Start Setup."
touch ${NPMINSTALLLOCK}
date +"%Y/%m/%d %H:%M:%S" >> ${NPMINSTALLLOCK} && id | tee -a ${NPMINSTALLLOCK}
# 出力をロックファイルに残しつつ、パイプの左側(コマンド本体)の終了コードを返す
run_logged() {
    "$@" 2>&1 | tee -a ${NPMINSTALLLOCK}
    return "${PIPESTATUS[0]}"
}
echo "Installing dependencies. ---------------------" | tee -a ${NPMINSTALLLOCK}
if ! run_logged npm install --include=dev --force; then
    # 失敗したまま CMD を exec すると、依存が不完全なまま起動して原因が分かりにくいため、ここで止める
    # ロックファイルが残ると他の処理が待ち続けるため削除する(ログはコンテナのログに出力済み)
    rm -f ${NPMINSTALLLOCK}
    {
        echo "ERROR: Failed to install npm dependencies ('npm install --include=dev --force' failed)."
        echo "  Check the npm output above. Common causes:"
        echo "  - Network error / timeout while downloading packages (registry unreachable, proxy settings)"
        echo "  - package.json / package-lock.json is invalid or inconsistent"
        echo "  - No write permission on /work/react_app (USER_ID / GROUP_ID in .env do not match the host user)"
        echo "  - node_modules is broken. Remove react_app/node_modules on the host and restart (see the dev-environment skill)"
    } >&2
    exit 1
fi
echo "Installing Playwright browsers. ---------------------" | tee -a ${NPMINSTALLLOCK}
if ! run_logged npx playwright install chromium chromium-headless-shell webkit; then
    # ブラウザが無くても開発サーバーやユニットテストは動くため、ここでは止めずに警告に留める(E2E だけが失敗する)
    echo "WARN: Failed to install Playwright browsers. The dev server still starts, but E2E tests will fail." | tee -a ${NPMINSTALLLOCK} >&2
    echo "  Retry: make d-run SERVICE=react_app CMD=\"npx playwright install chromium chromium-headless-shell webkit\"" >&2
fi
echo "Installation completed." | tee -a ${NPMINSTALLLOCK}
rm ${NPMINSTALLLOCK}
echo "End Setup."
exec "$@"
