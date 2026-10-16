#!/bin/sh
set -eu
/usr/sbin/nginx -t
if /bin/systemctl is-active --quiet nginx.service; then
    /bin/systemctl reload nginx.service
fi
