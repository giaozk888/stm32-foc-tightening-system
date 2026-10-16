"""Activate the prepared tunnel after cloud INSTALL PASS; run on LubanCat.

The current API token is supplied only through encrypted SSH stdin. Candidate
key authentication and API access are checked BEFORE stopping the old tunnel.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.request import Request, urlopen

UNIT = 'tightening-cloud-tunnel.service'
STATE = Path('/var/lib/tightening-cloud-tunnel')
SSH = ['/usr/bin/ssh', '-F', '/dev/null', '-NT', '-i', str(STATE / 'id_ed25519'),
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
       '-o', 'UserKnownHostsFile=' + str(STATE / 'known_hosts'),
       '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=8',
       '-o', 'ConnectionAttempts=1', '-o', 'ServerAliveInterval=10',
       '-o', 'ServerAliveCountMax=3']


def original_command(args):
    return (bool(args) and Path(args[0]).name == 'ssh' and '-N' in args and
            args[-1] == 'root@118.25.40.152' and '-L' in args and
            args[args.index('-L') + 1] == '192.168.50.1:18089:127.0.0.1:18088')


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def status():
    text = run(['systemctl', 'show', UNIT, '-p', 'MainPID', '-p', 'NRestarts', '-p', 'ActiveState'])
    return dict(line.split('=', 1) for line in text.splitlines())


def api(address, token, timeout=20):
    deadline = time.monotonic() + timeout
    while True:
        try:
            request = Request('http://' + address + '/api/v1/summary',
                              headers={'Authorization': 'Bearer ' + token})
            with urlopen(request, timeout=3) as response:
                data = json.load(response)
            if data['control_enabled'] is not False:
                raise RuntimeError('Unexpected unlocked server')
            return data
        except OSError:
            if time.monotonic() >= deadline:
                raise RuntimeError('Tunnel/API did not recover; inspect managed unit logs')
            time.sleep(0.5)


def activate(token):
    candidate = 'tightening-cloud-tunnel-check-' + str(int(time.time()))
    listener = run(['ss', '-H', '-lntp', 'sport = :18089'])
    pids = set(re.findall(r'pid=(\d+)', listener))
    old_pid = None
    old_command = None
    if listener:
        if len(pids) != 1 or '192.168.50.1:18089' not in listener:
            raise RuntimeError('Unexpected listener; will not stop it')
        old_pid = int(pids.pop())
        process = Path('/proc') / str(old_pid)
        old_command = process.joinpath('cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
        if process.stat().st_uid != 0 or not original_command(old_command):
            raise RuntimeError('Listener is not the previously identified manual tunnel')
    if run(['ss', '-H', '-lnt', 'sport = :18090']).strip():
        raise RuntimeError('Candidate loopback port already occupied; no changes')
    try:
        run(['systemd-run', '--unit=' + candidate, '--property=User=tightening-tunnel',
             '--property=Group=tightening-tunnel', '--property=RuntimeMaxSec=45',
             '--property=NoNewPrivileges=yes', '--property=ProtectSystem=strict',
             '--property=ProtectHome=yes', '--property=PrivateTmp=yes'] + SSH +
            ['-L', '127.0.0.1:18090:127.0.0.1:18088', 'root@118.25.40.152'])
        data = api('127.0.0.1:18090', token)
        print('Candidate dedicated key and API authentication PASS; stored=%d' % data['samples'], flush=True)
    finally:
        subprocess.run(['systemctl', 'stop', candidate + '.service'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if old_pid is not None:
        current = Path('/proc/%d/cmdline' % old_pid).read_bytes().rstrip(b'\0').decode().split('\0')
        if current != old_command:
            raise RuntimeError('Old tunnel identity changed; refusing to stop it')
        os.kill(old_pid, signal.SIGTERM)
        deadline = time.monotonic() + 8
        while Path('/proc/%d' % old_pid).exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        if Path('/proc/%d' % old_pid).exists():
            raise RuntimeError('Old tunnel did not stop; no SIGKILL used')
    run(['systemctl', 'enable', '--now', UNIT])
    api('192.168.50.1:18089', token)
    state = status()
    if state['ActiveState'] != 'active' or int(state['MainPID']) <= 0:
        raise RuntimeError('Managed tunnel is not running')
    print('ACTIVATE PASS: tunnel active/enabled; no manual password/window required.', flush=True)


def restart_test(token):
    if run(['systemctl', 'is-enabled', UNIT]).strip() != 'enabled':
        raise RuntimeError('Tunnel is not enabled; no fault injected')
    before = status()
    if before['ActiveState'] != 'active' or int(before['MainPID']) <= 0:
        raise RuntimeError('Tunnel is not active; no fault injected')
    baseline = api('192.168.50.1:18089', token)['samples']
    run(['systemctl', 'kill', '--kill-who=main', '--signal=SIGKILL', UNIT])
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        after = status()
        if (after['ActiveState'] == 'active' and int(after['MainPID']) > 0 and
                after['MainPID'] != before['MainPID'] and
                int(after['NRestarts']) > int(before['NRestarts'])):
            break
        time.sleep(0.5)
    else:
        raise RuntimeError('Automatic SSH restart not observed')
    current = api('192.168.50.1:18089', token)['samples']
    if current < baseline:
        raise RuntimeError('Server record count decreased')
    print('RESTART PASS: old_pid=%s new_pid=%s restarts=%s stored=%d' %
          (before['MainPID'], after['MainPID'], after['NRestarts'], current), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restart-test', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0 or not STATE.is_dir():
        raise RuntimeError('Prepared root LubanCat environment required')
    token = sys.stdin.read()
    if not 24 <= len(token) <= 128 or any(not 33 <= ord(c) <= 126 for c in token):
        raise RuntimeError('Private stdin token invalid; no secret displayed')
    if args.restart_test:
        restart_test(token)
    else:
        activate(token)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        detail = str(error) if type(error) is RuntimeError else type(error).__name__
        print('STOPPED: ' + detail + '; no secret displayed.', flush=True)
        sys.exit(1)
