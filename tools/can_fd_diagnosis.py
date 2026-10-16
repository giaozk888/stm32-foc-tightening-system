"""Bounded diagnostic FD boot, using existing firmware; never sends CAN data.

The guard reuses the previously tested fail-closed rollback: restore the boot
file, but hold CAN/HMI DOWN until original MCU A has been normally confirmed.
MMIO mapping is read-only and restricted to this board's CAN controller page.
ERROR_CODE may clear on read: read it ONCE on the first fault, then stop CAN.
"""
import argparse
from collections import Counter
import errno
import json
import mmap
import os
from pathlib import Path
import select
import socket
import struct
import sys
import time

import can_fd_deploy as recovery

ROOT = Path('/root/codex-canfd-diagnosis-20261007')
BASE = 0xfe580000
REGISTERS = {'mode': 0x00, 'state': 0x08, 'interrupt': 0x0c,
             'interrupt_mask': 0x10, 'rx_errors': 0x34, 'tx_errors': 0x38,
             'nominal_timing': 0x100, 'data_timing': 0x104}
ERROR_CODE = 0x2c


def configure():
    recovery.ROOT = ROOT
    base = recovery.base
    base.ROOT = ROOT
    base.UNIT_NAME = 'codex-canfd-diagnosis-guard-20261007.service'
    base.UNIT = Path('/etc/systemd/system') / base.UNIT_NAME
    base.DROP_NAME = 'zzzzzzzzzzzz-codex-canfd-diagnosis-20261007.conf'
    base.DROPS = [Path('/etc/systemd/system') / (name + '.d') / base.DROP_NAME
                  for name in recovery.SERVICES]
    base.MARKER = ROOT / 'trial-active'
    base.TIMEOUT = 1200
    base.DROP_DATA = ('[Unit]\nConditionPathExists=!' + str(base.MARKER) + '\n').encode()
    base.UNIT_DATA = ('[Unit]\nDescription=Fail-closed bounded CAN FD diagnosis\n'
        'After=local-fs.target\n[Service]\nType=simple\nExecStart=/usr/bin/python3 '
        + str(ROOT / 'controller.py') + ' watchdog\nTimeoutStopSec=5\n'
        '[Install]\nWantedBy=multi-user.target\n').encode()
    # This experiment owns no production application or setup overrides.
    recovery.owned_files = lambda: []


def guarded_boot():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    if (recovery.base.boot_id() == manifest['original_boot_id'] or
            not recovery.base.MARKER.exists()):
        raise RuntimeError('Not in this guarded diagnostic boot')
    if recovery.setup.compatible() != recovery.setup.EXPECTED_COMPATIBLE:
        raise RuntimeError('Unexpected CAN compatible; no MMIO/traffic allowed')
    for service in recovery.SERVICES:
        if recovery.base.run('systemctl', 'is-active', service, check=False).stdout.strip() == 'active':
            raise RuntimeError('Application service unexpectedly running')


def prepare():
    if Path(__file__).resolve() != ROOT / 'controller.py':
        raise RuntimeError('Use exact independent controller path')
    for service in recovery.SERVICES:
        recovery.base.atomic_write(ROOT / (service + '.original.txt'),
            recovery.base.run('systemctl', 'cat', service).stdout.encode())
    recovery.base.prepare()
    print('DIAG PREPARED: 1200s rollback; restore original MCU A before releasing classic', flush=True)


class CanRegisters:
    def __init__(self):
        # /proc/iomem must identify this exact MMIO region as a CAN resource.
        resources = Path('/proc/iomem').read_text().splitlines()
        if not any(line.strip().startswith('fe580000-') and 'can' in line.lower()
                   for line in resources):
            raise RuntimeError('CAN physical resource not verified; no mapping')
        self.fd = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
        try:
            self.memory = mmap.mmap(self.fd, 4096, flags=mmap.MAP_SHARED,
                                    prot=mmap.PROT_READ, offset=BASE)
        except Exception:
            os.close(self.fd)
            raise
        self.error_read = False

    def read(self):
        return {name: struct.unpack_from('<I', self.memory, offset)[0]
                for name, offset in REGISTERS.items()}

    def first_error_code(self):
        if self.error_read:
            raise RuntimeError('ERROR_CODE must not be repeatedly consumed')
        self.error_read = True
        value = struct.unpack_from('<I', self.memory, ERROR_CODE)[0]
        names = {0: 'bit', 1: 'stuff', 2: 'form', 3: 'ack', 4: 'crc'}
        return {'raw': value, 'raw_hex': hex(value),
                'type_field': names.get((value >> 26) & 7, 'unknown'),
                'direction_rx': bool(value & (1 << 25)),
                'data_phase': bool(value & (1 << 29)),
                'receive_crc_segment': bool(value & (1 << 9)),
                'transmit_idle': bool(value & (1 << 16)),
                'location_bits': value & 0x1ffffff,
                'may_clear_on_read': True,
                'validity': 'zero raw value is NOT proof of a bit error'}

    def close(self):
        self.memory.close()
        os.close(self.fd)


