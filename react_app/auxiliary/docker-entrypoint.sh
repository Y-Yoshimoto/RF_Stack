#!/bin/bash -x
NPMINSTALLLOCK=/work/react_app/.npm_install.lock
echo "Start Setup."
touch ${NPMINSTALLLOCK}
date +"%Y/%m/%d %H:%M:%S" >> ${NPMINSTALLLOCK} && id | tee -a ${NPMINSTALLLOCK}
echo "Installing dependencies. ---------------------" | tee -a ${NPMINSTALLLOCK}
npm install --include=dev --force | tee -a ${NPMINSTALLLOCK}
echo "Installing Playwright browsers. ---------------------" | tee -a ${NPMINSTALLLOCK}
npx playwright install chromium chromium-headless-shell webkit | tee -a ${NPMINSTALLLOCK}
echo "Installation completed." | tee -a ${NPMINSTALLLOCK}
rm ${NPMINSTALLLOCK}
echo "End Setup."
exec "$@"