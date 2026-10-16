"""Tencent Ubuntu IP HTTPS deployment; default CHECK ONLY, no secrets required.

--prepare installs Nginx/Certbot and serves ONLY ACME challenges. No firewall
change or public application. Issue certificates interactively as documented.
--activate requires trusted production certificate and provider policy approval.
Neither mode restarts the backend, changes its token/DB, nor operates motors.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from urllib.request import urlopen
import zipfile

IP = '118.25.40.152'
STATE = Path('/var/lib/tightening-ip-https')
CONFIG = Path('/etc/nginx/sites-available/tightening-public-ip')
ENABLED = Path('/etc/nginx/sites-enabled/tightening-public-ip')
ASSETS = ('nginx-http.conf', 'nginx-https.conf', 'reload-nginx.sh',
          'tightening-ip-cert-renew.service', 'tightening-ip-cert-renew.timer')


def run(args, capture=False):
    result = subprocess.run(args, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    return result.stdout if capture else ''


def asset(name):
    if name not in ASSETS:
        raise RuntimeError('Unknown asset')
    if zipfile.is_zipfile(sys.argv[0]):
        with zipfile.ZipFile(sys.argv[0]) as archive:
            return archive.read(name)
    return Path(__file__).with_name(name).read_bytes()


def certbot_version(text):
    match = re.search(r'certbot\s+(\d+)\.(\d+)\.(\d+)', text)
    if not match or tuple(map(int, match.groups())) < (5, 4, 0):
        raise RuntimeError('Certbot 5.4+ required for IP webroot; do not use Ubuntu 20.04 old apt Certbot')


def certificate_ip(text):
    # OpenSSL x509 -checkip can return status 0 even for a mismatch.
    if not re.search(r'IP\s+' + re.escape(IP) + r'\s+does match certificate', text):
        raise RuntimeError('Certificate IP SAN mismatch')


def new_file(path, data, mode=0o644):
    # Exclusive creation: refuse unrelated files and symlinks, preserve them.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def check():
    if platform.system() != 'Linux' or platform.machine() != 'x86_64' or os.geteuid() != 0:
        raise RuntimeError('Use the root Tencent Ubuntu terminal, NOT Windows or LubanCat')
    os_release = Path('/etc/os-release').read_text()
    if 'ID=ubuntu' not in os_release or 'VERSION_ID="20.04"' not in os_release:
        raise RuntimeError('This package targets the verified Ubuntu 20.04 host only')
    if run(['systemctl', 'is-active', 'tencent-observations.service'], True).strip() != 'active':
        raise RuntimeError('Existing backend must remain active')
    with urlopen('http://127.0.0.1:18088/health', timeout=5) as response:
        if json.load(response).get('control_enabled') is not False:
            raise RuntimeError('Backend safety contract mismatch')
    listener = run(['ss', '-H', '-lnt', 'sport = :18088'], True)
    if not listener.strip() or any('127.0.0.1:18088' not in line for line in listener.splitlines()):
        raise RuntimeError('Backend must listen on loopback ONLY')
    print('CHECK PASS: backend active, loopback only, control LOCKED; no token read.')


def prepare():
    if shutil.which('nginx') or STATE.exists() or STATE.is_symlink():
        raise RuntimeError('Nginx or deployment state already exists; inspect it, do NOT rerun blindly')
    if run(['ss', '-H', '-lnt', '( sport = :80 or sport = :443 )'], True).strip():
        raise RuntimeError('80/443 already occupied; no services will be stopped')
    ufw = run(['ufw', 'status', 'verbose'], True)
    if not re.search(r'^Status: active$', ufw, re.M):
        raise RuntimeError('Expected active UFW; inspect firewall first')
    if not re.search(r'Default:\s+(deny|reject)\s+\(incoming\)', ufw):
        raise RuntimeError('Default incoming firewall policy must block Web ports before installation')
    # Ports must still be blocked while distro packages install their defaults.
    if re.search(r'(?im)^.*(?:\b80\b|\b443\b|nginx|www|https?).*ALLOW', ufw):
        raise RuntimeError('Existing Web allow rule found; inspect before package installation')
    if re.search(r'(?m)^-A ufw-user-input\s+.*-j ACCEPT',
                 run(['iptables', '-S', 'ufw-user-input'], True)):
        # Reject broad inbound allows; the exact known per-port rules are fine.
        rules = run(['iptables', '-S', 'ufw-user-input'], True)
        for line in rules.splitlines():
            if '-j ACCEPT' in line and '--dport ' not in line:
                raise RuntimeError('Broad inbound firewall allow found; inspect before installation')
    STATE.mkdir(mode=0o700)
    for name in ASSETS:
        new_file(STATE / name, asset(name), 0o600)
    run(['apt-get', 'update'])
    run(['apt-get', 'install', '-y', 'nginx', 'snapd', 'ca-certificates', 'curl'])
    # Nginx is new in this operation. Never stop a pre-existing web service.
    run(['systemctl', 'stop', 'nginx.service'])
    default = Path('/etc/nginx/sites-enabled/default')
    if default.is_symlink() and default.resolve() == Path('/etc/nginx/sites-available/default'):
        default.rename(STATE / 'default-site.before')
    elif default.exists() or default.is_symlink():
        raise RuntimeError('Unexpected default site; preserved, inspect manually')
    if list(Path('/etc/nginx/sites-enabled').iterdir()):
        raise RuntimeError('Unexpected enabled sites; preserved, inspect manually')
    Path('/var/www/tightening-acme/.well-known/acme-challenge').mkdir(parents=True, exist_ok=True)
    new_file(CONFIG, asset('nginx-http.conf'))
    ENABLED.symlink_to(CONFIG)
    run(['nginx', '-t'])
    run(['systemctl', 'enable', '--now', 'nginx.service'])
    run(['systemctl', 'enable', '--now', 'snapd.socket'])
    run(['snap', 'install', '--classic', 'certbot'])
    certbot_version(run(['/snap/bin/certbot', '--version'], True))
    print('PREPARE PASS: only HTTP ACME path configured, all other HTTP paths 404.')
    print('No firewall opened, no public app, no backend restart, no API token read.')
    print('Next: provider approval, port 80 challenge reachability, interactive staging/production issuance.')


def activate(policy_confirmed):
    if not policy_confirmed:
        raise RuntimeError('Public Web access requires confirmed provider policy; no activation')
    if not STATE.is_dir() or STATE.is_symlink() or CONFIG.is_symlink():
        raise RuntimeError('Prepared project deployment required')
    if not ENABLED.is_symlink() or ENABLED.resolve() != CONFIG:
        raise RuntimeError('Unexpected site enablement; preserved')
    before = CONFIG.read_bytes()
    if before != asset('nginx-http.conf'):
        raise RuntimeError('Configuration already activated or externally changed; inspect, do not overwrite')
    if list(Path('/etc/nginx/sites-enabled').iterdir()) != [ENABLED]:
        raise RuntimeError('Other sites present; preserve and inspect')
    certbot_version(run(['/snap/bin/certbot', '--version'], True))
    cert = Path('/etc/letsencrypt/live/tightening-public-ip')
    run(['openssl', 'verify', '-CApath', '/etc/ssl/certs', '-untrusted', str(cert / 'chain.pem'), str(cert / 'cert.pem')], True)
    certificate_ip(run(['openssl', 'x509', '-in', str(cert / 'cert.pem'), '-noout', '-checkip', IP], True))
    run(['openssl', 'x509', '-in', str(cert / 'cert.pem'), '-noout', '-checkend', '86400'], True)
    lib = Path('/usr/local/lib/tightening-https')
    if lib.exists() or lib.is_symlink():
        raise RuntimeError('Deploy-hook directory exists; preserve and inspect')
    units = [Path('/etc/systemd/system') / name for name in ASSETS if name.endswith(('.service', '.timer'))]
    if any(path.exists() or path.is_symlink() for path in units):
        raise RuntimeError('Renewal unit already exists; preserve and inspect')
    hooks = Path('/etc/letsencrypt/renewal-hooks/deploy')
    hook = hooks / 'tightening-reload-nginx.sh'
    if hook.exists() or hook.is_symlink() or hooks.is_symlink():
        raise RuntimeError('Unexpected existing renewal hook; preserve and inspect')
    lib.mkdir(mode=0o755)
    new_file(lib / 'reload-nginx.sh', asset('reload-nginx.sh'), 0o755)
    hooks.mkdir(parents=True, exist_ok=True)
    # Persistent hook applies to BOTH the Snap renewal timer and our timer.
    # A CLI-only hook could miss a renewal performed first by Snap's timer.
    hook.symlink_to(lib / 'reload-nginx.sh')
    for path in units:
        new_file(path, asset(path.name))
    run(['systemd-analyze', 'verify'] + [str(path) for path in units])
    # Replace only our exact known HTTP template; keep a recoverable snapshot.
    new_file(STATE / 'activated-http.before', before, 0o600)
    pending = CONFIG.with_name(CONFIG.name + '.pending')
    new_file(pending, asset('nginx-https.conf'))
    pending.replace(CONFIG)
    try:
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx.service'])
        # curl validates the IP certificate with system trust. No -k allowed.
        health = run(['curl', '--noproxy', '*', '--connect-to', IP + ':443:127.0.0.1:443',
                      '-fsS', '--max-time', '10', 'https://' + IP + '/health'], True)
        if json.loads(health).get('control_enabled') is not False:
            raise RuntimeError('HTTPS backend safety mismatch')
        denied = run(['curl', '--noproxy', '*', '--connect-to', IP + ':443:127.0.0.1:443',
                      '-sS', '--max-time', '10', '-o', '/dev/null', '-w', '%{http_code}',
                      '-X', 'POST', 'https://' + IP + '/api/v1/observations'], True)
        if denied != '403':
            raise RuntimeError('Public POST was not rejected')
        unauthorized = run(['curl', '--noproxy', '*', '--connect-to', IP + ':443:127.0.0.1:443',
                            '-sS', '--max-time', '10', '-o', '/dev/null', '-w', '%{http_code}',
                            'https://' + IP + '/api/v1/summary'], True)
        if unauthorized != '401':
            raise RuntimeError('Public data must require API authentication')
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', '--now', 'tightening-ip-cert-renew.timer'])
        # Only the IPv4 HTTPS entry; leave SSH/MQTT/video rules intact.
        run(['ufw', 'allow', 'proto', 'tcp', 'from', '0.0.0.0/0', 'to', 'any', 'port', '443',
             'comment', 'tightening HTTPS read-only'])
    except Exception:
        recovery = CONFIG.with_name(CONFIG.name + '.recovery')
        new_file(recovery, before)
        recovery.replace(CONFIG)
        subprocess.run(['nginx', '-t'], check=False)
        subprocess.run(['systemctl', 'reload', 'nginx.service'], check=False)
        print('Fallback to ACME-only HTTP configuration; generated files retained for inspection.')
        raise
    print('ACTIVATE PASS: trusted IP TLS, public POST denied, data auth required; six-hour renewal timer enabled.')
    print('Verify Tencent firewall 443 and EXTERNAL access/renewal; local success alone is NOT end-to-end acceptance.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--prepare', action='store_true')
    modes.add_argument('--activate', action='store_true')
    parser.add_argument('--provider-policy-confirmed', action='store_true')
    args = parser.parse_args()
    try:
        check()
        if args.prepare:
            prepare()
        elif args.activate:
            activate(args.provider_policy_confirmed)
        else:
            print('CHECK ONLY: no packages, files, services or firewall changed.')
    except Exception as error:
        detail = str(error) if type(error) is RuntimeError else type(error).__name__
        print('STOPPED: ' + detail + '. Do not rerun blindly; report non-secret error.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
