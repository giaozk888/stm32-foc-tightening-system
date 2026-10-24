"""Pinned dq A: OFF stage, one supervised no-load run, OFF B restoration.

Default is files only. DQ OFF baseline first; ON is a separate manual run.
No firmware/control/threshold changes, forced contact, auto-retry or auto-sweep.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib
import friction_fsm_board as base
import encoder_saved_fault_report as encoder_report

TMP=base.TMP
IMAGE=base.old.ROOT/'foc2_app_a/build/DqDecouplingWireCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='95f36d0226fd25a33d74fbe61cc778264bf15ce565fa02f1225fcfe21095160e'
ELF_SHA='ed4f4430c57e6b8ba18b81b856a7ac9041a273776da8d9c14b111b9438ef7b45'
ROOT_RESTORE=TMP/'dq-fsm-restore-1792578653224597700.json'
ROOT_SHA='f42ae6afcdd938c3f8e6db9aa80754ccd96992fbdf0053808ff5abba8334a63d'
ROOT_A_SHA='5a37e50da1d6628cc40a0c08eecda21f757310c0c538fb0ae91c22e1e20ed911'
ORIGINAL_MOTION=base.motion
ORIGINAL_BOARD=base.TokenRecordedBoard
ORIGINAL_DECODE=base.decode_cm


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text())
             if c['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(cmd)
    required=('FOC_DQ_DECOUPLING_CANDIDATE','FOC_DQ_DECOUPLING_ENABLED_DEFAULT',
        'FOC_CURRENT_PI_IDENTIFIED_ENABLE','FOC_PWM_PIPELINE_CLOSED_LOOP',
        'FOC_INTENT_FSM_CANDIDATE','FOC_ONE_CYCLE_PWM_PIPELINE','AS5047P_DMA_FOC_FIRST',
        'FOC_SPEED_PI_ANTI_WINDUP','FOC_SPEED_SB3_DISABLE_CANDIDATE',
        'FOC_SPEED_SCURVE_CANDIDATE','FOC_ACCEL_FEEDFORWARD_CANDIDATE',
        'FOC_ACCEL_FF_ENABLED_DEFAULT','FOC_SPEED_FRICTION_CANDIDATE','FOC_FRICTION_ENABLED_DEFAULT')
    if (len(data)!=219300 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any(cmd.count('-D'+k+'=1')!=1 for k in required) or
        any('-D'+k+'=1' in cmd for k in ('FOC_CURRENT_STEP_AB_DIAG',
            'FOC_MOTOR_IDENTIFICATION_DIAG','FOC_IDENT_VOLTAGE_STEP_DIAG',
            'FOC_FAST_REJECT_COMPUTE_ONLY','FOC_TORQUE_CHAIN_DIAG')) or
        any(flag not in cmd for flag in ('-DFOC_DQ_LD_H=0.00002003f',
            '-DFOC_DQ_LQ_H=0.00001118f','-DSPEED_FRICTION_I_A=0.105f',
            '-DCURRENT_PI_CANDIDATE_BANDWIDTH_HZ=300.0f',
            '-DSPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0001875f'))):
        raise ValueError('Exact offline-tested dq normal A image/ELF/flags required')
    for marker in (b'INTENT_FSM_CANDIDATE; manual START only',b'TRIP_MA=4000',
                   b'RPM=240 LEASE_US=12000000',b'METHOD=TWO_SAMPLE',
                   b'TRAVEL=20000deg RAM only',b'MOTOR TEST DQ '):
        if marker not in data:raise ValueError('DQ/FSM/protection marker missing')
    if base.symbols(ELF)['dq_decoupling_frame'][1]!=56:
        raise ValueError('Exact latest-frame ABI required')
    return data


def configure(path):
    path=path.resolve()
    if path.parent!=TMP.resolve():raise ValueError('Private restore receipt required')
    r=json.loads(path.read_text('utf-8'));capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Successful halted/output-OFF B restore required')
    raw=capture.read_bytes();root=base.ROOT_BASE.read_bytes();meta=base.old.zero.latest_meta(raw)
    off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=r.get('final_sha256') or
        base.old.zero.digest(root)!=base.ROOT_BASE_SHA or list(meta)!=r.get('metadata') or
        meta[2:5]!=(2,0,0) or meta[8:10]!=(227964,627317606) or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or
        zlib.crc32(raw[0x40000:0x40000+meta[8]])!=meta[9] or
        off.get('VTOR')!=0x08040000 or not off.get('DHCSR',0)&0x20000 or
        off.get('SD',0x40)&0x40 or off.get('BDTR',0xc000)&0xc000 or off.get('CCER',1)):
        raise ValueError('Root B/boot/private/metadata/output identity mismatch')
    if path==ROOT_RESTORE.resolve():
        if (base.old.zero.digest(raw)!=ROOT_SHA or meta[5]!=908 or meta[6]!=218724 or
            base.old.zero.digest(raw[0x8000:0x8000+meta[6]])!=ROOT_A_SHA):
            raise ValueError('Exact B908 root restore required')
    else:
        data=image()
        if (r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or meta[5]<=908 or
            meta[6:8]!=(len(data),zlib.crc32(data)) or raw[0x8000:0x8000+len(data)]!=data):
            raise ValueError('Exact same-dq-image B restoration required')
    base.BASE=capture;base.BASE_SHA=base.old.zero.digest(raw);base.EXPECT_META=meta
    base.BASE_RESTORE_RECEIPT=path
    base.IMAGE=IMAGE;base.ELF=ELF;base.SHA=SHA;base.ELF_SHA=ELF_SHA
    base.image=image;base.FRICTION_A=.105
    base.motion=motion;base.TokenRecordedBoard=DqBoard;base.decode_cm=decode


def dq_status(line,on):
    values=base.hw.fields(line)
    expected=dict(ON=str(int(on)),LD_NH='20030',LQ_NH='11180')
    if any(values.get(k)!=v for k,v in expected.items()):
        raise RuntimeError('Exact DQ switch/inductance readback required; no START')
    return values


class DqBoard(ORIGINAL_BOARD):
    """Sparse evidence queries only; original START/status/stop owner unchanged."""
    def __init__(self,*args,**kwargs):
        self.dq_active=False;self.dq_next=0.;self.dq_pending=None;self.dq_index=0
        super().__init__(*args,**kwargs)

    def send(self,command):
        request=super().send(command)
        if command=='START':self.dq_active=True;self.dq_next=time.monotonic()+.25
        elif command in ('STOP','MOTOR TEST STOP','ANALOG SAFE'):self.dq_active=False
        return request

    def read_line(self,seconds=.02):
        now=time.monotonic()
        if self.dq_active and self.dq_pending and now-self.dq_pending[1]>.4:
            self.record.setdefault('dq_query_errors',[]).append('Sparse query reply timeout')
            self.dq_active=False  # Do not flood UART or resend an uncertain query.
        if self.dq_active and self.dq_pending is None and now>=self.dq_next:
            command='MOTOR TEST DQ '+('STATUS' if self.dq_index%2==0 else 'VOLTAGE')
            request=super().send(command)
            self.dq_pending=(request,now,command);self.dq_index+=1;self.dq_next=now+.25
        line=super().read_line(seconds)
        if line and self.dq_pending and line.startswith(str(self.dq_pending[0])+' '):
            self.record.setdefault('dq_samples',[]).append(dict(host_monotonic_s=time.monotonic(),
                command=self.dq_pending[2],reply=line,values=base.hw.fields(line)))
            if ' OK DQ ' not in line:
                self.record.setdefault('dq_query_errors',[]).append(line);self.dq_active=False
            self.dq_pending=None
        return line


def motion(board,row):
    row['dq_switch']=dq_status(board.command('MOTOR TEST DQ '+('ON' if row['dq_enabled'] else 'OFF')),
                               row['dq_enabled'])
    row['dq_before']=dq_status(board.command('MOTOR TEST DQ STATUS'),row['dq_enabled'])
    ORIGINAL_MOTION(board,row)  # Exactly one original START, 12s lease, all guards.


def decode(row):
    ORIGINAL_DECODE(row)
    ram=Path(row['ram_capture']).read_bytes();addr,size=base.symbols(ELF)['dq_decoupling_frame']
    if size!=56 or not 0<=addr-0x20000000<=len(ram)-size:raise ValueError('DQ SRAM bounds')
    values=struct.unpack_from('<5I9f',ram,addr-0x20000000)
    row['dq_saved']=dict(zip(('seq source_us enabled saturated valid omega_e id iq '
        'vd_pi vq_pi vd_ff vq_ff vd vq').split(),values))
    row['dq_capture_semantics']='Latest binary frame only; UART queries sparse, not full-rate peaks'
    try:row['encoder_saved']=encoder_report.decode_saved(row,ELF)
    except (ValueError,KeyError) as error:row['encoder_decode_error']=str(error)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--dq-on',action='store_true',help='Separate manually approved ON run, no automatic comparison')
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:
        p.error('Fresh OFF/unlocked/no-load/fixed fixture required')
    if a.execute_powered and not a.operator_present_drive_on_no_alarm_05a:
        p.error('Fresh ON/no-alarm/05A/operator fixture required')
    source_path=a.execute_powered or a.restore_b_drive_off
    source=json.loads(source_path.read_text()) if source_path else None
    selected=a.baseline_restore or (Path(source['baseline_restore_receipt']) if source else ROOT_RESTORE)
    configure(selected);data=image();base.baseline()
    if not (a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: pinned integer-wire dq A, B908 root, default no devices');return 0
    if source is not None and source.get('dq_enabled')!=a.dq_on:
        raise ValueError('Exact staged/run DQ mode required')
    kind='stage' if a.stage_off else 'run' if a.execute_powered else 'restore'
    name='dq-fsm-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],
        samples=[],postflight={},image_sha256=SHA,elf_sha256=ELF_SHA,
        baseline_restore_receipt=str(selected.resolve()),baseline_sha256=base.BASE_SHA,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,
        powered_no_alarm=a.operator_present_drive_on_no_alarm_05a,
        no_load=True,shaft_unlocked=True,start_attempts=0,automatic_retry=False,
        friction_enabled=True,friction_a=.105,dq_enabled=a.dq_on,ld_h=.00002003,lq_h=.00001118,
        speed_target_rpm=240,speed_iq_limit_A=.5,overspeed_trip_rpm=300,
        host_max_seconds=base.HOST_MAX_SECONDS,automatic_parameter_write=False)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.execute_powered:base.execute(row,name,a.execute_powered,data)
        else:base.restore(row,name,a.restore_b_drive_off,data)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
