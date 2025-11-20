#!/bin/bash -x
UVINSTALLLOCK=.uv_install.lock
echo "Start Setup."
touch ${UVINSTALLLOCK}
date +"%Y/%m/%d %H:%M:%S" >> ${UVINSTALLLOCK} && id | tee -a ${UVINSTALLLOCK}
# uv パッケージのインストール
echo "Installing dependencies. ---------------------" | tee -a ${UVINSTALLLOCK}
uv sync --locked 2>&1 || uv sync 2>&1 | tee -a ${UVINSTALLLOCK}
# playwright用のブラウザのインストール
# echo "Installing Playwright browsers. ---------------------" | tee -a ${UVINSTALLLOCK}
# uv run playwright install chromium | tee -a ${UVINSTALLLOCK}
# echo "Installation completed." | tee -a ${UVINSTALLLOCK}
# uv 仮想環境の有効化(source .venv/bin/activate)
. .venv/bin/activate 2>&1 | tee -a ${UVINSTALLLOCK}
rm ${UVINSTALLLOCK}
echo "End Setup."
exec "$@"