def fault_reasons(registers, interface=None, error_frame=False):
    reasons = []
    if registers['state'] & (1 << 4): reasons.append('hardware_warning')
    if registers['state'] & (1 << 5): reasons.append('hardware_bus_off')
    if registers['rx_errors'] or registers['tx_errors']: reasons.append('hardware_error_counter')
    # Interrupt reads do not acknowledge them: the normal driver clears by write.
    if registers['interrupt'] & ((1 << 2) | (1 << 3) | (1 << 4) | (1 << 6) | (1 << 9)):
        reasons.append('hardware_error_interrupt')
    if error_frame: reasons.append('socketcan_error_frame')
    if interface:
        info = interface['linkinfo']['info_data']
        stats = interface['linkinfo'].get('info_xstats', {})
        if info.get('state') != 'ERROR-ACTIVE': reasons.append('software_state')
        if any(info.get('berr_counter', {}).values()): reasons.append('software_error_counter')
        if any(stats.get(k, 0) for k in ('bus_error', 'error_warning', 'error_passive', 'bus_off')):
            reasons.append('software_error_event')
    return reasons


def healthy_setup_notification(interface, registers, consumed):
    """Only one queued DOWN notification may be stale after a verified UP."""
    info = interface.get('linkinfo', {}).get('info_data', {})
    return (consumed == 0 and 'UP' in interface.get('flags', []) and
            interface.get('mtu') == 72 and set(info.get('ctrlmode', [])) == {'FD'} and
            info.get('bittiming', {}).get('bitrate') == 500000 and
            info.get('data_bittiming', {}).get('bitrate') == 500000 and
            not fault_reasons(registers, interface))


