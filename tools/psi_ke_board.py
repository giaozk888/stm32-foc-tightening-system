"""Pinned A-only supervised steady-flux batch. DEFAULT FILES ONLY.

Separate OFF staging, explicit supervised ON execution, OFF B restoration.
Each allowed speed runs once in a fresh protected boot. Never changes gains,
limits, recipe, safety, IRQs, or enables BEMF. Any guard/stop evidence failure
stops the batch; quality-failed windows remain visible and are not retried.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib
import psi_ke_report as report
import dq_original_runtime_board as runtime
import encoder_saved_fault_report as encoder_report

base=runtime.original.base
TMP=base.TMP
ROOT_RESTORE=TMP/'dq-fsm-restore-1792585192772831000.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/PsiKeIdentificationDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='a260cc660b1c6bedaf8bc098c31e53505fd1c7fdd11595a9a1b95d985d186859'
ELF_SHA='76fb625066eb9520500d69a21d68f18de9f37ed9ab8e18944186fbafee37647d'
SIZE=215860
API_LIMIT=250
TRIP_LIMIT=300
POINTS=report.POINTS


def batch_plan():
    return report.plan(API_LIMIT,TRIP_LIMIT,POINTS)


def image():
    data=IMAGE.read_bytes()
    command=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text())
                 if c['file'].endswith('/Core/Src/main.c'))
    flags=('FOC_PSI_IDENT_DIAG=1','FOC_BEMF_CANDIDATE=1','FOC_BEMF_ENABLED_DEFAULT=0',
        'FOC_BEMF_PSI_WB=0.0f','FOC_CURRENT_PI_IDENTIFIED_ENABLE=1',
        'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_FRICTION_ENABLED_DEFAULT=1',
        'AS5047P_DMA_FOC_FIRST=1','FOC_SPEED_PI_ANTI_WINDUP=1')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any('-D'+flag+' ' not in command for flag in flags) or
        '-DFOC_DQ_DECOUPLING_CANDIDATE' in command or '-DDECOUPLING_SIGN_TEST' in command or
        base.symbols(ELF).get('psi_ident',(0,0))[1]!=168 or
        b'PSI_IDENT_DIAGNOSTIC: manual point; no normal START; BEMF unchanged OFF' not in data):
        raise ValueError('Exact offline-tested PSI diagnostic image required')
    return data


def configure(path):
    # Validate the exact preserved stopped B932 and its boot/private root first.
    runtime.configure(ROOT_RESTORE);base.baseline()
    base.IMAGE,base.ELF,base.SHA,base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    base.image=image;base.FRICTION_A=.105
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()


class PsiConsole(base.TokenConsole):
    def query(self,text,timeout=2):
        if text not in ('MOTOR TEST PSI PLAN','MOTOR TEST PSI STATUS','MOTOR TEST PSI RESULT',
                        'MOTOR TEST FF STATUS','MOTOR TEST FRIC STATUS','MOTOR TEST BEMF STATUS'):
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
        raise TimeoutError('No query ACK; no retry: '+text)


def decode(row):
    ram=Path(row['ram_capture']).read_bytes();flash=Path(row['final_capture']).read_bytes()
    if (len(ram)!=0x20000 or hashlib.sha256(flash).hexdigest()!=row['final_sha256'] or
        flash[0x8000:0x8000+SIZE]!=image()):raise ValueError('Complete same-image evidence required')
    row['ram_sha256']=hashlib.sha256(ram).hexdigest();syms=base.symbols(ELF)
    addr,size=syms['psi_ident']
    if size!=168:raise ValueError('PSI ABI changed')
    v=struct.unpack_from('<8f3f6I5Ii8B',ram,addr-0x20000000+68)
    names=('psi_m2 start_angle net_travel encoder_before start_us stable_since window_start '
           'last_observe last_seq seen valid reject stop_good_ms stage rpm '
           'used queued prepared admitting active finished passed window_complete').split()
    row['psi_state']=dict(zip(names,v[8:]));row['psi_state']['mean']=list(v[:8])
    last_index=struct.unpack_from('<I',ram,addr-0x20000000)[0]
    row['psi_log_coverage']=report.trace_coverage(row.get('tokenized_decoded',[]),last_index,row['psi_state']['seen'])
    row['current_guard']={n:int.from_bytes(ram[a-0x20000000:a-0x20000000+s],'little')
        for n in ('cl_flags','cl_fault_valid','adc_fault','foc_fault','encoder_valid') for a,s in [syms[n]]}
    row['encoder_saved']=encoder_report.decode_saved(row,ELF)
    base.decode_cm(row)


def classify(row):
    s=row['psi_state'];t=row['snapshot']['timing'];guard=row['current_guard'];o=row['outputs']
    fault=row['snapshot']['first_fault'];enc=row['encoder_saved']
    if (not row.get('preflight_pass') or row.get('start_attempts')!=1 or
        not row.get('motion_ack','').endswith('OK PSI QUEUED RPM='+str(row['rpm'])) or
        not row.get('final_outputs_off') or not row.get('final_cpu_halted') or
        not row.get('all_app_private_unchanged') or o.get('VTOR')!=0x08008000 or
        o.get('SD',64)&64 or o.get('BDTR',0xc000)&0xc000 or o.get('CCER',1) or
        any(guard[k] for k in ('cl_flags','cl_fault_valid','adc_fault','foc_fault')) or
        guard['encoder_valid']!=1 or fault['valid'] or enc['first_fault']['valid'] or
        any(enc['counters'][k] for k in ('timeouts','dma_errors','schedule_misses','control_stale')) or
        t['deadline_miss'] or t['actual_late_count'] or not 0<t['wall_max_us']<50 or
        t['actual_margin_min_us']<=1 or row['snapshot']['cur_confirm']['fault'] or
        s['active'] or not s['finished'] or s['stage']==4 or s['rpm']!=row['rpm'] or
        row.get('stop_error') or row.get('token_decode_errors')):
        raise RuntimeError('Protection/identity/shutdown/timing evidence failed; stop batch without retry')
    result=report.point(s);result['log_coverage']=row['psi_log_coverage']
    return result


def run_point(row,name,source,before,data,rpm,first):
    port=base.support.support.open_port();uart=PsiConsole(port,row)
    try:
        row['hardware_attempted']=True
        commands=[*base.old.zero.off_gate(),
            *base.hw.full_compare_commands(TMP/(name+'-before.bin'),source),'reset halt',*base.hw.off_commands()]
        if first:commands+=base.hw.write_mailbox(base.mailbox(2,2,1,len(data),zlib.crc32(data)))
        commands+=['reset run','shutdown'];base.hw.debug(row,commands)
        base.old.prior.wait_health_confirmation(uart,row,base.hw.fields)
        if not any('PSI_IDENT_DIAGNOSTIC: manual point;' in line for line in uart.lines):
            raise RuntimeError('Wrong diagnostic marker; no motion')
        row['zero']=base.old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        base.profile(uart.query('MOTOR TEST PROFILE'));base.filter_profile(uart.query('MOTOR TEST FILTER'))
        base.ff_status(uart.query('MOTOR TEST FF STATUS'));base.friction_status(uart.query('MOTOR TEST FRIC STATUS'),True)
        row['plan_readback']=base.hw.fields(uart.query('MOTOR TEST PSI PLAN'))
        p=row['plan_readback']
        for key,value in dict(RS_UOHM='780000',LD_NH='20030',PP='10',MIN_RPM='50',API_RPM=str(API_LIMIT),
                              TRIP_RPM=str(TRIP_LIMIT),WINDOW_MS='2000',LEASE_US='12000000').items():
            if p.get(key)!=value:raise RuntimeError('Identification configuration mismatch: '+key)
        initial=base.hw.fields(uart.query('MOTOR TEST PSI STATUS'))
        if any(initial.get(k)!=v for k,v in dict(USED='0',ACTIVE='0',DONE='0').items()):
            raise RuntimeError('One-shot diagnostic already used')
        if base.hw.fields(uart.query('MOTOR TEST BEMF STATUS')).get('ON')!='0':
            raise RuntimeError('Do not estimate while applying the unknown flux')
        base.old.prior.wait_timing(uart,row)
        port.close();board=base.TokenRecordedBoard('COM5',row)
        try:
            base.require_idle_ready(board,'A')
            stack=base.motor_stack(board)
            if stack.get('VALID')!='1' or int(stack.get('FREE_B',0))<256:
                raise RuntimeError('Motor task stack preflight failed')
            row['preflight_pass']=True;row['start_attempts']=1
            base.old.prior.checkpoint(row,'single_PSI_command_intent')
            row['motion_ack']=board.command('MOTOR TEST PSI RUN '+str(rpm),.8)
            if not row['motion_ack'].endswith('OK PSI QUEUED RPM='+str(rpm)):
                raise RuntimeError('Unknown/rejected motion ACK; do not retry')
            end=time.monotonic()+7.5
            while time.monotonic()<end:
                live=base.hw.fields(board.command('MOTOR TEST STATUS',.8))
                if live.get('FAULT')!='0' or live.get('FLAGS')!='0':
                    raise RuntimeError('Protection triggered; stop entire batch')
                status=base.hw.fields(board.command('MOTOR TEST PSI STATUS',.8))
                row['samples'].append(dict(at=time.monotonic(),status=status))
                if status.get('DONE')=='1' and status.get('ACTIVE')=='0':
                    row['terminal']=status;row['result_wire']=board.command('MOTOR TEST PSI RESULT',.8);break
                # Drain the 20 Hz four-token stream; 4 Hz status queries leave
                # baud headroom and never replace MCU's immediate guards.
                until=min(end,time.monotonic()+.25)
                while time.monotonic()<until:board.read_line(min(.02,until-time.monotonic()))
            else:raise TimeoutError('Point stop bound exceeded; stop batch')
        finally:
            try:
                base.stop(board);row['safe_ack']=board.command('ANALOG SAFE',.8)
                safe=base.hw.fields(board.command('ANALOG SAFE STATUS',.8))
                if any(safe.get(k)!=v for k,v in dict(LATCHED='1',SD='0',MOE='0',FOC='0').items()):
                    raise RuntimeError('Verified shutdown missing')
            finally:board.close()
    finally:
        if port.is_open:
            try:row['stop_ack']=uart.query('STOP',.6);row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as e:row['stop_error']=str(e)
            port.close()
        if row.get('hardware_attempted'):
            base.old.capture_stopped(row,name,before,elf=ELF)
            if row.get('outputs',{}).get('VTOR')==0x08008000:decode(row)
    row['result']=classify(row);row['pass_']=True


def execute(parent,name,path,data):
    if not parent.get('powered_no_alarm'):raise ValueError('Fresh supervised powered confirmation required')
    source,before=base.staged(path,data);first=True;latest={}
    parent['points']=[];parent['results']=[];parent['hardware_attempted']=True
    try:
        for rpm in batch_plan()['runnable']:
            child_name=name+'-'+str(rpm);child=new_row(child_name,'run');latest=child;child['rpm']=rpm
            parent['points'].append(child['receipt_path']);base.old.prior.checkpoint(parent,'point_intent')
            try:run_point(child,child_name,source,before,data,rpm,first)
            except BaseException as e:child['failure']=str(e);raise
            finally:base.old.prior.checkpoint(child,'complete' if child['pass_'] else 'aborted')
            parent['results'].append(child['result']);first=False
            source=Path(child['final_capture']);before=source.read_bytes()
            # No fault recovery: classify just proved a fully stopped healthy
            # previous point. Following reset is the next planned point only.
            if base.old.zero.latest_meta(before)[2:5]!=(1,0,0):raise RuntimeError('Expected confirmed stopped A')
            base.old.prior.checkpoint(parent,'point_saved')
        parent['analysis']=report.fit(parent['results']);parent['acquisition_complete']=True;parent['pass_']=True
    finally:
        for key in ('final_capture','final_sha256','outputs','all_app_private_unchanged',
                    'final_cpu_halted','final_outputs_off','snapshot','ram_capture'):
            if key in latest:parent[key]=latest[key]


def new_row(name,mode):
    return dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],
        postflight={},start_attempts=0,automatic_retry=False,image_sha256=SHA,elf_sha256=ELF_SHA,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),friction_enabled=True,plan=batch_plan())


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--execute-batch',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-whole-batch-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:
        p.error('Fresh drive OFF/unlocked/no-load fixture required')
    if a.execute_batch and not a.operator_present_whole_batch_drive_on_no_alarm_05a:
        p.error('Fresh whole-batch supervised ON/no-alarm/0.5A confirmation required')
    path=a.execute_batch or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(path.read_text())['baseline_restore_receipt']) if path else ROOT_RESTORE)
    data=configure(selected)
    if not (a.stage_off or path):print(json.dumps(batch_plan(),indent=2));print('OFFLINE PASS: no devices');return 0
    mode='stage' if a.stage_off else 'restore' if a.restore_b_drive_off else 'run'
    name='psi-ke-'+mode+'-'+str(time.time_ns());row=new_row(name,mode)
    row['physical_power_off']=a.drive_off_unlocked_no_load_fixed
    row['powered_no_alarm']=a.operator_present_whole_batch_drive_on_no_alarm_05a
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,path,data)
        else:execute(row,name,path,data)
    except BaseException as e:
        row['failure']=str(e)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'aborted')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path']);return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
