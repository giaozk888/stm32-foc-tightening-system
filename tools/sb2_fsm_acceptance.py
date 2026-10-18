"""One SB2 no-load full state-machine observation, NOT tightening qualification.

Reuse the original full-cycle runner without changing firmware or thresholds.
Default is files only; inspect is drive OFF; execution needs fresh powered
readiness and an exact inspection. Preserve the independent 12s board lease.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import sb2_speed_acceptance as sb2
import loaded_fsm_motion as fsm
from firmware_transfer_iap import fields
from latest_original_fsm_stage import full_compare_commands, off_commands, write_mailbox
from original_closed_loop_updated_stage import debug, off_report, check_off
from original_closed_loop_trial import emergency_off

TMP=sb2.TMP
BASE=TMP/'sb2-speed-restore-1792312229610595100-flash.bin'
BASE_SHA='bdc7540b9419061016315fdaf0269959973c167b31a0940ea39862034609f701'


def baseline(data):
    raw=BASE.read_bytes(); old=sb2.baseline()
    if (len(raw)!=0x80000 or sb2.zero.digest(raw)!=BASE_SHA or
            sb2.zero.latest_meta(raw)[2:6]!=(2,0,0,653) or
            raw[0x8000:0x8000+len(data)]!=data or raw[:0x8000]!=old[:0x8000] or
            raw[0x40000:0x7e800]!=old[0x40000:0x7e800] or raw[0x7f800:]!=old[0x7f800:]):
        raise ValueError('Exact preserved halted B653 with SB2 already in A required')
    return raw


class JournalBoard(fsm.RecordedBoard):
    """Durable START intent prevents silent repeat after an ambiguous ACK."""
    def send(self,command):
        if command=='START':
            if self.record.get('start_attempts',0):
                raise RuntimeError('Second START prohibited')
            self.record['start_attempts']=1
            sb2.prior.checkpoint(self.record,'START_ATTEMPT')
        result=super().send(command)
        if command=='START':
            self.record['start_request_id']=result
            sb2.prior.checkpoint(self.record,'START_SENT')
        return result

    def read_line(self,seconds=.02):
        line=super().read_line(seconds)
        if line is not None:
            sb2.prior.checkpoint(self.record,'cycle_feedback')
        return line


def inspect(row,name,data):
    baseline(data); path=TMP/(name+'-inspection-flash.bin')
    row['hardware_attempted']=True
    output=debug(row,[*sb2.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted B653"}',
        *full_compare_commands(path,BASE),*off_report(),'shutdown'])
    row.update(pass_=True,inspection_capture=str(path),inspection_sha256=BASE_SHA,
        outputs=check_off(output,(0x08040000,)),no_reset=True,no_programming=True,
        final_cpu_halted=True,final_outputs_off=True)


def inspection_receipt(path,data):
    raw=baseline(data); r=json.loads(path.read_text('utf-8'))
    captured=Path(r.get('inspection_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or captured.parent!=TMP.resolve() or
            r.get('mode')!='inspect' or r.get('pass_') is not True or
            r.get('image_sha256')!=sb2.SHA or r.get('elf_sha256')!=sb2.ELF_SHA or
            r.get('inspection_sha256')!=BASE_SHA or captured.read_bytes()!=raw or
            not r.get('physical_power_off') or not r.get('motor_connected_fixed') or
            r.get('test_kind')!='NO_LOAD_STATE_MACHINE_ONLY'):
        raise ValueError('Exact OFF inspection required before full-state-machine test')
    return captured,raw


def execute(row,name,path,data):
    inspected,before=inspection_receipt(path,data)
    port=sb2.prior.open_port(); uart=sb2.prior.JournalConsole(port,row)
    try:
        body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
        mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
        row['hardware_attempted']=True
        sb2.prior.checkpoint(row,'trial_request_intent')
        debug(row,[*sb2.zero.off_gate(),
            *full_compare_commands(TMP/(name+'-pretrial.bin'),inspected),
            'reset halt',*off_commands(),*write_mailbox(mailbox),'reset run','shutdown'])
        row['trial_requests']=1; row['reset_attempts']=1
        sb2.prior.checkpoint(row,'trial_request_submitted')
        sb2.prior.wait_health_confirmation(uart,row,fields)
        row['preflight_zero']=sb2.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        fsm.check_profile(fields(uart.query('MOTOR TEST PROFILE')),'SB2')
        sb2.prior.wait_timing(uart,row)
        sb2.prior.checkpoint(row,'preflight_pass')
        port.close()
        board=JournalBoard('COM5',row)
        try:
            fsm.execute(board,row,'A',expected_speed_ctrl='SB2')
            sb2.prior.checkpoint(row,'cycle_completed_outputs_off')
        finally: board.close()
    finally:
        if port.is_open: port.close()
        row['startup_uart']=uart.lines
        if row.get('hardware_attempted'): sb2.capture_stopped(row,name,before)
    snap=row.get('snapshot')
    if (not snap or snap['first_fault']['valid'] or snap['timing']['deadline_miss'] or
            snap['timing']['actual_late_count']):
        raise RuntimeError('Postflight snapshot/protection/timing failure')
    row['state_machine_pass']=bool(row.get('cycle_pass'))
    row['pass_']=row['state_machine_pass']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--inspect-off',action='store_true')
    mode.add_argument('--execute-powered',type=Path)
    mode.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-connected-fixed',action='store_true')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    a=p.parse_args()
    if (a.inspect_off or a.restore_b_drive_off) and not a.drive_off_connected_fixed:
        p.error('Actual drive OFF and fixed/connected no-load motor required')
    if a.execute_powered and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready:
        p.error('Powered no-alarm fixed no-load motor, 0.5A and emergency OFF required')
    data=sb2.image(); baseline(data)
    if not(a.inspect_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: exact SB2 A / preserved B653; no hardware'); return 0
    mode='inspect' if a.inspect_off else 'fsm' if a.execute_powered else 'restore'
    name='sb2-fsm-'+mode+'-'+str(time.time_ns()); path=TMP/(name+'.json')
    row=dict(mode=mode,pass_=False,image_sha256=sb2.SHA,elf_sha256=sb2.ELF_SHA,
        test_kind='NO_LOAD_STATE_MACHINE_ONLY',tightening_qualified=False,
        torque_accuracy_verified=False,automatic_retry=False,start_attempts=0,
        host_limit_seconds=fsm.HOST_MAX_SECONDS,board_lease_us=12000000,
        motor_connected_fixed=True,physical_power_off=bool(a.drive_off_connected_fixed),
        flash_programming=False,steps=[],commands=[],uart=[],samples=[],postflight={},
        receipt_path=str(path))
    sb2.prior.checkpoint(row,'prepared_no_start')
    try:
        if a.inspect_off: inspect(row,name,data)
        elif a.execute_powered: execute(row,name,a.execute_powered,data)
        else: sb2.restore(row,name,a.restore_b_drive_off,data)
    except Exception as error:
        row.update(pass_=False,failure=str(error))
        sb2.prior.checkpoint(row,'failed')
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    sb2.prior.checkpoint(row,'complete' if row['pass_'] else 'failed')
    print(('PASS: ' if row['pass_'] else 'FAIL: ')+str(path),flush=True)
    if row.get('failure'): print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
