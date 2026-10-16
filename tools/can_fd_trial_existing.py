"""Normally trial the previously verified, inactive CAN FD B; no Flash write.

Only the bootloader's CRC-protected START_TRIAL mailbox and a reset are used.
Full Flash evidence must be in an already ACL-restricted private directory.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.can_fd_restore_original_slot import latest_meta, CLI, SN
from tools.router_transfer_concurrency_live import Console

B_SHA = 'fc232ac7adbae15b8eeec7bda2896844ea06a5a02dd8a7d084afbf3e96402c83'
A_SHA = '963589881051138ce1d8fae0e25b7a3c4999306f11812fe92efd2f35bcb94fcc'


def validate_flash(data):
    if len(data) != 0x80000: raise RuntimeError('Incomplete Flash capture')
    meta = latest_meta(data)
    if meta[2:5] != (1, 0, 0): raise RuntimeError('Require confirmed A, no pending trial')
    for slot, offset, size, crc, expected in (
            ('A', 0x8000, meta[6], meta[7], A_SHA),
            ('B', 0x40000, meta[8], meta[9], B_SHA)):
        if not 8 <= size <= 0x38000: raise RuntimeError('Invalid slot size')
        image = data[offset:offset+size]
        if zlib.crc32(image) != crc or hashlib.sha256(image).hexdigest() != expected:
            raise RuntimeError('Unexpected existing ' + slot + ' image; never write/boot it')
    return meta


def mailbox(meta):
    # START_TRIAL is requested from confirmed A (1) to inactive B (2).
    # The bootloader correctly rejects requester == target.
    head = struct.pack('<7I', 0x584f424d, 1, 2, 1, 2, meta[8], meta[9])
    return struct.unpack('<8I', head + struct.pack('<I', zlib.crc32(head)))


async def run(args):
    evidence = args.evidence.resolve()
    capture = args.capture.resolve()
    if not evidence.is_relative_to(ROOT / 'safety_backups') or not capture.is_relative_to(ROOT / 'safety_backups'):
        raise RuntimeError('Evidence must remain inside safety_backups')
    if evidence.exists() or capture.exists() or not capture.parent.is_dir():
        raise RuntimeError('Fresh evidence and pre-existing restricted capture directory required')
    evidence.mkdir(parents=True)
    report = {'pass': False, 'flash_written': False, 'force_confirm': False,
              'mailbox_written': False, 'motor_commands_sent': False, 'swd': []}
    console = None
    def cli(*parameters):
        process = subprocess.run([CLI, '-c', 'port=SWD', 'mode=HOTPLUG', 'freq=1000', 'sn='+SN,
            *map(str, parameters)], capture_output=True, text=True, timeout=30)
        output = process.stdout + process.stderr
        report['swd'].append({'args': list(map(str, parameters)), 'code': process.returncode,
                              'output': output})
        if process.returncode or 'Error:' in output: raise RuntimeError(output)
        return output
    def read(address):
        output = cli('-r32', hex(address), '4')
        found = re.search(rf'0x{address:08X}\s*:\s*([0-9a-f]{{8}})', output, re.I)
        if not found: raise RuntimeError('SWD safety register unavailable')
        return int(found[1], 16)
    try:
        console = Console(args.port, evidence)
        fw = (await console.request('FW STATUS'))[0]
        safe = (await console.request('ANALOG SAFE STATUS'))[0]
        if not all(f in fw for f in ('CURRENT=A','CONFIRMED=A','PENDING=-','ACTIVE=0')):
            raise RuntimeError('Require original confirmed A')
        if 'LATCHED=1 SD=0 MOE=0 FOC=0' not in safe: raise RuntimeError('Power-off latch missing')
        if read(0xe000ed08) != 0x08008000 or read(0x48000814) & 0x40 or read(0x40012c44) & 0x8000:
            raise RuntimeError('Running slot or power-off register check failed')
        cli('-u', '0x08000000', '0x80000', capture)
        meta = validate_flash(capture.read_bytes())
        report['before_metadata'] = list(meta)
        report['existing_images_verified'] = True
        print('EXISTING A/B VERIFIED: no application/bootloader Flash write', flush=True)
        if args.activate:
            if not args.permit_isolated_trial:
                raise RuntimeError('Explicit reset/trial permission required')
            proof_path = args.ready_proof.resolve()
            if (not proof_path.is_relative_to(ROOT / 'safety_backups') or
                    abs(time.time() - proof_path.stat().st_mtime) > 45):
                raise RuntimeError('Fresh independently captured FD readiness proof required')
            proof = json.loads(proof_path.read_text())
            interface = proof['after']
            info = interface['linkinfo']['info_data']
            if (proof['compatible'] != 'rockchip,canfd-1.0' or interface['mtu'] != 72 or
                    'UP' not in interface['flags'] or info['state'] != 'ERROR-ACTIVE' or
                    set(info['ctrlmode']) != {'FD'} or info['bittiming']['bitrate'] != 500000 or
                    info['data_bittiming']['bitrate'] != 500000 or any(info['berr_counter'].values()) or
                    any(interface['linkinfo']['info_xstats'].get(k,0) for k in
                        ('bus_error','error_warning','error_passive','bus_off'))):
                raise RuntimeError('FD counterpart is not proven healthy; no reset')
            words = mailbox(meta)
            cli('-w32','0x2001ffc0','0','-w32','0x2001ffc4',*map(hex,words[1:]),
                '-w32','0x2001ffc0',hex(words[0]),'-rst')
            report['mailbox_written'] = True
            print('EXISTING B TRIAL REQUESTED: normal bootloader validation/health confirmation only', flush=True)
            deadline = time.monotonic()+70
            while time.monotonic()<deadline:
                try: fw=(await console.request('FW STATUS'))[0]
                except TimeoutError: continue
                if all(f in fw for f in ('CURRENT=B','CONFIRMED=B','PENDING=-','ATTEMPTS=0','ACTIVE=0')):
                    break
                await asyncio.sleep(1)
            else: raise RuntimeError('Normal B confirmation not proven; no force-confirm')
            safe=(await console.request('ANALOG SAFE STATUS'))[0]
            if 'LATCHED=1 SD=0 MOE=0 FOC=0' not in safe: raise RuntimeError('Trial power-off not proven')
            await console.request('BENCH STATUS')
        report.update(pass_=True, fw=fw, safe=safe)
        report['pass']=report.pop('pass_')
    finally:
        if console: console.close()
        (evidence/'trial.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',required=True,type=Path)
    parser.add_argument('--capture',required=True,type=Path)
    parser.add_argument('--ready-proof',type=Path)
    parser.add_argument('--activate',action='store_true')
    parser.add_argument('--permit-isolated-trial',action='store_true')
    parser.add_argument('--port',default='COM5')
    args=parser.parse_args()
    if args.activate and (not args.permit_isolated_trial or not args.ready_proof):
        parser.error('Activation requires explicit permission and counterpart readiness proof')
    asyncio.run(run(args))
