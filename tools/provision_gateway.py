"""Offline NVS image generator. Never flashes or resets either board.

Run with the installed ESP-IDF Python environment. Output contains secrets.
"""
import argparse
import csv
import getpass
import ipaddress
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

def _lubancat_ssh(command, input_text=None):
    """Capture only; never log remote stdout, stderr, or secret stdin."""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        raise RuntimeError("Windows LOCALAPPDATA is unavailable")
    key = Path(local_appdata)/"Temp"/"codex-lubancat-ssh-admin-20260928"/"id_ed25519"
    ssh = Path(os.environ.get("WINDIR", "C:/Windows"))/"System32"/"OpenSSH"/"ssh.exe"
    if not key.is_file() or not ssh.is_file():
        raise RuntimeError("Existing LubanCat SSH key or client is unavailable")
    return subprocess.run([
        str(ssh), "-T", "-i", str(key), "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=5", "root@192.168.137.10", command,
    ], input=input_text, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", timeout=20, check=True).stdout

def lubancat_hotspot_password():
    value = _lubancat_ssh(
        "nmcli --show-secrets -g 802-11-wireless-security.psk connection show codex-esp32-hotspot"
    ).rstrip("\r\n")
    if len(value) != 32 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise RuntimeError("Hotspot password does not match the configured random format")
    return value

def check_lubancat_api_token(token):
    # Secret travels on encrypted SSH stdin, never in a command line or a URL.
    command = "python3 -c 'import sys; from urllib.request import Request,urlopen; t=sys.stdin.read(); q=Request(\"http://192.168.50.1:18089/api/v1/summary\",headers={\"Authorization\":\"Bearer \"+t}); r=urlopen(q,timeout=5); print(r.status); r.close()'"
    if _lubancat_ssh(command, token).strip() != "200":
        raise RuntimeError("Cloud API authentication was not confirmed")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ssid")
    p.add_argument("--url",help="Full /api/v1/observations endpoint")
    p.add_argument("--interactive",action="store_true",help="Prompt locally; never flashes hardware")
    p.add_argument("--allow-lan-http",action="store_true")
    p.add_argument("--lubancat-hotspot", action="store_true",
                   help="Capture this project's hotspot password over existing SSH and verify API authentication")
    p.add_argument("--output",default="esp32_s3_gateway/local_config/network_nvs.bin")
    args=p.parse_args()
    if args.interactive:
        print("OFFLINE CONFIGURATION ONLY. No board will be flashed or reset.")
        print("Use the LubanCat LAN endpoint, NOT 127.0.0.1 or the public cloud HTTP address.")
        if not args.ssid:args.ssid=input("2.4 GHz Wi-Fi SSID: ")
        if not args.url:args.url=input("Full upload URL (/api/v1/observations): ").strip()
        if args.url.startswith("http://") and not args.allow_lan_http:
            args.allow_lan_http=input("Trusted LAN plaintext demo only. Type LAN to allow: ")=="LAN"
    if not args.ssid or not args.url:p.error("Provide --ssid and --url, or use --interactive")
    u=urlsplit(args.url)
    if not u.hostname or u.username or u.password or u.query or u.fragment or u.path!="/api/v1/observations":
        p.error("URL must be the observation endpoint without credentials or query")
    if u.scheme!="https" and not (args.allow_lan_http and u.scheme=="http"):
        p.error("Use HTTPS, or explicitly opt into trusted-LAN plaintext demo")
    if u.hostname.lower() in ("localhost","localhost.localdomain"):
        p.error("ESP32 must use a reachable server address, not localhost")
    try:address=ipaddress.ip_address(u.hostname)
    except ValueError:address=None
    if address and (address.is_loopback or address.is_unspecified):
        p.error("ESP32 cannot upload to loopback or an unspecified address")
    if u.scheme=="http":
        private_ranges=(ipaddress.ip_network("10.0.0.0/8"),ipaddress.ip_network("172.16.0.0/12"),ipaddress.ip_network("192.168.0.0/16"))
        if not isinstance(address,ipaddress.IPv4Address) or not any(address in subnet for subnet in private_ranges):
            p.error("Plain HTTP demo requires a private LAN IPv4 address; never send a token over public HTTP")
    if not 1<=len(args.ssid.encode())<=32:p.error("SSID must be 1..32 UTF-8 bytes")
    if args.lubancat_hotspot:
        if args.ssid != "LubanCat-ESP32" or args.url != "http://192.168.50.1:18089/api/v1/observations":
            p.error("LubanCat auto-provisioning is restricted to this project's hotspot and upload endpoint")
        try: password=lubancat_hotspot_password()
        except (OSError, subprocess.SubprocessError, RuntimeError):
            p.error("Could not capture the existing hotspot password securely; no configuration created")
        print("Hotspot password loaded securely; value not displayed.")
    else:
        password=getpass.getpass("Wi-Fi password (hidden): ")
    if not 8<=len(password.encode())<=63:p.error("Wi-Fi password must be 8..63 bytes")
    token=(None if args.interactive else os.environ.get("TIGHTEN_API_TOKEN")) or getpass.getpass("Server API token (hidden): ")
    if not 24<=len(token)<=128 or any(not 33<=ord(c)<=126 for c in token):
        p.error("Token must be 24..128 printable ASCII characters without whitespace")
    if len(args.url.encode())>255:p.error("URL too long")
    if args.lubancat_hotspot:
        try: check_lubancat_api_token(token)
        except (OSError, subprocess.SubprocessError, RuntimeError):
            p.error("Cloud API authentication failed or service unreachable; check the current server token. Nothing flashed")
        print("Cloud API authentication verified (HTTP 200); token not displayed.")
    dest=Path(args.output).resolve();dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():p.error("Output already exists; choose a new path to preserve old provisioning")
    # Generator requires a CSV. Keep it only in a temporary private directory.
    with tempfile.TemporaryDirectory(prefix="gateway-nvs-") as temporary:
        source=Path(temporary)/"config.csv"
        with source.open("w",newline="",encoding="utf-8") as f:
            w=csv.writer(f);w.writerow(["key","type","encoding","value"])
            w.writerow(["gateway","namespace","",""])
            for key,value in (("ssid",args.ssid),("pass",password),("url",args.url),("token",token)):
                w.writerow([key,"data","string",value])
            w.writerow(["allow_http","data","u8",int(args.allow_lan_http)])
        subprocess.run([sys.executable,"-m","esp_idf_nvs_partition_gen","generate",str(source),str(dest),"0x6000"],check=True)
    print(f"Created private NVS image: {dest}\nContains secrets. Not flashed; do not share or commit.")

if __name__=="__main__":main()