def monitor(seconds, permit, run_number=1):
    if not permit or not 30 <= seconds <= 300:
        raise RuntimeError('Explicit bounded isolated diagnostic permission required')
    if run_number not in (1, 2):
        raise RuntimeError('Only two separately preserved diagnostic runs allowed')
    guarded_boot()
    baseline = recovery.setup.inspect()
    if 'UP' in baseline.get('flags', []):
        raise RuntimeError('Collector must be armed before interface goes UP')
    suffix = '' if run_number == 1 else '2'
    output = ROOT / ('monitor' + suffix + '.jsonl')
    summary_path = ROOT / ('monitor' + suffix + '-summary.json')
    if output.exists() or summary_path.exists():
        raise RuntimeError('Fresh evidence required; never overwrite a prior run')
    summary = {'can_frames_sent': 0, 'read_only_mmio': True,
               'error_code_reads': 0, 'duration_limit': seconds,
               'baseline': baseline, 'counts': {}, 'error_frames': [], 'fault': None}
    bus = None
    registers = None
    saw_up = False
    start = None
    counts = Counter()
    arm_deadline = time.monotonic() + 90
    last_interface = 0.0
    first_fd = False
    latest = None
    setup_notifications = 0
    try:
        with output.open('x') as evidence:
            bus = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            bus.setsockopt(socket.SOL_CAN_RAW, 5, 1)  # CAN_RAW_FD_FRAMES
            bus.setsockopt(socket.SOL_CAN_RAW, 2, struct.pack('=I', 0x1fffffff))
            bus.bind(('can0',))
            bus.setblocking(False)
            print('MONITOR ARMED: socket receive-only; MMIO reads start after interface UP', flush=True)
            while True:
                now = time.monotonic()
                if now - last_interface >= .1:
                    latest = recovery.setup.inspect()
                    last_interface = now
                    evidence.write(json.dumps({'t': now, 'interface': latest}) + '\n')
                    evidence.flush()
                up = 'UP' in latest.get('flags', [])
                if not up:
                    if saw_up:
                        summary['end'] = 'interface_went_down'
                        break
                    if now >= arm_deadline:
                        raise RuntimeError('Interface did not become UP within arm limit')
                    time.sleep(.02)
                    continue
                if not saw_up:
                    saw_up = True
                    start = now
                    if latest.get('mtu') != 72 or set(latest['linkinfo']['info_data'].get('ctrlmode', [])) != {'FD'}:
                        raise RuntimeError('Unexpected UP profile; stopping interface')
                    registers = CanRegisters()
                    print('MONITOR ACTIVE: read-only CAN register whitelist; 10ms sampling', flush=True)
                raw_registers = registers.read()
                summary['last_registers'] = raw_registers
                evidence.write(json.dumps({'t': now, 'registers': raw_registers}) + '\n')
                error_seen = False
                for _ in range(100):
                    try:
                        raw = bus.recv(72)
                    except BlockingIOError:
                        break
                    except OSError as error:
                        if error.errno != errno.ENETDOWN:
                            raise
                        current = recovery.setup.inspect()
                        current_registers = registers.read()
                        if not healthy_setup_notification(current, current_registers, setup_notifications):
                            raise
                        setup_notifications += 1
                        evidence.write(json.dumps({'setup_notification': 'queued ENETDOWN',
                            'interface': current, 'registers': current_registers}) + '\n')
                        summary['stale_setup_notifications'] = setup_notifications
                        continue
                    cid, length = struct.unpack_from('=IB', raw)
                    if cid & 0x20000000:
                        error_seen = True
                        record = {'t': now, 'can_id': hex(cid), 'length': length, 'raw': raw.hex()}
                        summary['error_frames'].append(record)
                        evidence.write(json.dumps({'error_frame': record}) + '\n')
                    else:
                        form = 'FD' if len(raw) == 72 else 'classic'
                        counts[f'{form}:{cid & 0x1fffffff:03x}:{length}'] += 1
                        if form == 'FD' and not first_fd:
                            first_fd = True
                            summary['first_fd_time'] = now
                            print('FIRST FD FRAME RECEIVED', flush=True)
                reasons = fault_reasons(raw_registers, latest, error_seen)
                if reasons:
                    fault = {'t': now, 'elapsed_s': now - start, 'reasons': reasons,
                             'registers_before_error_read': raw_registers,
                             'interface': recovery.setup.inspect(),
                             'error_code': registers.first_error_code(),
                             'registers_after_error_read': registers.read()}
                    summary['error_code_reads'] = 1
                    summary['fault'] = fault
                    summary['end'] = 'first_fault'
                    evidence.write(json.dumps({'fault': fault}) + '\n')
                    evidence.flush()
                    print('FAULT CAPTURED: ' + json.dumps(fault), flush=True)
                    break
                if now - start >= seconds:
                    summary['end'] = 'bounded_timeout_no_fault'
                    break
                evidence.flush()
                select.select([bus], [], [], .01)
            summary['elapsed_s'] = time.monotonic() - start if start else 0
            summary['interface_before_stop'] = recovery.setup.inspect()
    except Exception as error:
        summary['capture_error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        # Close mapping before DOWN, since the driver can gate the CAN clock.
        if registers: registers.close()
        if bus: bus.close()
        if saw_up:
            recovery.base.run('ip', 'link', 'set', 'can0', 'down')
        summary['counts'] = dict(counts)
        summary['interface_after_stop'] = recovery.setup.inspect()
        recovery.base.atomic_write(summary_path, json.dumps(summary, indent=2).encode())
        print('MONITOR STOPPED: evidence retained; CAN DOWN; restore original MCU A before classic', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'ready', 'monitor', 'rollback',
        'watchdog', 'release-classic', 'verify-classic'))
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--run-number', type=int, choices=(1, 2), default=1)
    parser.add_argument('--permit-isolated-diagnosis', action='store_true')
    parser.add_argument('--original-mcu-a-confirmed', action='store_true')
    parser.add_argument('--reboot', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('Run only on the explicitly approved LubanCat')
    if args.reboot and args.command != 'rollback':
        parser.error('--reboot only applies to rollback')
    configure()
    {'prepare': prepare, 'ready': recovery.ready,
     'monitor': lambda: monitor(args.seconds, args.permit_isolated_diagnosis, args.run_number),
     'rollback': lambda: recovery.rollback(args.reboot), 'watchdog': recovery.watchdog,
     'release-classic': lambda: recovery.release_classic(args.original_mcu_a_confirmed),
     'verify-classic': recovery.base.verify_restored}[args.command]()


if __name__ == '__main__':
    main()
