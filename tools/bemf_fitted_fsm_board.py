"""One supervised 240rpm BEMF fitted-flux A test. Default FILES ONLY.

Flux is an explicitly chosen unqualified command-voltage-model candidate.
No B changes, automatic comparison, retries, contact forcing, or gain changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import psi_ke_high_speed_board as previous
import encoder_saved_fault_report as encoder_report

base=previous.low.base
TMP=base.TMP
ROOT_RESTORE=TMP/'psi-ke-restore-1792590404078518900.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/BemfFittedFluxCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='6e66984d9867de2f25b362c14b6549eec2043406905f031bdf12c1594cbaad3f'
ELF_SHA='a656e26ee84cb1724dcd5033387a3199351fa464b08983d5623559773ef0ceb3'
SIZE=219204
PSI_WB=.00069732
ORIGINAL_MOTION=base.motion
ORIGINAL_DECODE=base.decode_cm
ORIGINAL_BOARD=base.TokenRecordedBoard
ORIGINAL_STAGED=base.staged


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text())
        if c['file'].endswith('/Core/Src/main.c'))
    required=('FOC_BEMF_CANDIDATE=1','FOC_BEMF_ENABLED_DEFAULT=0','FOC_BEMF_PSI_WB=0.00069732f',
        'FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','FOC_ONE_CYCLE_PWM_PIPELINE=1',
        'FOC_PWM_PIPELINE_CLOSED_LOOP=1','FOC_INTENT_FSM_CANDIDATE=1',
        'FOC_FRICTION_ENABLED_DEFAULT=1','AS5047P_DMA_FOC_FIRST=1',
        'FOC_SPEED_PI_ANTI_WINDUP=1','FOC_ACCEL_FF_ENABLED_DEFAULT=1',
        'SPEED_FRICTION_I_A=0.105f','SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0001875f')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or
        base.hw.image_info(data)[0]!='A' or any('-D'+f+' ' not in cmd for f in required) or
        any('-D'+f in cmd for f in ('FOC_PSI_IDENT','FOC_DQ_DECOUPLING_CANDIDATE',
            'DECOUPLING_SIGN_TEST','FOC_CURRENT_STEP_AB_DIAG','FOC_FAST_REJECT_COMPUTE_ONLY')) or
        base.symbols(ELF).get('bemf_frame',(0,0))[1]!=52):
        raise ValueError('Exact offline-tested fitted BEMF image/ELF/flags required')
    for marker in (b'INTENT_FSM_CANDIDATE; manual START only',b'TRIP_MA=4000',
        b'RPM=240 LEASE_US=12000000',b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF',
        b'METHOD=TWO_SAMPLE',b'TRAVEL=20000deg RAM only',b'MOTOR TEST BEMF '):
        if marker not in data:raise ValueError('BEMF/FSM/protection marker absent')
    base.support.support.require_baud(cmd)
    return data


def configure(path):
    # First prove the last B940 restore under the PREVIOUS high-speed image.
    # Then install this new image; never rename old hashes to bypass a check.
    previous.configure(ROOT_RESTORE)
    base.baseline()
    base.IMAGE,base.ELF,base.SHA,base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    base.image=image;base.FRICTION_A=.105
    base.motion=motion;base.decode_cm=decode;base.TokenRecordedBoard=BemfBoard;base.staged=staged
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()


def verify_existing(row,name,data):
    """Read-only proof of an already installed A. No reset/write/activation."""
    if not row.get('powered_no_alarm'):raise ValueError('Fresh supervised powered confirmation required')
    before=base.baseline()
    if before[0x8000:0x8000+len(data)]!=data:
        raise ValueError('Existing image differs; cannot program with drive powered')
    capture=TMP/(name+'-existing.bin');second=TMP/(name+'-independent.bin')
    row['hardware_attempted']=True
    for dest in (capture,second):
        output=base.hw.debug(row,[*base.old.zero.off_gate(),
            'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted B baseline"}',
            *base.hw.full_compare_commands(dest,base.BASE),*base.hw.off_report(),'shutdown'])
        if dest.read_bytes()!=before:raise ValueError('Read-only complete Flash mismatch')
        row['outputs']=base.hw.check_off(output,(0x08040000,))
    row.update(pass_=True,staged_capture=str(capture),staged_sha256=hashlib.sha256(before).hexdigest(),
        independent_capture=str(second),independent_readback_pass=True,
        read_only_existing_verified=True,b_boot_private_metadata_unchanged=True,
        flash_programming=False,activation=False,motor_commands=0,
        final_cpu_halted=True,final_outputs_off=True)


def staged(path,data):
    receipt=json.loads(path.read_text())
    if not receipt.get('read_only_existing_verified'):
        return ORIGINAL_STAGED(path,data)
    capture=Path(receipt.get('staged_capture','')).resolve()
    second=Path(receipt.get('independent_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or second.parent!=TMP.resolve() or
        receipt.get('mode')!='stage' or receipt.get('image_sha256')!=SHA or receipt.get('elf_sha256')!=ELF_SHA or
        receipt.get('flash_programming') is not False or receipt.get('activation') is not False or
        receipt.get('motor_commands')!=0 or any(receipt.get(k) is not True for k in
            ('pass_','powered_no_alarm','independent_readback_pass','final_cpu_halted','final_outputs_off')) or
        Path(receipt.get('baseline_restore_receipt','')).resolve()!=base.BASE_RESTORE_RECEIPT):
        raise ValueError('Exact read-only existing-image readiness receipt required')
    before=base.baseline();raw=capture.read_bytes()
    if (raw!=before or second.read_bytes()!=raw or hashlib.sha256(raw).hexdigest()!=receipt.get('staged_sha256') or
        raw[0x8000:0x8000+len(data)]!=data):
        raise ValueError('Read-only receipt/full Flash/image mismatch')
    return capture,raw


def status(line,on):
    v=base.hw.fields(line)
    if any(v.get(k)!=x for k,x in dict(ON=str(int(on)),CONFIGURED='1',PSI_NWB='697320',DQ_CROSS='0').items()):
        raise RuntimeError('Exact BEMF flux/switch readback required; no START')
    return v


class BemfBoard(ORIGINAL_BOARD):
    """Sparse SAME-FRAME voltage queries; never pair adjacent STATUS frames."""
    query_interval_s=.25
    def __init__(self,*args,**kwargs):
        self.bemf_active=False;self.bemf_pending=None;self.bemf_next=0.
        super().__init__(*args,**kwargs)

    def send(self,command):
        req=super().send(command)
        if command=='START':self.bemf_active=True;self.bemf_next=time.monotonic()+self.query_interval_s
        elif command in ('STOP','MOTOR TEST STOP','ANALOG SAFE'):self.bemf_active=False
        return req

    def read_line(self,seconds=.02):
        now=time.monotonic()
        if self.bemf_active and self.bemf_pending and now-self.bemf_pending[1]>.4:
            self.record.setdefault('bemf_query_errors',[]).append('Sparse voltage reply timeout')
            self.bemf_active=False
        if self.bemf_active and self.bemf_pending is None and now>=self.bemf_next:
            req=super().send('MOTOR TEST BEMF VOLTAGE')
            self.bemf_pending=(req,now);self.bemf_next=now+self.query_interval_s
        line=super().read_line(seconds)
        if line and self.bemf_pending and line.startswith(str(self.bemf_pending[0])+' '):
            self.record.setdefault('bemf_samples',[]).append(dict(reply=line,values=base.hw.fields(line)))
            if ' OK BEMF ' not in line:self.record.setdefault('bemf_query_errors',[]).append(line)
            self.bemf_pending=None
        return line


def motion(board,row):
    row['bemf_before']=status(board.command('MOTOR TEST BEMF STATUS'),False)
    on=row.get('bemf_enabled',True)
    row['bemf_switch']=status(board.command('MOTOR TEST BEMF '+('ON' if on else 'OFF')),on)
    ORIGINAL_MOTION(board,row) # Existing one START, original recipe and stop owner.


def decode(row):
    ORIGINAL_DECODE(row)
    ram=Path(row['ram_capture']).read_bytes()
    row['ram_sha256']=hashlib.sha256(ram).hexdigest()
    addr,size=base.symbols(ELF)['bemf_frame']
    if size!=52 or not 0<=addr-0x20000000<=len(ram)-size:raise ValueError('BEMF ABI/bounds mismatch')
    row['bemf_saved']=dict(zip(('seq source_us enabled saturated valid omega_e id iq '
        'vd_pi vq_pi vq_ff vd vq').split(),struct.unpack_from('<5I8f',ram,addr-0x20000000)))
    row['encoder_saved']=encoder_report.decode_saved(row,ELF)
    row['bemf_capture_semantics']='Sparse coherent VOLTAGE queries + last RAM frame, not full-rate extrema'


def classify(row):
    o=row.get('outputs',{});snap=row.get('snapshot',{});t=snap.get('timing',{});e=row.get('encoder_saved',{})
    terminal=row.get('terminal_status',{});f=base.hw.fields(row.get('postflight',{}).get('MOTOR TEST FAULT',''))
    first=snap.get('first_fault',{})
    # The original FSM records its expected no-load timeout in the PROCESS
    # snapshot. That valid bit is not an independent protection latch.
    process_timeout=(first.get('domain')==3 and first.get('fault_reason')==3 and
        first.get('timeout_reason')==0 and first.get('protection_flags')==0 and
        terminal.get('OUTCOME')=='RUNDOWN_TIMEOUT')
    if (not row.get('final_cpu_halted') or not row.get('final_outputs_off') or
        not row.get('all_app_private_unchanged') or o.get('VTOR')!=0x08008000 or
        o.get('SD',64)&64 or o.get('BDTR',0xc000)&0xc000 or o.get('CCER',1) or
        row.get('start_attempts')!=1 or not row.get('preflight_pass') or
        not row.get('fsm_observation_complete') or terminal.get('OUTCOME')!='RUNDOWN_TIMEOUT' or
        terminal.get('FLT')!='0' or terminal.get('CONTACT')!='0' or
        f.get('VALID')!='0' or f.get('FLAGS')!='0' or (first.get('valid') and not process_timeout) or
        t.get('deadline_miss')!=0 or t.get('actual_late_count')!=0 or
        not 0<t.get('wall_max_us',0)<50 or t.get('actual_margin_min_us',0)<=1 or
        snap['cur_confirm']['fault'] or not e or e['first_fault']['valid'] or
        any(e['counters'][k] for k in ('timeouts','dma_errors','schedule_misses','control_stale')) or
        any(row.get(k) for k in ('token_decode_errors','accel_ff_metrics_error','friction_metrics_error','stop_error','bemf_query_errors'))):
        raise RuntimeError('BEMF protection/timing/terminal/shutdown evidence failed; no retry')
    frames=[s['values'] for s in row.get('bemf_samples',[]) if s['values'].get('VALID')=='1']
    active=[v for v in frames if abs(int(v.get('WE_MRAD_S','0')))>=50000]
    enabled=row.get('bemf_enabled',True)
    if not active or any(v.get('ON')!=str(int(enabled)) for v in active):raise RuntimeError('Missing active BEMF evidence')
    # Wire terms truncate to integer micro-units; tolerate <=3uV quantization.
    if any(abs(int(v['VQ_FF_UV'])-(int(v['WE_MRAD_S'])*PSI_WB*1000 if enabled else 0))>3 for v in active):
        raise RuntimeError('Measured-speed flux formula readback mismatch')
    post_status=base.hw.fields(row.get('postflight',{}).get('STATUS',''))
    dropped=int(post_status.get('UDROP','0'))
    return dict(acquisition_complete=True,tightening_ok=False,outcome='RUNDOWN_TIMEOUT',
        expected_process_timeout_snapshot=bool(first.get('valid') and process_timeout),
        uart_dropped_bytes=dropped,full_uart_telemetry_complete=(dropped==0),
        active_coherent_voltage_frames=len(active),psi_f_wb=PSI_WB,
        foc_max_us=t['wall_max_us'],deadline_miss=t['deadline_miss'],ccr_late=t['actual_late_count'],
        actual_margin_min_us=t['actual_margin_min_us'],
        bemf_abs_observed_peak_v=max(abs(int(v['VQ_FF_UV'])) for v in active)/1e6,
        observed_saturation_frames=sum(v.get('SAT')=='1' for v in active))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--verify-existing-powered',action='store_true')
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:
        p.error('Fresh OFF/unlocked/no-load fixture required')
    if (a.execute_powered or a.verify_existing_powered) and not a.operator_present_drive_on_no_alarm_05a:
        p.error('Fresh ON/no-alarm/operator/0.5A confirmation required')
    source=a.execute_powered or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=configure(selected)
    if not (a.stage_off or a.verify_existing_powered or source):print('OFFLINE PASS: fitted BEMF candidate; no devices');return 0
    mode='stage' if a.stage_off or a.verify_existing_powered else 'restore' if a.restore_b_drive_off else 'run'
    name='bemf-fitted-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],
        samples=[],postflight={},start_attempts=0,automatic_retry=False,
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(selected.resolve()),
        physical_power_off=a.drive_off_unlocked_no_load_fixed,powered_no_alarm=a.operator_present_drive_on_no_alarm_05a,
        friction_enabled=True,bemf_enabled=True,psi_f_wb=PSI_WB,qualified_physical_flux=False,
        speed_target_rpm=240,speed_iq_limit_A=.50,overspeed_trip_rpm=300,
        host_max_seconds=base.HOST_MAX_SECONDS,automatic_parameter_write=False)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.verify_existing_powered:verify_existing(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:
            try:base.execute(row,name,source,data)
            except RuntimeError as error:
                expected='FSM terminal RUNDOWN_TIMEOUT; no-load observation is not successful tightening; no retry'
                if str(error)!=expected:raise
                row['natural_terminal_note']=str(error)
            row['result']=classify(row);row['pass_']=True
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'])
    if row.get('failure'):print(row['failure'])
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
