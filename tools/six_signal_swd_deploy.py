"""B457 timeout-locked -> exact inactive-A signal fixture, drive OFF only.

Used only after the archived UART BEGIN rejection; never clear the timeout
fault to make an upgrade pass. ST-Link programs A only while reset/halted.
Protected Flash and metadata are verified BEFORE one SRAM START_TRIAL request.
The original bootloader verifies CRC/vector and the APP confirms its health.
No force-confirm, Flash metadata edit, bridge, PWM, zero sample or motion.
"""
import argparse
import json
import struct
import subprocess
import time
import zlib
from pathlib import Path

import six_signal_acceptance as profile
from feedback_safety_commit import Console as ReadConsole, fault_fields
from firmware_transfer_iap import fields, image_info
from zero_retest_deploy import compare_flash, require_confirmed, require_service
from tighten_synthetic_swd_recovery import OCD, SCRIPTS
from tighten_synthetic_acceptance import locked, require_stopped
from switch_feedback_timerfix_acceptance import guard_result

REJECTION = profile.OUTPUT/'deploy-1791892784088048500.json'


def rejection():
    row = json.loads(REJECTION.read_text('utf-8'))
    if (row.get('pass_') is not False or row.get('stage_attempted') is not True or
            row.get('commit_attempted') or row.get('image_sha256') != profile.SHA or
            row.get('failure') != '15007 ERR 105 FAULT'):
        raise RuntimeError('Exact archived BEGIN rejection required')
    return row


def mailbox(data):
    if image_info(data)[0] != 'A': raise ValueError('Inactive A only')
    # Command 2 START_TRIAL; never command 1 CONFIRM or 3 SET_CONFIRMED.
    packet = struct.pack('<7I',0x584F424D,1,2,2,1,len(data),zlib.crc32(data))
    return struct.unpack('<8I',packet+struct.pack('<I',zlib.crc32(packet)))


def safe_halt_commands():
    return ['init','halt','reset halt',
        'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted in bootloader"}',
        'mmw 0x4002104C 0x4 0','mww 0x48000818 0x00400000',
        'mmw 0x48000800 0x1000 0x2000','mmw 0x40021060 0x800 0',
        'mww 0x48000818 0x00400000','mww 0x40012C20 0',
        'mmw 0x40012C44 0 0xC000','mmw 0x40012C00 0 1']


