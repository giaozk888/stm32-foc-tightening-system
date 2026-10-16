"""Run on LubanCat as root. Prepare only: never stop the user's live tunnel.

Creates one private service identity and one project-specific SSH key. Copies
only the existing trusted cloud host entry; does not weaken host verification.
"""
import os
import pathlib
import pwd
import subprocess

STATE = pathlib.Path('/var/lib/tightening-cloud-tunnel')
USER = 'tightening-tunnel'
UNIT = pathlib.Path('/etc/systemd/system/tightening-cloud-tunnel.service')
UNIT_TEXT = '''[Unit]
Description=Restricted SSH tunnel for tightening observations
Wants=network-online.target
After=network-online.target NetworkManager.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=tightening-tunnel
Group=tightening-tunnel
ExecStart=/usr/bin/ssh -F /dev/null -NT -i /var/lib/tightening-cloud-tunnel/id_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/var/lib/tightening-cloud-tunnel/known_hosts -o ExitOnForwardFailure=yes -o ConnectTimeout=8 -o ConnectionAttempts=1 -o ServerAliveInterval=10 -o ServerAliveCountMax=3 -L 192.168.50.1:18089:127.0.0.1:18088 root@118.25.40.152
Restart=always
RestartSec=5
TimeoutStopSec=10
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

[Install]
WantedBy=multi-user.target
'''


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Root required on LubanCat')
    if STATE.exists() or UNIT.exists():
        raise RuntimeError('Managed paths already exist; inspect rather than overwrite')
    try:
        pwd.getpwnam(USER)
    except KeyError:
        pass
    else:
        raise RuntimeError('User already exists; refusing to reuse an unrelated identity')
    trusted = subprocess.run(
        ['ssh-keygen', '-F', '118.25.40.152', '-f', '/root/.ssh/known_hosts'],
        check=True, stdout=subprocess.PIPE, text=True).stdout
    host_lines = [line for line in trusted.splitlines() if line and not line.startswith('#')]
    if not host_lines:
        raise RuntimeError('Cloud host is not already trusted; no keys generated')
    subprocess.run(['useradd', '--system', '--user-group', '--home-dir', str(STATE),
                    '--shell', '/usr/sbin/nologin', USER], check=True)
    account = pwd.getpwnam(USER)
    STATE.mkdir(mode=0o700)
    os.chown(str(STATE), account.pw_uid, account.pw_gid)
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '',
                    '-C', 'tightening-cloud-tunnel-20261001',
                    '-f', str(STATE / 'id_ed25519')], check=True)
    (STATE / 'known_hosts').write_text('\n'.join(host_lines) + '\n', encoding='ascii')
    for filename in ('id_ed25519', 'id_ed25519.pub', 'known_hosts'):
        path = STATE / filename
        os.chmod(str(path), 0o600)
        os.chown(str(path), account.pw_uid, account.pw_gid)
    UNIT.write_text(UNIT_TEXT, encoding='ascii')
    os.chmod(str(UNIT), 0o644)
    subprocess.run(['systemd-analyze', 'verify', str(UNIT)], check=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    print('PREPARED ONLY: service not enabled or started; original tunnel unchanged.')
    print('Public key (not a private key):')
    print((STATE / 'id_ed25519.pub').read_text().strip())


if __name__ == '__main__':
    main()
