"""Supervised fixed grid, independent protected boots. Default: files only.

Stage while drive OFF; execute only with present operator and explicit powered
conditions. No current escalation, automatic fault retry, recipe SAVE or B write.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib
import re
import statistics
import friction_fsm_board as base
import friction_calibration_report as analysis

TMP=base.TMP
ROOT_RESTORE=TMP/'friction-fsm-restore-1792486818400514000.json'
RESTORE=TMP/'friction-cal-restore-1792491242366781600.json'
SELECTED_RESTORE=RESTORE
REQUIRED_API_RPM=None
IMAGE=base.old.ROOT/'foc2_app_a/build/FrictionCalibrationDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='a23a7c8760e92cd498d3753065aad12a220ce66514aeac245421869a24a117f0'
ELF_SHA='8a392f5d7ffb72b5849b3b4713c5d1ac5f311b237484b462d9ff28a005e207ee'
FIELDS=('valid reject seen valid_s stable_s iq_sum iq_ref_sum id_sum abs_id_sum '
        'iq_sq_sum speed_sum speed_error_sum start_angle last_angle net_travel abs_travel '
        'rpm used queued prepared admitting active finished passed angle_initialized '
        'encoder_before stop_good_ms').split()


def image():
    raw=IMAGE.read_bytes()
    commands=json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
    cmd=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(cmd)
    if (len(raw)!=212836 or base.old.zero.digest(raw)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or
        base.symbols(ELF).get('friction_calibration',(0,0))[1]!=84 or
        any(flag not in cmd for flag in ('-DFOC_FRICTION_CALIBRATION_DIAG=1',
            '-DFOC_FRICTION_ENABLED_DEFAULT=0','-DFOC_SPEED_FRICTION_CANDIDATE=1')) or
        b'FCAL_DIAGNOSTIC: manual single point; FRIC OFF; no START' not in raw):
        raise ValueError('Exact offline-tested calibration A BIN/ELF required')
    return raw


def configure(path=RESTORE):
    # Validate the original FR1 restoration before replacing runner identities.
    global SELECTED_RESTORE
    base.configure_baseline(ROOT_RESTORE)
    original=base.baseline()
    raw=image()
    path=path.resolve();SELECTED_RESTORE=path
    if path!=ROOT_RESTORE.resolve():
        r=json.loads(path.read_text('utf-8'))
        capture=Path(r.get('final_capture','')).resolve()
        if (path.parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
            r.get('mode')!='restore' or r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
            r.get('motor_commands')!=0 or any(r.get(k) is not True for k in
              ('pass_','all_app_private_unchanged','b_application_not_run','final_cpu_halted','final_outputs_off'))):
            raise ValueError('Exact halted calibration B restore required')
        before=capture.read_bytes();meta=base.old.zero.latest_meta(before);off=r.get('outputs',{})
        if (len(before)!=0x80000 or base.old.zero.digest(before)!=r.get('final_sha256') or
            meta[2:5]!=(2,0,0) or meta[5]<=780 or meta[6:10]!=(len(raw),zlib.crc32(raw),227964,627317606) or
            list(meta)!=r.get('metadata') or before[0x8000:0x8000+len(raw)]!=raw or
            before[:0x8000]!=original[:0x8000] or before[0x40000:0x7e800]!=original[0x40000:0x7e800] or
            before[0x7f800:]!=original[0x7f800:] or off.get('VTOR')!=0x08040000 or
            not off.get('DHCSR',0)&0x20000 or off.get('SD',0x40)&0x40 or
            off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1)):
            raise ValueError('Restoration preservation/identity/output mismatch')
        base.BASE=capture;base.BASE_SHA=base.old.zero.digest(before);base.EXPECT_META=meta
        base.BASE_RESTORE_RECEIPT=path
    base.IMAGE,base.ELF,base.SHA,base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    base.image=image
    return raw


def new_row(name,kind):
    return dict(mode=kind,pass_=False,receipt_path=str(TMP/(name+'.json')),
        image_sha256=SHA,elf_sha256=ELF_SHA,friction_enabled=False,
        baseline_restore_receipt=str(SELECTED_RESTORE),steps=[],commands=[],uart=[],samples=[],
        postflight={},automatic_retry=False,plan=analysis.plan())


def validate_finished(s):
    if s.get('DONE')!='1' or s.get('ACTIVE')!='0' or s.get('FRIC')!='0':
        raise RuntimeError('Calibration did not finish output-OFF; no next point')


def decode_guard(row):
    """Current stopped guard state, not merely the first latched snapshot."""
    path=Path(row['ram_capture']).resolve()
    if path.parent!=TMP.resolve():raise ValueError('Private same-session RAM required')
    ram=path.read_bytes();table=base.symbols(ELF)
    if len(ram)!=0x20000:raise ValueError('Complete RAM capture required')
    result={}
    for name in ('cl_flags','cl_fault_valid','adc_fault','foc_fault','encoder_valid'):
        address,size=table[name]
        if size not in (1,4):raise ValueError('Unexpected guard scalar ABI')
        result[name]=int.from_bytes(ram[address-0x20000000:address-0x20000000+size],'little')
    row['current_guard']=result
    row['ram_sha256']=base.old.zero.digest(ram)
    return result


def classify_point(row):
    """Only an isolated PROCESS/NO_ROTATION may be a nonfatal failed point.

    A newer live guard fault, bad timing, incomplete motion ACK, uncertain stop
    or any other first-fault reason still aborts the entire batch. No fault is
    cleared and no threshold changes: a later point is a new protected boot.
    """
    snap=row.get('snapshot',{});timing=snap.get('timing',{});fault=snap.get('first_fault',{})
    guard=row.get('current_guard',{});off=row.get('outputs',{})
    safe=row.get('safe',{})
    rejection=row.get('command_rejection',row.get('failure',''))
    denied=bool(re.fullmatch(r'\d+ ERR FCAL NOT_READY',rejection))
    if (not row.get('preflight_pass') or row.get('stop_error') or
        row.get('start_attempts')!=1 or (not denied and ' OK FCAL QUEUED ' not in row.get('motion_ack','')) or
        timing.get('deadline_miss',1) or timing.get('actual_late_count',1) or
        not 0<timing.get('wall_max_us',0)<50 or timing.get('actual_margin_min_us',0)<=1 or
        timing.get('actual_commit_count',0)<=0 or snap.get('cur_confirm',{}).get('fault',1) or
        not row.get('final_cpu_halted') or not row.get('final_outputs_off') or
        off.get('VTOR')!=0x08008000 or off.get('SD',0x40)&0x40 or
        off.get('BDTR',0xC000)&0xC000 or off.get('CCER',1) or
        any(safe.get(k)!=v for k,v in dict(LATCHED='1',SD='0',MOE='0',FOC='0').items()) or
        any(guard.get(k,1) for k in ('cl_flags','cl_fault_valid','adc_fault','foc_fault')) or
        guard.get('encoder_valid')!=1 or fault.get('valid') not in (0,1) or
        (not denied and not row.get('terminal'))):
        raise RuntimeError('Safety/timing/stop evidence failed; abort grid')
    point=row.get('calibration_point',{})
    if denied:
        if (fault['valid'] or any(point.get(k,1) for k in ('used','queued','active','seen','valid')) or
            not any(r.get('line')==rejection for r in row.get('uart',[]))):
            raise RuntimeError('Uncertain or unsafe rejection; abort grid')
        return 'NOT_ADMITTED'
    validate_finished(row['terminal'])
    if point.get('finished')!=1 or point.get('active')!=0:
        raise RuntimeError('Unfinished calibration point; no next point')
    if fault['valid']:
        if (fault.get('domain')!=3 or fault.get('fault_reason')!=7 or
            fault.get('protection_flags',1)!=0 or fault.get('encoder_valid')!=1 or
            point.get('passed')!=0):
            raise RuntimeError('Non-NO_ROTATION fault; abort grid')
        return 'NO_ROTATION'
    return 'STEADY' if point.get('passed') else 'NOT_STEADY'


def comparison(row):
    """Keep failed points in the comparison; sparse logs are not steady means."""
    text='\n'.join(d['decoded'] for d in row.get('tokenized_decoded',[]))
    def values(key):
        return [float(v) for v in re.findall(r'\b'+key+r'=([-+0-9.]+)',text)]
    speeds=values('speed_meas');iq=values('iq_meas');refs=values('iq_ref')
    s=row['calibration_point'];net=s.get('net_travel',0)
    result=dict(rpm=row.get('rpm',s['rpm']),repeat=row.get('repeat'),outcome=row['point_outcome'],
        qualified=bool(s['passed']),valid_s=s.get('valid_s',0),reject=s.get('reject',0),
        net_travel_deg=net,total_abs_travel_deg=s.get('abs_travel',0),
        travel_ratio=s.get('abs_travel',0)/abs(net) if abs(net)>1e-6 else None,
        sparse_speed_mean_rpm=statistics.mean(speeds) if speeds else None,
        sparse_speed_min_rpm=min(speeds) if speeds else None,
        sparse_speed_max_rpm=max(speeds) if speeds else None,
        sparse_mean_iq_a=statistics.mean(iq) if iq else None,
        sparse_peak_abs_iq_ref_a=max(map(abs,refs)) if refs else None,
        timing=row['snapshot']['timing'],
        qualification='Sparse log statistics include startup, are not full-rate peaks or qualified steady current')
    return result


def previous_first_point(path):
    """Resume just the explicitly completed +40rpm first measurement, not a fault retry."""
    path=path.resolve();row=json.loads(path.read_text('utf-8'))
    flash=Path(row.get('final_capture','')).resolve()
    if (path.parent!=TMP.resolve() or flash.parent!=TMP.resolve() or row.get('mode')!='point' or
        row.get('image_sha256')!=SHA or row.get('elf_sha256')!=ELF_SHA or row.get('rpm')!=40 or
        row.get('repeat')!=1 or not row.get('all_app_private_unchanged')):
        raise ValueError('Exact stopped first +40rpm receipt required')
    raw=flash.read_bytes();data=image()
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=row.get('final_sha256') or
        raw[0x8000:0x8000+len(data)]!=data):raise ValueError('Prior point Flash/ELF mismatch')
    decode_guard(row)
    row['point_outcome']=classify_point(row)
    row['comparison']=comparison(row)
    return row


def stopped_batch(path):
    """Resume remaining indices after fully proven stopped point receipts.

    No ambiguous command timeout, safety trip, active gate or live-fault state
    can be promoted to a resumable point. Existing failed points are NOT retried.
    """
    path=path.resolve();parent=json.loads(path.read_text('utf-8'));rows=[]
    if (path.parent!=TMP.resolve() or parent.get('mode')!='run' or parent.get('image_sha256')!=SHA or
        parent.get('elf_sha256')!=ELF_SHA or
        tuple(parent.get('plan',{}).get('speeds_rpm',()))!=tuple(analysis.POINTS) or
        not 1<=len(parent.get('points',[]))<24):raise ValueError('Exact partial batch required')
    for index,child_path in enumerate(parent['points']):
        child_path=Path(child_path).resolve();r=json.loads(child_path.read_text('utf-8'))
        if (child_path.parent!=TMP.resolve() or r.get('mode')!='point' or
            r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
            r.get('rpm')!=analysis.POINTS[index%8] or r.get('repeat')!=index//8+1 or
            not r.get('all_app_private_unchanged')):raise ValueError('Partial point identity/order mismatch')
        capture=Path(r.get('final_capture','')).resolve();raw=capture.read_bytes();data=image()
        if (capture.parent!=TMP.resolve() or len(raw)!=0x80000 or
            base.old.zero.digest(raw)!=r.get('final_sha256') or raw[0x8000:0x8000+len(data)]!=data):
            raise ValueError('Partial point exact Flash evidence missing')
        decode_guard(r);r['point_outcome']=classify_point(r);r['comparison']=comparison(r);rows.append(r)
    last=rows[-1];raw=Path(last['final_capture']).read_bytes();original=base.baseline()
    meta=base.old.zero.latest_meta(raw)
    if (meta[2:5]!=(1,0,0) or meta[6:10]!=(len(data),zlib.crc32(data),227964,627317606) or
        raw[:0x8000]!=original[:0x8000] or raw[0x40000:0x7e800]!=original[0x40000:0x7e800] or
        raw[0x7f800:]!=original[0x7f800:]):raise ValueError('Confirmed halted A/B preservation mismatch')
    return dict(rows=rows,source=Path(last['final_capture']),before=raw,receipt=str(path))


def append_measurement(row,child):
    s=child['calibration_point']
    if child.get('point_outcome')=='NOT_ADMITTED':
        # Request identity is not a fabricated measured RPM. Keep raw unstarted
        # diagnostic values in the original receipt and label the report copy.
        s=dict(s,rpm=child['rpm'],raw_diagnostic_rpm=s['rpm'],not_admitted=True)
    row['calibration_points'].append(s)
    row['comparisons'].append(child.get('comparison',dict(rpm=child['rpm'],outcome='NOT_STEADY')))


class CalibrationConsole(base.TokenConsole):
    """Only add three read-only queries; never widen the old motion whitelist."""
    def query(self,text,timeout=2):
        if text not in ('MOTOR TEST FF STATUS','MOTOR TEST FRIC STATUS','MOTOR TEST FCAL STATUS','MOTOR TEST FCAL LIMITS'):
            return super().query(text,timeout)
        self.request+=1;request=self.request
        self.port.write(f'{request} {text}\r\n'.encode('ascii'))
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            line=self.read_line(min(.02,max(0,end-time.monotonic())))
            if line is None:continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '):raise RuntimeError(line)
                return line
        raise TimeoutError('No read ACK; no retry: '+text)


def run_point(row,name,source,before,data,rpm,first):
    hw=base.hw;port=base.support.support.open_port();uart=CalibrationConsole(port,row)
    try:
        row['hardware_attempted']=True
        commands=[*base.old.zero.off_gate(),
            *hw.full_compare_commands(TMP/(name+'-before.bin'),source),
            'reset halt',*hw.off_commands()]
        if first:
            commands+=hw.write_mailbox(base.mailbox(2,2,1,len(data),zlib.crc32(data)))
        commands+=['reset run','shutdown']
        hw.debug(row,commands)
        base.old.prior.wait_health_confirmation(uart,row,hw.fields)
        row['zero']=base.old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        base.profile(uart.query('MOTOR TEST PROFILE'))
        base.filter_profile(uart.query('MOTOR TEST FILTER'))
        base.ff_status(uart.query('MOTOR TEST FF STATUS'))
        base.friction_status(uart.query('MOTOR TEST FRIC STATUS'),False)
        if REQUIRED_API_RPM is not None:
            limits=hw.fields(uart.query('MOTOR TEST FCAL LIMITS'))
            if any(limits.get(k)!=v for k,v in dict(API_RPM=str(REQUIRED_API_RPM),
                    TRIP_RPM='300',IQ_LIMIT_MA='500',GRID='HIGH').items()):
                raise RuntimeError('Actual command range/trip/current mismatch; no motion')
            row['calibration_limits']=limits
        initial=hw.fields(uart.query('MOTOR TEST FCAL STATUS'))
        if any(initial.get(k)!=v for k,v in dict(USED='0',ACTIVE='0',DONE='0',FRIC='0',
                DRIVE_MS='5000',LEASE_US='12000000').items()):
            raise RuntimeError('Unused exact calibration point absent')
        base.old.prior.wait_timing(uart,row)
        # No changes to the command path after this preflight. One uncertain
        # command ACK stops the whole grid; never resend it.
        port.close();board=base.TokenRecordedBoard('COM5',row)
        try:
            base.require_idle_ready(board,'A')
            stack=base.motor_stack(board);row['motor_stack_preflight']=stack
            if stack.get('VALID')!='1' or int(stack.get('FREE_B','0'))<256:
                raise RuntimeError('Insufficient motor-task stack; no calibration start')
            row['preflight_pass']=True;row['start_attempts']=1
            base.old.prior.checkpoint(row,'FCAL_single_command_intent')
            sign='POS' if rpm>0 else 'NEG'
            try:
                row['motion_ack']=board.command('MOTOR TEST FCAL RUN '+sign+' '+str(abs(rpm)),.6)
            except RuntimeError as error:
                if not re.fullmatch(r'\d+ ERR FCAL NOT_READY',str(error)):raise
                row['command_rejection']=str(error)
            end=time.monotonic()+7.5
            while time.monotonic()<end and not row.get('command_rejection'):
                state=hw.fields(board.command('MOTOR TEST STATUS',.6))
                if state.get('FAULT')!='0' or state.get('FLAGS')!='0':
                    raise RuntimeError('Protection fault; abort entire grid, no retry')
                status=hw.fields(board.command('MOTOR TEST FCAL STATUS',.6))
                if status.get('RPM')!=str(rpm):raise RuntimeError('Requested calibration speed mismatch')
                row['samples'].append(dict(at=time.monotonic(),status=status))
                base.old.prior.checkpoint(row,'calibration_feedback')
                if status.get('DONE')=='1' and status.get('ACTIVE')=='0':
                    validate_finished(status);row['terminal']=status;break
                # Collect UART without a blocking sleep or empty polling loop.
                until=min(end,time.monotonic()+.10)
                while time.monotonic()<until: board.read_line(min(.02,until-time.monotonic()))
            else:
                if not row.get('command_rejection'):
                    raise TimeoutError('Calibration stop bound exceeded; no next point')
        finally:
            try: base.stop(board)
            finally:
                try:
                    row['safe_ack']=board.command('ANALOG SAFE',.8)
                    row['safe']=hw.fields(board.command('ANALOG SAFE STATUS',.8))
                    if any(row['safe'].get(k)!=v for k,v in dict(LATCHED='1',SD='0',MOE='0',FOC='0').items()):
                        raise RuntimeError('Output-OFF latch absent')
                finally: board.close()
    finally:
        if port.is_open:
            try:
                row['stop_ack']=uart.query('STOP',.6);row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as error: row['stop_error']=str(error)
            port.close()
        if row.get('hardware_attempted'):
            base.old.capture_stopped(row,name,before,elf=ELF)
            if row['outputs']['VTOR']!=0x08008000: raise RuntimeError('Not calibration A RAM')
            ram=Path(row['ram_capture']).read_bytes();address,size=base.symbols(ELF)['friction_calibration']
            if size!=84: raise ValueError('Calibration ABI mismatch')
            stats=dict(zip(FIELDS,struct.unpack_from('<3I13fi8B2I',ram,address-0x20000000)))
            row['calibration_point']=stats
            decode_guard(row)
    row['point_outcome']=classify_point(row)
    row['comparison']=comparison(row)
    row['pass_']=True  # Acquisition success, not necessarily a usable friction point.


def execute(row,name,stage,data,previous=None,continuation=None):
    if not row.get('powered_no_alarm'): raise ValueError('Fresh supervised powered conditions required')
    source,before=(continuation['source'],continuation['before']) if continuation else base.staged(stage,data)
    row['points']=[];row['calibration_points']=[];row['comparisons']=[];row['hardware_attempted']=True
    if previous:
        row['points'].append(previous['receipt_path'])
        row['calibration_points'].append(previous['calibration_point'])
        row['comparisons'].append(previous['comparison'])
        row['resumed_completed_first_point']=True
    if continuation:
        for child in continuation['rows']:
            row['points'].append(child['receipt_path']);append_measurement(row,child)
        row['continued_from']=continuation['receipt']
    latest={}
    activated=bool(continuation)
    completed=len(row['points'])
    try:
        for repeat in range(3):
            for index,rpm in enumerate(analysis.POINTS):
                if previous and repeat==0 and index==0:continue
                if continuation and repeat*8+index<completed:continue
                point_name=name+'-%02d'%(repeat*8+index)
                child=new_row(point_name,'point');latest=child
                child.update(rpm=rpm,repeat=repeat+1)
                row['points'].append(child['receipt_path'])
                base.old.prior.checkpoint(row,'point_intent')
                print('POINT %d/24: %+d rpm'%(repeat*8+index+1,rpm),flush=True)
                try:
                    run_point(child,point_name,source,before,data,rpm,not activated)
                    activated=True
                except BaseException as error:
                    child['failure']=str(error);raise
                finally: base.old.prior.checkpoint(child,'complete' if child['pass_'] else 'aborted')
                append_measurement(row,child)
                source=Path(child['final_capture']);before=source.read_bytes()
                if not child['calibration_point']['passed']:
                    print('POINT FAILED: '+child.get('point_outcome','NOT_STEADY')+
                          '; saved, outputs verified OFF; next independent point',flush=True)
                base.old.prior.checkpoint(row,'point_saved')
        row['analysis']=analysis.report(row['calibration_points'])
        row['acquisition_complete']=True
        row['pass_']=True
    finally:
        for key in ('final_capture','final_sha256','final_metadata','ram_capture','outputs',
                    'all_app_private_unchanged','final_cpu_halted','final_outputs_off','snapshot'):
            if key in latest: row[key]=latest[key]


def main():
    p=argparse.ArgumentParser(description=__doc__);mode=p.add_mutually_exclusive_group()
    mode.add_argument('--stage-off',action='store_true')
    mode.add_argument('--execute-batch',type=Path)
    mode.add_argument('--continue-stopped-batch',type=Path)
    mode.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-connected-fixed',action='store_true')
    p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--resume-first-point',type=Path,help='Exact completed first +40rpm receipt; acquire the other 23')
    p.add_argument('--operator-present-drive-on-no-alarm-05a-empty-fixed',action='store_true')
    args=p.parse_args()
    if (args.stage_off or args.restore_b_drive_off) and not args.drive_off_connected_fixed:
        p.error('Fresh drive OFF, connected/fixed motor required')
    if (args.execute_batch or args.continue_stopped_batch) and not args.operator_present_drive_on_no_alarm_05a_empty_fixed:
        p.error('Operator must remain present with emergency power-off throughout grid')
    source=args.execute_batch or args.continue_stopped_batch or args.restore_b_drive_off
    selected=args.baseline_restore or (Path(json.loads(source.read_text('utf-8'))['baseline_restore_receipt']) if source else RESTORE)
    data=configure(selected);base.baseline()
    previous=previous_first_point(args.resume_first_point) if args.resume_first_point else None
    continuation=stopped_batch(args.continue_stopped_batch) if args.continue_stopped_batch else None
    if not (args.stage_off or args.execute_batch or args.continue_stopped_batch or args.restore_b_drive_off):
        print(json.dumps(analysis.plan(),indent=2));print('OFFLINE PASS: no device access');return 0
    kind='stage' if args.stage_off else 'restore' if args.restore_b_drive_off else 'run'
    name='friction-cal-'+kind+'-'+str(time.time_ns());row=new_row(name,kind)
    row.update(physical_power_off=args.drive_off_connected_fixed,
               powered_no_alarm=args.operator_present_drive_on_no_alarm_05a_empty_fixed)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if args.stage_off: base.stage(row,name,data)
        elif args.restore_b_drive_off: base.restore(row,name,args.restore_b_drive_off,data)
        else: execute(row,name,args.execute_batch,data,previous,continuation)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'aborted')
    print(('PASS: ' if row['pass_'] else 'STOPPED/FAIL: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
