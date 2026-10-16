#!/usr/bin/env bash
# New, isolated NetworkManager AP profile. No credentials are printed.
set -Eeuo pipefail

profile='codex-esp32-hotspot'
ssid='LubanCat-ESP32'
iface='wlan0'
address='192.168.50.1/24'
created_uuid=''

rollback() {
    local status=$?
    trap - ERR
    if [[ -n "$created_uuid" ]]; then
        nmcli --wait 10 connection down uuid "$created_uuid" >/dev/null 2>&1 || true
        nmcli connection delete uuid "$created_uuid" >/dev/null 2>&1 || true
        printf 'Activation failed; removed only the AP profile created by this script.\n' >&2
    fi
    exit "$status"
}
trap rollback ERR

[[ $EUID -eq 0 ]] || { printf 'Run as root.\n' >&2; exit 1; }
command -v nmcli >/dev/null
command -v openssl >/dev/null
command -v dnsmasq >/dev/null
[[ $(nmcli -g WIFI-PROPERTIES.AP device show "$iface") == yes ]]
if nmcli -g NAME connection show | grep -Fxq "$profile"; then
    printf 'Profile already exists; refusing to overwrite its settings or password.\n' >&2
    exit 1
fi
if ip -4 route show | grep -Eq '^192\.168\.50\.'; then
    printf 'Hotspot subnet overlaps an existing route; no changes made.\n' >&2
    exit 1
fi
if [[ $(nmcli -g GENERAL.STATE device show "$iface") != '30 (disconnected)' ]]; then
    printf 'wlan0 is not disconnected; refusing to replace an active connection.\n' >&2
    exit 1
fi

# Same 2.4 GHz channel as the existing campus station, to reduce concurrency conflicts.
nmcli connection add type wifi ifname "$iface" con-name "$profile" ssid "$ssid" >/dev/null
created_uuid=$(nmcli -g connection.uuid connection show "$profile")
psk=$(openssl rand -hex 16)
nmcli connection modify uuid "$created_uuid" \
    connection.autoconnect yes \
    connection.autoconnect-priority 10 \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    802-11-wireless.channel 6 \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.proto rsn \
    802-11-wireless-security.pairwise ccmp \
    802-11-wireless-security.group ccmp \
    802-11-wireless-security.psk "$psk" \
    ipv4.method shared \
    ipv4.addresses "$address" \
    ipv4.never-default yes \
    ipv6.method disabled >/dev/null
unset psk
nmcli --wait 35 connection up uuid "$created_uuid" >/dev/null
trap - ERR
printf 'Hotspot active: SSID=%s interface=%s address=%s UUID=%s\n' "$ssid" "$iface" "$address" "$created_uuid"
printf 'Password is stored only in the root-managed NetworkManager profile.\n'
nmcli -f GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS device show "$iface"
ip -4 route show default
exit 0