OFF_PROOF = ('if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || '
             '[mrw 0x40012C00] & 1 || [mrw 0x40012C20]} {error "Output off proof failed"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-inactive-a',action='store_true')
    parser.add_argument('--drive-12v-off',action='store_true')
    parser.add_argument('--motor-disconnected',action='store_true')
    args = parser.parse_args()
    if not (args.allow_inactive_a and args.drive_12v_off and args.motor_disconnected):
        parser.error('Inactive-A flash/reset permission, physical drive OFF and motor disconnected required')
    import serial
    data = profile.image(); refusal = rejection()
    private = profile.OUTPUT/'private'
    if not private.is_dir(): parser.error('Existing private evidence directory required')
    run = str(time.time_ns()); output = profile.OUTPUT/f'swd-deploy-{run}.json'
    row = dict(pass_=False,image_sha256=profile.SHA,target_slot='A',bridge_enabled=False,
               pwm_enabled=False,adc_capture=False,motion_commands=False,force_confirm=False,
               direct_metadata_write=False,automatic_retry=False,motor_qualified=False,
               physical_drive_off_user_confirmed=True,motor_disconnected_user_confirmed=True,steps=[])
    port = uart = None
    def cli(*tokens):
        if not tokens or tokens[0] not in ('-u','-r32'): raise ValueError('Read-only CLI')
        proc = subprocess.run([profile.CLI,'-c','port=SWD','mode=HOTPLUG','freq=1000',
            'sn='+profile.SN,*map(str,tokens)],capture_output=True,text=True,errors='replace',timeout=30)
        out = proc.stdout+proc.stderr
        row['steps'].append(dict(tool='read-only-cli',args=list(map(str,tokens)),code=proc.returncode,output=out))
        if proc.returncode or 'Error:' in out: raise RuntimeError('Read failed; no retry')
        return out
    def capture(name):
        path = private/f'{run}-{name}.bin'; cli('-u','0x08000000','0x80000',path)
        raw = path.read_bytes(); row[name+'_backup'] = str(path)
        if len(raw) != 0x80000: raise RuntimeError('Incomplete private capture')
        return raw
    def registers(slot):
        return profile.require_registers(cli(*(x for a in profile.ADDRESSES for x in ('-r32',hex(a),'4'))),slot)
    def ocd(commands):
        proc = subprocess.run([OCD,'-s',SCRIPTS,'-f','interface/stlink.cfg','-f','target/stm32g4x.cfg',
            '-c','gdb_port disabled; tcl_port disabled; telnet_port disabled; adapter serial '+profile.SN+
            '; adapter speed 1000; '+'; '.join(commands)],capture_output=True,text=True,errors='replace',timeout=60)
        out = proc.stdout+proc.stderr
        row['steps'].append(dict(tool='OpenOCD',commands=commands,code=proc.returncode,output=out))
        print(out,flush=True)
        if proc.returncode or '** Programming Failed **' in out:
            raise RuntimeError('Controlled SWD failed; no blind reset or retry')
    try:
        before = capture('before'); row['baseline'] = profile.baseline(before)
        rejected_before = Path(refusal['before_backup']).resolve()
        if rejected_before.parent != private.resolve() or before != rejected_before.read_bytes():
            raise RuntimeError('Rejected BEGIN changed Flash; recovery refused')
        row['rejected_begin_all_flash_unchanged'] = True
        row['before_outputs'] = registers('B')
        port = serial.Serial(port=None,baudrate=115200,timeout=.02,write_timeout=2)
        port.dtr = port.rts = False; port.port = 'COM5'; port.open(); uart = ReadConsole(port)
        row['before_fw'] = require_confirmed(uart.query('FW STATUS'),'B')
        if row['before_fw'].get('GEN') != '457': raise RuntimeError('UART generation differs')
        require_stopped(uart.query('BENCH STATUS'))
        if not locked(fields(uart.query('ANALOG SAFE STATUS'))): raise RuntimeError('Latch absent')
        row['before_fault'] = fault_fields(uart.query('BENCH PROTECTION FAULT'))
        prior = json.loads(profile.REFERENCE.read_text('utf-8'))
        if row['before_fault'] != prior['final_fault']:
            raise RuntimeError('Fault changed since authorized timeout test; no reset')
        if row['before_fault'].get('VALID') != '1' or row['before_fault'].get('REASON') != '6':
            raise RuntimeError('Only preserved injected timeout admitted')
        row['before_timing'] = fields(uart.query('BENCH PROTECTION TIMING'))
        if row['before_timing'].get('TEST_USED') != '1': raise RuntimeError('Not the intentional stopped-stream test')
        # Store the previous fault before the reset; no fault-clear command.
        saved_uart = uart.lines; uart = profile.Console(port); uart.lines = saved_uart
        protected = []
        for name,start,end in (('boot',0,0x8000),('outside-a',0x40000,0x80000)):
            path = private/f'{run}-{name}.bin'; path.write_bytes(before[start:end])
            protected.append((start,path))
        staged_path = private/f'{run}-staged.bin'
        checks = [f'verify_image {{{profile.IMAGE.as_posix()}}} 0x08008000 bin']
        checks += [f'verify_image {{{path.as_posix()}}} {0x08000000+start:#x} bin' for start,path in protected]
        row['program_attempted'] = True
        ocd(safe_halt_commands()+[
            f'flash write_image erase {{{profile.IMAGE.as_posix()}}} 0x08008000 bin',*checks,
            f'dump_image {{{staged_path.as_posix()}}} 0x08000000 0x80000',OFF_PROOF,'shutdown'])
        row['staged_backup'] = str(staged_path)
        staged = staged_path.read_bytes()
        row['staged_flash'] = compare_flash(before,staged,data,'A',staged=True)
        if before[:0x8000] != staged[:0x8000] or before[0x40000:] != staged[0x40000:]:
            raise RuntimeError('Protected bytes differ; keep halted and drive OFF')
        row['all_bytes_outside_a_unchanged_before_trial'] = True
        print('SWD STAGE PASS: exact A; all other Flash including metadata unchanged; CPU halted',flush=True)
        words = mailbox(data)
        request = ['init','halt',
            'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not still halted in bootloader"}',
            *checks,OFF_PROOF,'mww 0x2001FFC0 0']
        request += [f'mww {0x2001FFC0+4*i:#x} {words[i]:#x}' for i in range(1,8)]
        request += [f'mww 0x2001FFC0 {words[0]:#x}','reset run','shutdown']
        row['trial_request_attempted'] = True
        ocd(request)
        row['confirmed'] = profile.observe(uart)
        row['before_guard_zero'] = require_service(uart.query('ZERO STATUS'))
        fresh = profile.signal_status(uart.query('SWITCH STATUS'))
        if fresh.get('ATTEMPTS') != '0' or fresh.get('N') != '0': raise RuntimeError('Not fresh fixture')
        row['start_guard'] = profile.signal_status(uart.query('SWITCH START GUARD'),mode=4)
        time.sleep(.25)
        row['guard_line'] = uart.query('SWITCH STATUS')
        profile.signal_status(row['guard_line'],mode=4)
        row['final_outputs'] = registers('A')
        row['final_fw'] = require_confirmed(uart.query('FW STATUS'),'A')
        row['final_zero'] = require_service(uart.query('ZERO STATUS'))
        row['final_flash'] = compare_flash(before,capture('final'),data,'A')
        if int(row['final_fw']['GEN']) != row['final_flash']['generation']:
            raise RuntimeError('UART/Flash generation mismatch')
        row['guard'] = guard_result(row['guard_line'])
        row['pass_'] = row['final_safe_locked'] = True
        print('SIGNAL FIXTURE DEPLOY/GUARD PASS: A confirmed; B457 preserved; SD/PWM OFF',flush=True)
    except BaseException as error:
        row['failure'] = str(error)
        if uart and row.get('trial_request_attempted'):
            try:
                fw = fields(uart.query('FW STATUS',2)); row['failure_fw'] = fw
                if fw.get('CURRENT') == 'A':
                    row['abort'] = profile.signal_status(uart.query('SWITCH ABORT'))
                    require_service(uart.query('ZERO STATUS'))
                elif fw.get('CURRENT') == 'B': require_stopped(uart.query('BENCH STATUS'))
                else: raise RuntimeError('Unknown slot')
                row['failure_outputs'] = registers(fw['CURRENT'])
                capture('failure'); row['failure_safe_locked'] = True
            except BaseException as cleanup: row['cleanup_failure'] = str(cleanup)
        raise
    finally:
        if uart: row['uart'] = uart.lines
        if port: port.close()
        output.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(output),flush=True)


if __name__ == '__main__': main()
