#!/bin/sh
# Set up the existing CAN interface without interrupting a correctly running bus.
set -eu

IP=/usr/sbin/ip
IFACE=can0

if [ ! -d "/sys/class/net/$IFACE" ]; then
    echo "$IFACE is not present" >&2
    exit 1
fi

if "$IP" -o link show dev "$IFACE" | grep -q 'state UP'; then
    details=$("$IP" -details link show dev "$IFACE")
    case "$details" in
        *'bitrate 500000'*'restart-ms 100'*) exit 0 ;;
        *'restart-ms 100'*'bitrate 500000'*) exit 0 ;;
    esac
    echo "$IFACE is already UP with unexpected timing; refusing to interrupt it" >&2
    exit 1
fi

"$IP" link set dev "$IFACE" type can bitrate 500000 restart-ms 100
"$IP" link set dev "$IFACE" up

details=$("$IP" -details link show dev "$IFACE")
case "$details" in
    *'bitrate 500000'*'restart-ms 100'* | *'restart-ms 100'*'bitrate 500000'*) ;;
    *) echo "$IFACE did not accept the expected timing" >&2; exit 1 ;;
esac
