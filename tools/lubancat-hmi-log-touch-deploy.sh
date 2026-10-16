#!/bin/sh
set -eu
deploy_root=/home/cat/lubancat_hmi_log_touch_20260930
archive=/home/cat/log-touch-fix-20260930.zip
override=/etc/systemd/system/lubancat-hmi.service.d/zzzzzz-log-touch.conf
# Never overwrite an existing checkout or override. Previous HMI stays running
# until the new binary has compiled and passed all tests.
test ! -e "$deploy_root" || { echo "Deployment directory exists; inspect before retry." >&2; exit 1; }
test ! -e "$override" || { echo "Touch override already exists; inspect before retry." >&2; exit 1; }
test -f "$archive"
mkdir "$deploy_root"
cd "$deploy_root"
unzip -q "$archive"
cmake -S lubancat_hmi -B build -DCMAKE_BUILD_TYPE=Release -DHMI_BUILD_TESTS=ON
cmake --build build -j2
(cd build && ctest --output-on-failure)
mkdir service-backup
cp -a /etc/systemd/system/lubancat-hmi.service /etc/systemd/system/lubancat-hmi.service.d service-backup/
install -m 644 lubancat_hmi/systemd/zzzzzz-log-touch.conf "$override"
systemctl daemon-reload
systemctl restart lubancat-hmi.service
systemctl is-active lubancat-hmi.service
systemctl show lubancat-hmi.service -p ExecStart
echo "Only HMI changed. STM32 and CAN setup unchanged. Confirm buttons on the MIPI screen."
