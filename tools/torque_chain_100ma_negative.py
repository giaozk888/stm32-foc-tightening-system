"""One explicit -100mA/200ms probe of the already-staged A. Files only by default.

No programming, positive pulse, repeat, sign/angle/threshold change or START.
Separate OFF readback, powered normal A/B trial, then OFF restore-before-B-app.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib
import torque_chain_100ma_acceptance as positive

old=positive.old; TMP=positive.TMP; image=positive.image
ELF=positive.ELF; SHA=positive.SHA; ELF_SHA=positive.ELF_SHA
debug=positive.debug; check_off=positive.check_off; off_report=positive.off_report
full_compare_commands=positive.full_compare_commands; off_commands=positive.off_commands
write_mailbox=positive.write_mailbox; emergency_off=positive.emergency_off
BASE=TMP/'torque100-restore-1792331907180865800-flash.bin'
BASE_SHA='a43892c56ae93b5b6adceae89fbc1122664cd73b0a56b248629a29dc2428a514'
COMMAND='MOTOR TEST TORQUE NEG ZERO CONFIRM'


def baseline():
    raw=BASE.read_bytes(); original=positive.baseline(); data=image()
    if (len(raw)!=0x80000 or old.zero.digest(raw)!=BASE_SHA or
        old.zero.latest_meta(raw)[2:6]!=(2,0,0,677) or raw[0x8000:0x8000+len(data)]!=data or
        raw[:0x8000]!=original[:0x8000] or raw[0x40000:0x7e800]!=original[0x40000:0x7e800] or
        raw[0x7f800:]!=original[0x7f800:]): raise ValueError('Exact halted B677 / existing 100mA A required')
    return raw


def inspect(row,name,data):
    baseline(); capture=TMP/(name+'-flash.bin'); row['hardware_attempted']=True
    output=debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted B677"}',
        *full_compare_commands(capture,BASE),*off_report(),'halt','shutdown'])
    raw=capture.read_bytes()
    row.update(pass_=True,inspection_capture=str(capture),inspection_sha256=old.zero.digest(raw),
        outputs=check_off(output,(0x08040000,)),programming_attempted=False,activation=False,
        final_cpu_halted=True,final_outputs_off=True,all_app_private_unchanged=True)


def inspection_receipt(path,data):
    r=json.loads(path.read_text('utf-8')); capture=Path(r.get('inspection_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
        r.get('mode')!='inspect' or r.get('pass_') is not True or r.get('iq_command_mA')!=-100 or
        r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
        not r.get('physical_power_off') or not r.get('motor_connected_fixed') or
        r.get('programming_attempted') is not False or r.get('activation') is not False):
        raise ValueError('Exact OFF negative inspection required')
    raw=capture.read_bytes()
    if old.zero.digest(raw)!=r.get('inspection_sha256') or raw!=baseline():
        raise ValueError('Negative inspection capture changed')
    return capture,raw


class NegativeConsole(old.prior.JournalConsole):
    def torque(self,command,timeout=1.0):
        if command not in (COMMAND,'MOTOR TEST TORQUE STATUS'):
            raise ValueError('Negative one-shot/status only; no positive pulse or sweep')
        if command==COMMAND:
            if self.row.get('pulse_attempts',0): raise RuntimeError('No second pulse or ACK retry')
            self.row['pulse_attempts']=1
            old.prior.checkpoint(self.row,'negative_pulse_intent')
        self.request+=1; request=self.request
        self.row['commands'].append(dict(command=command,at=time.monotonic()))
        self.port.write(f'{request} {command}\r\n'.encode('ascii'))
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            line=self.read_line(.02)
            if line is None: continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '): raise RuntimeError(line)
                return line
        raise TimeoutError('No ACK; outcome unknown, no retry')


def execute(row,name,path,data):
    inspected,before=inspection_receipt(path,data)
    port=old.prior.open_port(); uart=NegativeConsole(port,row)
    try:
        body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
        mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
        row['hardware_attempted']=True; old.prior.checkpoint(row,'trial_request_intent')
        debug(row,[*old.zero.off_gate(),*full_compare_commands(TMP/(name+'-pretrial.bin'),inspected),
            'reset halt',*off_commands(),*write_mailbox(mailbox),'reset run','shutdown'])
        row['trial_requests']=1; old.prior.wait_health_confirmation(uart,row,positive.fields)
        positive.preflight(uart,row); old.prior.checkpoint(row,'preflight_pass')
        row['pulse_ack']=uart.torque(COMMAND)
        time.sleep(.35) # Independent board lease owns stopping; no live motion polling.
        row['postflight_state']=positive.fields(uart.query('MOTOR TEST STATUS'))
        row['torque_postflight']=positive.fields(uart.torque('MOTOR TEST TORQUE STATUS'))
    finally:
        if row.get('hardware_attempted'):
            try:
                row['stop_ack']=uart.query('STOP',.6)
                row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as error: row['stop_error']=str(error)
        if port.is_open: port.close()
        if row.get('hardware_attempted'): old.capture_stopped(row,name,before,elf=ELF)
    if not row.get('snapshot'): raise RuntimeError('No matching 100mA A snapshot')
    positive.classify(row,Path(row['ram_capture']).read_bytes(),expected_sign=-1)


def main():
    p=argparse.ArgumentParser(description=__doc__); m=p.add_mutually_exclusive_group()
    m.add_argument('--inspect-off',action='store_true'); m.add_argument('--execute-negative',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-connected-fixed',action='store_true')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    a=p.parse_args()
    if (a.inspect_off or a.restore_b_drive_off) and not a.drive_off_connected_fixed: p.error('Fresh drive OFF required')
    if a.execute_negative and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready: p.error('Fresh powered readiness required')
    data=image(); baseline()
    if not (a.inspect_off or a.execute_negative or a.restore_b_drive_off):
        print('OFFLINE PASS: exact same 100mA A / B677; no programming or devices'); return 0
    mode='inspect' if a.inspect_off else 'run' if a.execute_negative else 'restore'
    name='torque100-negative-'+mode+'-'+str(time.time_ns()); receipt=TMP/(name+'.json')
    row=dict(mode=mode,pass_=False,image_sha256=SHA,elf_sha256=ELF_SHA,pulse_attempts=0,
        automatic_retry=False,physical_power_off=a.drive_off_connected_fixed,motor_connected_fixed=True,
        iq_command_mA=-100,board_lease_us=200000,steps=[],commands=[],receipt_path=str(receipt))
    old.prior.checkpoint(row,'prepared_no_pulse')
    try:
        if a.inspect_off: inspect(row,name,data)
        elif a.execute_negative: execute(row,name,a.execute_negative,data)
        else: positive.restore(row,name,a.restore_b_drive_off,data)
    except Exception as error:
        row.update(pass_=False,failure=str(error)); old.prior.checkpoint(row,'failed')
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    old.prior.checkpoint(row,'complete' if row['pass_'] else 'failed')
    print(('PASS: ' if row['pass_'] else 'FAIL: ')+str(receipt),flush=True)
    if row.get('failure'): print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
