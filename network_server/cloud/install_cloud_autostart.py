"""Self-contained ZIP entrypoint for the already-deployed Tencent backend.

Default is CHECK ONLY. --install performs the requested service migration.
Never reads shell history, prints secrets, changes SSH daemon policy, or opens
public ports. Existing database is snapshotted after stopping its exact owner.
Compatible with Python 3.8 on Ubuntu 20.04.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from urllib.request import Request, urlopen
import zipfile

SOURCE = Path('/root/tightening-cloud-Q9UdUB')
APP = Path('/opt/tightening-observations')
STATE = Path('/var/lib/tightening-observations')
ENV = Path('/etc/tightening-observations.env')
UNIT = Path('/etc/systemd/system/tencent-observations.service')
AUTH = Path('/root/.ssh/authorized_keys')
USER = 'tightening'
FILES = ('__init__.py', 'server.py', 'schema.py', 'store.py',
         'index.html', 'app.js', 'style.css')


def run(args, **kwargs):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, **kwargs)


def secret_file(path, data):
    # New files only: no overwrite of existing configuration or secrets.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def summary(token):
    request = Request('http://127.0.0.1:18088/api/v1/summary',
                      headers={'Authorization': 'Bearer ' + token})
    with urlopen(request, timeout=5) as response:
        data = json.load(response)
    if data.get('control_enabled') is not False:
        raise RuntimeError('Unexpected control-enabled endpoint')
    return data


def preflight():
    if os.geteuid() != 0 or platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise RuntimeError('Run only in the root Tencent Ubuntu terminal, not LubanCat')
    for path in (APP, STATE, ENV, UNIT):
        if path.exists() or path.is_symlink():
            raise RuntimeError('Managed target already exists: ' + str(path))
    try:
        pwd.getpwnam(USER)
    except KeyError:
        pass
    else:
        raise RuntimeError('Service user already exists; inspect existing installation')
    listener = run(['ss', '-H', '-lntp', 'sport = :18088'], text=True).stdout
    if not listener or any('127.0.0.1:18088' not in line for line in listener.splitlines()):
        raise RuntimeError('Expected loopback-only listener missing')
    pids = set(re.findall(r'pid=(\d+)', listener))
    if len(pids) != 1:
        raise RuntimeError('Cannot identify exactly one backend owner')
    pid = int(pids.pop())
    process = Path('/proc') / str(pid)
    args = process.joinpath('cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
    if process.stat().st_uid != 0 or process.joinpath('cwd').resolve() != SOURCE:
        raise RuntimeError('Listener owner/source mismatch; do not stop it')
    if args[1:3] != ['-m', 'network_server.server'] or '--port' not in args or '--bind' not in args:
        raise RuntimeError('Unexpected listener command')
    if args[args.index('--port') + 1] != '18088' or args[args.index('--bind') + 1] != '127.0.0.1':
        raise RuntimeError('Unexpected listener address')
    allowed = {'--port', '--bind', '--db'}
    tail = args[3:]
    if len(tail) % 2 or any(tail[i] not in allowed for i in range(0, len(tail), 2)):
        raise RuntimeError('Unexpected backend options')
    values = [item[len(b'TIGHTEN_API_TOKEN='):]
              for item in process.joinpath('environ').read_bytes().split(b'\0')
              if item.startswith(b'TIGHTEN_API_TOKEN=')]
    if len(values) != 1:
        raise RuntimeError('Existing backend token unavailable; no migration')
    token = values[0].decode('ascii')
    if not 24 <= len(token) <= 128 or any(not 33 <= ord(c) <= 126 for c in token):
        raise RuntimeError('Invalid existing token')
    database = SOURCE / (args[args.index('--db') + 1] if '--db' in args else 'network_data/observations.sqlite3')
    database = database.resolve()
    if SOURCE not in database.parents or not database.is_file():
        raise RuntimeError('Database outside the known deployment or missing')
    for filename in FILES:
        path = SOURCE / 'network_server' / filename
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Missing/indirect source file: ' + filename)
    if AUTH.is_symlink() or AUTH.parent.is_symlink():
        raise RuntimeError('Unexpected indirect SSH authorization path')
    ssh_options = run(['/usr/sbin/sshd', '-T'], text=True).stdout
    if 'gatewayports no\n' not in ssh_options:
        raise RuntimeError('Remote forwarding is not loopback constrained; refuse key install')
    with zipfile.ZipFile(sys.argv[0]) as bundle:
        public = bundle.read('cloud_tunnel.pub').decode('ascii').strip()
        unit = bundle.read('tencent-observations.service')
    parts = public.split()
    if len(parts) != 3 or parts[0] != 'ssh-ed25519' or len(base64.b64decode(parts[1], validate=True)) != 51:
        raise RuntimeError('Invalid dedicated public key')
    # Only this loopback service; no shell/PTY/agent/X11/user-rc. Reverse
    # forwarding is limited to this same loopback endpoint (not public).
    key_line = ('restrict,port-forwarding,permitopen="127.0.0.1:18088",'
                'permitlisten="127.0.0.1:18088",command="/bin/false" ' + public + '\n').encode()
    original_auth = AUTH.read_bytes() if AUTH.exists() else b''
    if parts[1].encode() in original_auth:
        raise RuntimeError('Dedicated key already installed; refusing duplicate')
    data = summary(token)
    run([sys.executable, '-m', 'unittest', 'discover', '-s', 'network_server/tests',
         '-p', 'test_server.py', '-q'], cwd=str(SOURCE))
    print('CHECK PASS: exact backend PID=%d; existing records=%d; token not displayed.' % (pid, data['samples']))
    return pid, args, token, database, unit, key_line, original_auth


def install(info):
    pid, args, token, database, unit, key_line, original_auth = info
    backup = Path('/root/tencent-observations-autostart-backup-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(mode=0o700)
    secret_file(backup / 'authorized_keys.before', original_auth)
    secret_file(backup / 'source-info.json', json.dumps({'source': str(SOURCE), 'database': str(database), 'pid': pid}).encode())
    stopped = False
    key_added = False
    migrated = False
    try:
        run(['useradd', '--system', '--user-group', '--home-dir', str(STATE),
             '--shell', '/usr/sbin/nologin', USER])
        account = pwd.getpwnam(USER)
        APP.joinpath('network_server').mkdir(parents=True, mode=0o755)
        for filename in FILES:
            dest = APP / 'network_server' / filename
            shutil.copyfile(str(SOURCE / 'network_server' / filename), str(dest))
            os.chmod(str(dest), 0o644)
        STATE.mkdir(mode=0o700)
        os.chown(str(STATE), account.pw_uid, account.pw_gid)
        # systemd EnvironmentFile double-quoted values, not shell expansion.
        escaped = token.replace('\\', '\\\\').replace('"', '\\"')
        secret_file(ENV, ('TIGHTEN_API_TOKEN="' + escaped + '"\n').encode('ascii'))
        secret_file(UNIT, unit)
        os.chmod(str(UNIT), 0o644)
        run(['systemd-analyze', 'verify', str(UNIT)])
        run(['systemctl', 'daemon-reload'])
        # Recheck command identity immediately before stopping the known PID.
        current = Path('/proc/%d/cmdline' % pid).read_bytes().rstrip(b'\0').decode().split('\0')
        if current != args:
            raise RuntimeError('Listener identity changed; not stopping')
        os.kill(pid, signal.SIGINT)
        stopped = True
        deadline = time.monotonic() + 12
        while Path('/proc/%d' % pid).exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        if Path('/proc/%d' % pid).exists():
            raise RuntimeError('Old process did not stop; no SIGKILL used')
        # Snapshot final durable DB, including WAL; never copy a live DB file.
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as src:
            saved = int(src.execute('SELECT COUNT(*) FROM observations').fetchone()[0])
            with sqlite3.connect(str(STATE / 'observations.sqlite3')) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Database integrity check failed')
                if dst.execute('SELECT COUNT(*) FROM observations').fetchone()[0] != saved:
                    raise RuntimeError('Snapshot record count mismatch')
            migrated = True
            with sqlite3.connect(str(backup / 'observations.sqlite3')) as dst:
                src.backup(dst)
        for path in (STATE / 'observations.sqlite3', backup / 'observations.sqlite3'):
            os.chmod(str(path), 0o600)
        os.chown(str(STATE / 'observations.sqlite3'), account.pw_uid, account.pw_gid)
        run(['systemctl', 'start', 'tencent-observations.service'])
        deadline = time.monotonic() + 10
        while True:
            try:
                data = summary(token)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Managed backend health/auth did not recover')
                time.sleep(0.3)
        if data['samples'] < saved:
            raise RuntimeError('Existing records were not preserved')
        AUTH.parent.mkdir(mode=0o700, exist_ok=True)
        # Preserve all unrelated authorization lines; append only our key.
        with AUTH.open('ab') as stream:
            if original_auth and not original_auth.endswith(b'\n'):
                stream.write(b'\n')
            stream.write(key_line)
            stream.flush()
            os.fsync(stream.fileno())
        key_added = True
        os.chmod(str(AUTH), 0o600)
        run(['systemctl', 'enable', 'tencent-observations.service'])
        print('INSTALL PASS: backend active/enabled; records preserved=%d; control locked.' % saved)
        print('Dedicated restricted tunnel public key installed; no SSH daemon configuration changed.')
        print('Private backup retained at ' + str(backup))
        print('No API token printed, no public port opened, no motor action performed.')
    except Exception:
        subprocess.run(['systemctl', 'disable', '--now', 'tencent-observations.service'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if key_added:
            # Remove only the just-added line, not other users' keys.
            AUTH.write_bytes(b''.join(line for line in AUTH.read_bytes().splitlines(keepends=True)
                                      if line != key_line))
            os.chmod(str(AUTH), 0o600)
        if stopped and not Path('/proc/%d' % pid).exists():
            if migrated:
                # The managed backend may already have acknowledged new rows.
                # Bring those back before restarting the old backend; never
                # silently return to a pre-cutover snapshot and lose ACKed data.
                with sqlite3.connect((STATE / 'observations.sqlite3').as_uri() + '?mode=ro', uri=True) as src:
                    with sqlite3.connect(str(database)) as dst:
                        src.backup(dst)
            log = (backup / 'foreground-recovery.log').open('ab')
            subprocess.Popen(args, cwd=str(SOURCE),
                             env={'TIGHTEN_API_TOKEN': token, 'PATH': '/usr/bin:/bin', 'PYTHONUNBUFFERED': '1'},
                             stdout=log, stderr=log, start_new_session=True)
            log.close()
            print('Fallback: original backend relaunched against original database; inspect health.')
        print('Installation incomplete; retained generated files and backups for diagnosis. Do not rerun blindly.')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    try:
        info = preflight()
        if args.install:
            install(info)
        else:
            print('CHECK ONLY: no configuration, service, key or process changed. Use --install to migrate.')
    except Exception as error:
        # Do not print exception strings: a transport exception can contain
        # request context. Token values never appear in tracebacks or argv.
        detail = str(error) if type(error) is RuntimeError else type(error).__name__
        print('STOPPED: ' + detail + '; no secret displayed. Check targeted preflight or service logs.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
